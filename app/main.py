from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis
import structlog
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Trending Scanner service", env=settings.APP_ENV)

    # Redis
    try:
        app.state.redis = aioredis.from_url(
            settings.REDIS_URL, decode_responses=True
        )
        await app.state.redis.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning("Redis unavailable, running without cache/rate-limiting", error=str(e))
        app.state.redis = None

    # APScheduler for delayed publish jobs
    jobstores = {"default": MemoryJobStore()}
    if app.state.redis is not None:
        try:
            from apscheduler.jobstores.redis import RedisJobStore

            jobstores["default"] = RedisJobStore(
                host=settings.REDIS_URL.split("://")[1].split(":")[0]
                if "://" in settings.REDIS_URL
                else "localhost",
                port=int(
                    settings.REDIS_URL.split(":")[-1].split("/")[0]
                    if "://" in settings.REDIS_URL
                    else 6379
                ),
                db=int(settings.REDIS_URL.rsplit("/", 1)[-1] or 0),
            )
        except Exception as e:
            logger.warning("Redis job store unavailable, using memory", error=str(e))

    scheduler = AsyncIOScheduler(
        jobstores=jobstores,
        job_defaults={"coalesce": True, "max_instances": 1},
        timezone=ZoneInfo(settings.TIMEZONE),
    )
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("APScheduler started")

    # Register recurring scan schedules as cron jobs.
    from app.services.scan_scheduler import load_schedules, set_scheduler

    set_scheduler(scheduler)
    try:
        await load_schedules(scheduler)
    except Exception as e:
        logger.warning("Failed to load scan schedules", error=str(e))

    # Recover stuck runs. When scans run in-process (FastAPI BackgroundTasks),
    # every non-terminal run is orphaned by this restart, so fail them all
    # (max_age 0). When scans are dispatched to the ARQ worker they survive an
    # ai-service restart, so fall back to the age threshold and let the periodic
    # sweep catch genuine hangs. Either way the periodic sweep below covers runs
    # that hang while the process is alive.
    from app.services.run_recovery import recover_stale_runs

    startup_max_age = (
        0 if not settings.USE_ARQ_FOR_SCANS else settings.SCAN_STALE_TIMEOUT_MINUTES
    )
    try:
        await recover_stale_runs(max_age_minutes=startup_max_age)
    except Exception as e:
        logger.warning("Startup stale-run recovery failed", error=str(e))

    scheduler.add_job(
        recover_stale_runs,
        "interval",
        minutes=5,
        id="stale-run-recovery",
        replace_existing=True,
        kwargs={"max_age_minutes": settings.SCAN_STALE_TIMEOUT_MINUTES},
    )

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    set_scheduler(None)
    logger.info("APScheduler stopped")

    if app.state.redis is not None:
        await app.state.redis.aclose()
    logger.info("Trending Scanner service stopped")


app = FastAPI(
    title="TikTok Technology Trend Scanner",
    description=(
        "AI-powered technology trend scanner for TikTok content creation.\n\n"
        "## Workflow\n"
        "1. **Trigger a scan** — `POST /api/v1/scan` to crawl HackerNews\n"
        "2. **Poll status** — `GET /api/v1/scan/{scan_id}/status` until `completed`\n"
        "3. **Query trends** — `GET /api/v1/trends` with filters\n"
        "4. **View reports** — `GET /api/v1/reports/{scan_run_id}` for TikTok-focused report\n"
        "5. **Generate posts** — `POST /api/v1/posts/generate` to create TikTok content\n"
        "6. **Publish** — `POST /api/v1/publish/{post_id}` to publish to TikTok\n\n"
        "## Data source\n"
        "`hackernews` — Top stories from Hacker News, crawled and analyzed for TikTok relevance.\n\n"
        "## Pipeline\n"
        "HackerNews → GPT-4o Analysis → Content Save → TikTok Report → Database → "
        "Post Generation → Golden Hour Scheduling → TikTok Publish\n\n"
        "## Scan lifecycle\n"
        "`pending` → `running` → `completed` | `partial` | `failed`"
    ),
    version="0.3.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS: once the NestJS gateway fronts all traffic we only need to allow it.
# In development we still accept any origin so Swagger UI / local tools work.
_cors_origins = [settings.BACKEND_ORIGIN] if settings.is_production else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-User-Id", "X-Internal-Api-Key", "X-Request-Id"],
)

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "trending-scanner"}


# Import and register API routers
from app.api.v1.router import v1_router  # noqa: E402

app.include_router(v1_router, prefix="/api/v1")
