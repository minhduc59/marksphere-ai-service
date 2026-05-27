"""Constants for the Publish Post Agent."""

# Engagement score weights for golden hour calculation
ENGAGEMENT_WEIGHTS = {
    "views": 0.2,
    "likes": 0.3,
    "comments": 0.3,
    "shares": 0.2,
}

# Time slot configuration
SLOTS_PER_DAY = 48
SLOT_DURATION_MIN = 30

# Minimum published posts required before using historical data for golden hour
MIN_POSTS_FOR_GOLDEN_HOUR = 10

# TikTok caption limit
TIKTOK_CAPTION_MAX_CHARS = 2200

# Retry configuration
RETRY_DELAYS_SECONDS = [30, 60, 120]
