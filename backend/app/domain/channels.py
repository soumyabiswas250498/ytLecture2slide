import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlsplit

YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"})
CHANNEL_TAB_SEGMENTS = frozenset(
    {
        "videos",
        "featured",
        "streams",
        "shorts",
        "playlists",
        "community",
        "posts",
        "about",
        "live",
        "releases",
        "podcasts",
    }
)
YOUTUBE_CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{6,62}$")
YOUTUBE_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,32}$")
HANDLE_RE = re.compile(r"^@[^\s/?#]{2,100}$")
LEGACY_SEGMENT_RE = re.compile(r"^[^\s/?#]{1,100}$")


class ChannelError(Exception):
    """Base domain exception for channel operations."""


class ChannelValidationError(ChannelError):
    """Raised when channel input data fails domain validation."""


class ChannelNotFoundError(ChannelError):
    """Raised when a requested channel does not exist."""


class DuplicateChannelError(ChannelError):
    """Raised when a channel duplicates an existing normalized URL or YouTube channel ID."""


class InvalidCsvError(ChannelError):
    """Raised when an uploaded CSV file cannot be decoded or has invalid headers."""


@dataclass(frozen=True)
class ChannelEntity:
    id: int
    name: str
    channel_url: str
    youtube_channel_id: str | None
    sample_video_url: str | None
    search_keyword: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ChannelSummary:
    total: int
    active: int
    inactive: int


@dataclass(frozen=True)
class ChannelPage:
    items: list[ChannelEntity]
    total: int
    page: int
    page_size: int
    total_pages: int
    summary: ChannelSummary


@dataclass(frozen=True)
class ChannelCreateInput:
    name: str
    channel_url: str
    youtube_channel_id: str | None
    sample_video_url: str | None
    search_keyword: str
    is_active: bool


@dataclass(frozen=True)
class CsvRowIssue:
    row_number: int
    channel_name: str | None
    channel_url: str | None
    reason: str


@dataclass(frozen=True)
class CsvImportSummary:
    total_rows: int
    imported_count: int
    skipped_count: int
    invalid_count: int
    imported: list[ChannelEntity]
    skipped: list[CsvRowIssue]
    errors: list[CsvRowIssue]


def normalize_channel_name(raw_name: str) -> str:
    cleaned = raw_name.strip()
    if not cleaned:
        raise ChannelValidationError("Channel name is required.")
    if len(cleaned) > 255:
        raise ChannelValidationError("Channel name must be 255 characters or fewer.")
    return cleaned


def normalize_search_keyword(raw_keyword: str | None, *, default_keyword: str) -> str:
    if raw_keyword is None:
        return default_keyword
    cleaned = raw_keyword.strip()
    if not cleaned:
        return default_keyword
    if len(cleaned) > 120:
        raise ChannelValidationError("Search keyword must be 120 characters or fewer.")
    return cleaned


def normalize_youtube_channel_id(raw_id: str | None) -> str | None:
    if raw_id is None:
        return None
    cleaned = raw_id.strip()
    if not cleaned:
        return None
    if not YOUTUBE_CHANNEL_ID_RE.match(cleaned):
        raise ChannelValidationError(
            "YouTube channel ID must start with 'UC' and use letters, digits, '_' or '-'."
        )
    return cleaned


def normalize_channel_url(raw_url: str) -> tuple[str, str | None]:
    """Validate and normalize a YouTube channel URL without external requests."""
    cleaned = raw_url.strip()
    if not cleaned:
        raise ChannelValidationError("Channel URL is required.")

    parsed = urlsplit(cleaned)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.netloc:
        raise ChannelValidationError(
            "Channel URL must be a full http(s) URL (for example, https://www.youtube.com/@handle)."
        )
    if parsed.username or parsed.password or parsed.port is not None:
        raise ChannelValidationError("Channel URL must not contain credentials or a custom port.")

    host = parsed.hostname.lower() if parsed.hostname else ""
    if host not in YOUTUBE_HOSTS:
        raise ChannelValidationError(
            "Channel URL must use a supported YouTube domain (youtube.com)."
        )

    segments = [unquote(seg) for seg in parsed.path.split("/") if seg]
    if not segments:
        raise ChannelValidationError(
            "Channel URL must point to a YouTube channel "
            "(/@handle, /channel/UC..., /c/name, or /user/name)."
        )

    if len(segments) >= 2 and segments[-1].lower() in CHANNEL_TAB_SEGMENTS:
        segments = segments[:-1]

    if segments[0].startswith("@"):
        if len(segments) != 1 or not HANDLE_RE.match(segments[0]):
            raise ChannelValidationError("YouTube handle channel URL is invalid.")
        return f"https://www.youtube.com/{segments[0].lower()}", None

    prefix = segments[0].lower()
    if prefix == "channel":
        if len(segments) != 2 or not YOUTUBE_CHANNEL_ID_RE.match(segments[1]):
            raise ChannelValidationError(
                "YouTube /channel/ URL must include a valid UC... channel ID."
            )
        channel_id = segments[1]
        return f"https://www.youtube.com/channel/{channel_id}", channel_id

    if prefix in {"c", "user"}:
        if len(segments) != 2 or not LEGACY_SEGMENT_RE.match(segments[1]):
            raise ChannelValidationError(f"YouTube /{prefix}/ channel URL is invalid.")
        return f"https://www.youtube.com/{prefix}/{segments[1].lower()}", None

    raise ChannelValidationError(
        "Channel URL must point to a YouTube channel "
        "(/@handle, /channel/UC..., /c/name, or /user/name)."
    )


def normalize_sample_video_url(raw_url: str | None) -> str | None:
    """Validate and normalize a YouTube video URL to canonical watch form."""
    if raw_url is None:
        return None
    cleaned = raw_url.strip()
    if not cleaned:
        return None

    parsed = urlsplit(cleaned)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.netloc:
        raise ChannelValidationError("Sample video URL must be a full http(s) YouTube video URL.")
    if parsed.username or parsed.password or parsed.port is not None:
        raise ChannelValidationError(
            "Sample video URL must not contain credentials or a custom port."
        )

    host = parsed.hostname.lower() if parsed.hostname else ""
    segments = [unquote(seg) for seg in parsed.path.split("/") if seg]

    video_id: str | None = None
    if host == "youtu.be":
        if len(segments) == 1:
            video_id = segments[0]
    elif host in YOUTUBE_HOSTS:
        if segments == ["watch"]:
            values = parse_qs(parsed.query).get("v", [])
            if len(values) == 1:
                video_id = values[0]
        elif len(segments) == 2 and segments[0].lower() in {"shorts", "live", "embed"}:
            video_id = segments[1]
    else:
        raise ChannelValidationError(
            "Sample video URL must use a supported YouTube domain (youtube.com or youtu.be)."
        )

    if not video_id or not YOUTUBE_VIDEO_ID_RE.match(video_id):
        raise ChannelValidationError("Sample video URL must include a valid YouTube video ID.")

    return f"https://www.youtube.com/watch?v={video_id}"


def resolve_channel_identity(
    normalized_url: str,
    url_channel_id: str | None,
    explicit_channel_id: str | None,
) -> str | None:
    """Ensure explicit youtube_channel_id does not conflict with a /channel/UC... URL."""
    if url_channel_id and explicit_channel_id and url_channel_id != explicit_channel_id:
        raise ChannelValidationError(
            f"YouTube channel ID does not match the ID in {normalized_url}."
        )
    return explicit_channel_id or url_channel_id
