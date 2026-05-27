import enum


class ScanStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class Platform(str, enum.Enum):
    HACKERNEWS = "hackernews"
    ARTICLE = "article"


class Sentiment(str, enum.Enum):
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    CONTROVERSIAL = "controversial"


class TrendLifecycle(str, enum.Enum):
    EMERGING = "emerging"
    RISING = "rising"
    PEAKING = "peaking"
    SATURATED = "saturated"
    DECLINING = "declining"


class EngagementPrediction(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VIRAL = "viral"


class SourceType(str, enum.Enum):
    OFFICIAL_BLOG = "official_blog"
    NEWS = "news"
    RESEARCH = "research"
    COMMUNITY = "community"
    SOCIAL = "social"


class ContentStatus(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"
    FLAGGED_FOR_REVIEW = "flagged_for_review"
    PUBLISHED = "published"
    REGENERATING = "regenerating"


class PostFormat(str, enum.Enum):
    QUICK_TIPS = "quick_tips"
    HOT_TAKE = "hot_take"
    TRENDING_BREAKDOWN = "trending_breakdown"
    DID_YOU_KNOW = "did_you_know"
    TUTORIAL_HACK = "tutorial_hack"
    MYTH_BUSTERS = "myth_busters"
    BEHIND_THE_TECH = "behind_the_tech"


class PublishStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PublishMode(str, enum.Enum):
    AUTO = "auto"
    MANUAL = "manual"


class ContentType(str, enum.Enum):
    PHOTO = "photo"
    VIDEO = "video"


class VideoTaskStatus(str, enum.Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    CLIPPING = "clipping"
    CAPTIONING = "captioning"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


class VideoClipStatus(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"
    FAILED = "failed"
