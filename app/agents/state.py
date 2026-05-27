import operator
from typing import Annotated, TypedDict


class RawTrendData(TypedDict):
    platform: str
    items: list[dict]
    error: str | None
    metadata: dict


class ScanError(TypedDict):
    platform: str
    error: str


class TrendScanState(TypedDict):
    # Input
    scan_run_id: str
    platforms: list[str]
    options: dict

    # Scanner outputs - each scanner appends via operator.add
    raw_results: Annotated[list[RawTrendData], operator.add]

    # Trend analyzer output (combined analysis + report)
    analyzed_trends: list[dict]  # Processed articles that passed quality threshold
    discarded_articles: list[dict]  # Articles below quality threshold
    trend_report_md: str  # Full markdown trend report
    analysis_meta: dict  # Meta info (counts, dominant sentiment, top trend, etc.)

    # Content saver output
    content_file_paths: list[str]

    # Report file output
    report_file_path: str

    # Post generation
    generate_posts: bool  # Whether to run the post generation pipeline
    post_gen_options: dict  # {num_posts, formats}
    post_gen_output: dict  # Final output from post generation (content_plan, posts, strategy_update)

    # Control
    errors: Annotated[list[ScanError], operator.add]
