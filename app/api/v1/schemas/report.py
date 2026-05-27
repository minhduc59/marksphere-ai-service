import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ContentAngleReport(BaseModel):
    angle: str = Field(description="Content hook (max 15 words)")
    format: str = Field(description="Format: quick_tips, trending_breakdown, hot_take, did_you_know, tutorial_hack, myth_busters, behind_the_tech")
    hook_line: str = Field(description="Scroll-stopper opening line (max 15 words)")


class ProcessedArticle(BaseModel):
    id: str
    title: str
    source_url: str = ""
    source_type: str = Field(default="community", description="official_blog | news | research | community | social")
    quality_score: float
    cleaned_content: str = ""
    key_data_points: list[str] = []
    sentiment: str
    engagement_prediction: str
    lifecycle: str
    content_angles: list[ContentAngleReport] = []
    target_audience: list[str] = []


class DiscardedArticle(BaseModel):
    id: str
    title: str
    quality_score: float
    discard_reason: str


class AnalysisMeta(BaseModel):
    total_input: int = 0
    passed: int = 0
    discarded: int = 0
    dominant_sentiment: str = ""
    top_trend: str = ""
    top_tiktok_format: str = ""
    suggested_posting_window: str = ""


class ReportListItem(BaseModel):
    scan_run_id: uuid.UUID
    generated_at: datetime
    report_file_path: str
    total_items_found: int
    platforms_completed: list[str] = []


class ReportListResponse(BaseModel):
    items: list[ReportListItem]
    total: int


class ReportContentResponse(BaseModel):
    scan_run_id: uuid.UUID
    content: str = Field(description="Full markdown trend report")
    report_file_path: str
    generated_at: datetime


class ReportSummaryResponse(BaseModel):
    scan_run_id: str
    meta: AnalysisMeta = Field(default_factory=AnalysisMeta)
    processed_count: int = 0
    discarded_count: int = 0
    processed_articles: list[ProcessedArticle] = []
    discarded_articles: list[DiscardedArticle] = []
    generated_at: str
