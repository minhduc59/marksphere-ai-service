from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database — either pass DATABASE_URL directly, or pass discrete DB_* vars
    # (as ECS does) and let the validator below assemble the URL.
    DATABASE_URL: str = "postgresql+asyncpg://scanner:scanner_pass@localhost:5432/marksphere"
    DB_HOST: str | None = None
    DB_PORT: str | None = None
    DB_USER: str | None = None
    DB_PASSWORD: str | None = None
    DB_NAME: str | None = None

    @model_validator(mode="after")
    def _assemble_database_url(self) -> "Settings":
        if self.DB_HOST and self.DB_USER and self.DB_PASSWORD and self.DB_NAME:
            port = self.DB_PORT or "5432"
            self.DATABASE_URL = (
                f"postgresql+asyncpg://{quote_plus(self.DB_USER)}:{quote_plus(self.DB_PASSWORD)}"
                f"@{self.DB_HOST}:{port}/{self.DB_NAME}"
            )
        return self

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # OpenAI
    OPENAI_API_KEY: str = ""

    # App
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    # Firecrawl
    FIRECRAWL_API_KEY: str = ""

    # Modal (FLUX.2-klein fine-tuned image generation)
    MODAL_TOKEN_ID: str = ""
    MODAL_TOKEN_SECRET: str = ""
    MODAL_APP_NAME: str = ""
    MODAL_FUNCTION_NAME: str = ""
    MODAL_CHECKPOINT: str = ""

    # S3 (production storage)
    S3_BUCKET: str = ""
    S3_REGION: str = "ap-southeast-1"
    S3_PREFIX: str = "trending-scanner"

    # Cloudinary (temporary image hosting; replaces local disk for generated post images)
    # Cloudinary (all storage — reports, posts, images, video clips)
    CLOUDINARY_CLOUD_NAME: str | None = None
    CLOUDINARY_API_KEY: str | None = None
    CLOUDINARY_API_SECRET: str | None = None

    # TikTok API
    TIKTOK_CLIENT_KEY: str = ""
    TIKTOK_CLIENT_SECRET: str = ""
    TIKTOK_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/tiktok/callback"
    TIKTOK_DEFAULT_PRIVACY: str = "SELF_ONLY"

    # Token encryption (Fernet key — generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    TOKEN_ENCRYPTION_KEY: str = ""

    # Publishing
    PUBLISH_MAX_RETRIES: int = 3
    PUBLISH_POLL_INTERVAL: int = 10
    PUBLISH_POLL_MAX_ATTEMPTS: int = 30

    # Golden Hour
    DEFAULT_GOLDEN_HOURS: str = "07:00,12:00,19:00"
    TIMEZONE: str = "Asia/Ho_Chi_Minh"

    # A scan / pipeline run still PENDING or RUNNING past this many minutes is
    # treated as stuck (crashed task or service restart) and auto-failed by the
    # watchdog so it stops blocking new runs.
    SCAN_STALE_TIMEOUT_MINUTES: int = 30

    # Backend gateway (NestJS). ai-service only trusts requests that carry
    # the shared internal API key + an X-User-Id header; direct external
    # callers are rejected except for the TikTok OAuth callback.
    BACKEND_ORIGIN: str = "http://localhost:3000"
    INTERNAL_API_KEY: str = ""
    REQUIRE_INTERNAL_AUTH: bool = False

    # When true, scans are dispatched to the ARQ 'scan-processing' worker queue
    # (bounded concurrency, off the API event loop) instead of in-process
    # FastAPI BackgroundTasks. Requires the ai-worker-scan service to be running.
    USE_ARQ_FOR_SCANS: bool = False

    # AssemblyAI (video transcription)
    ASSEMBLY_AI_API_KEY: str = ""

    # Video Clipper
    VIDEO_TEMP_DIR: str = "/tmp/marketing-video-clipper"

    # RapidAPI — used to resolve YouTube media URLs for download (YouTube blocks
    # datacenter/AWS IPs, so we go through a RapidAPI provider instead of yt-dlp).
    RAPIDAPI_KEY: str = ""

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def sync_database_url(self) -> str:
        return self.DATABASE_URL.replace("+asyncpg", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
