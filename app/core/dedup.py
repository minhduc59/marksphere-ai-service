import hashlib
import re
import unicodedata


def normalize_title(title: str) -> str:
    """Normalize a title for dedup comparison."""
    text = title.lower().strip()
    # Remove accents
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    # Remove special characters, keep alphanumeric and spaces
    text = re.sub(r"[^a-z0-9\s]", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compute_dedup_key(title: str) -> str:
    """Compute a hash key for deduplication."""
    normalized = normalize_title(title)
    # Use first 100 chars to avoid long title noise
    truncated = normalized[:100]
    return hashlib.sha256(truncated.encode()).hexdigest()[:16]


def titles_are_similar(title_a: str, title_b: str, threshold: float = 0.7) -> bool:
    """Check if two titles are similar enough to be the same trend."""
    norm_a = normalize_title(title_a)
    norm_b = normalize_title(title_b)

    if norm_a == norm_b:
        return True

    # Simple word overlap ratio
    words_a = set(norm_a.split())
    words_b = set(norm_b.split())

    if not words_a or not words_b:
        return False

    intersection = words_a & words_b
    union = words_a | words_b
    jaccard = len(intersection) / len(union)

    return jaccard >= threshold
