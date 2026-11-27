"""Typed HTTP client for YouTube Data API v3.

Design decisions:
- Uses httpx (synchronous) rather than google-api-python-client to avoid a heavy SDK.
- API key is accepted as a constructor argument and never logged or included in exceptions.
- Follows current YouTube Data API v3 quota documentation:
  https://developers.google.com/youtube/data/determine_quota_cost
  - `search.list` is tracked in its own dedicated daily quota bucket (default 100 calls/day).
  - General read endpoints (`channels.list`, `videos.list`) draw from the general daily pool
    (default 10,000 units/day, 1 unit per call, up to 50 IDs per batch).
  - Every HTTP request that reaches the API (including pagination and retries) consumes quota.
  - Quotas reset daily at midnight Pacific Time (`America/Los_Angeles`).
- Retries 429 and 5xx responses with exponential back-off (max 3 attempts).
"""

import contextlib
import logging
import time
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.domain.videos import ChannelResolutionError, QuotaExhaustedError

logger = logging.getLogger("app.youtube")

_BASE_URL = "https://www.googleapis.com/youtube/v3"
QUOTA_RESET_TIMEZONE = ZoneInfo("America/Los_Angeles")
_SEARCH_QUOTA = 1  # 1 call in dedicated search.list bucket
_CHANNELS_QUOTA = 1  # 1 unit in general pool
_VIDEOS_QUOTA = 1  # 1 unit in general pool (up to 50 items)
_MAX_RETRIES = 3
_RETRY_STATUSES = {429, 500, 502, 503, 504}


def next_quota_reset_utc(now: datetime | None = None) -> datetime:
    """Return the next midnight America/Los_Angeles converted to UTC."""
    current = (now or datetime.now(UTC)).astimezone(QUOTA_RESET_TIMEZONE)
    next_midnight = datetime(
        current.year,
        current.month,
        current.day,
        tzinfo=QUOTA_RESET_TIMEZONE,
    ) + timedelta(days=1)
    return next_midnight.astimezone(UTC)


class YouTubeApiClient:
    """Lightweight wrapper around the YouTube Data API v3 REST endpoints."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 10.0,
        max_retries: int = _MAX_RETRIES,
        quota_limit: int = 10000,
        search_quota_limit: int = 100,
    ) -> None:
        # Store api_key but never expose it in repr/str, logs, or exceptions.
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._quota_limit = quota_limit
        self._search_quota_limit = search_quota_limit
        self._quota_used = 0
        self._search_quota_used = 0
        self._requests_made = 0
        self._quota_date: date = datetime.now(QUOTA_RESET_TIMEZONE).date()
        self._client = httpx.Client(timeout=timeout)

    def __repr__(self) -> str:
        return (
            f"YouTubeApiClient("
            f"quota_used={self._quota_used}/{self._quota_limit}, "
            f"search_quota_used={self._search_quota_used}/{self._search_quota_limit})"
        )

    @property
    def quota_used(self) -> int:
        self._reset_if_new_pt_day()
        return self._quota_used

    @property
    def quota_remaining(self) -> int:
        self._reset_if_new_pt_day()
        return max(0, self._quota_limit - self._quota_used)

    @property
    def search_quota_used(self) -> int:
        self._reset_if_new_pt_day()
        return self._search_quota_used

    @property
    def search_quota_remaining(self) -> int:
        self._reset_if_new_pt_day()
        return max(0, self._search_quota_limit - self._search_quota_used)

    @property
    def requests_made(self) -> int:
        return self._requests_made

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "YouTubeApiClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Channel resolution
    # ------------------------------------------------------------------

    def resolve_channel_by_id(self, channel_id: str) -> bool:
        """Verify that a /channel/UC... ID exists. Returns False if not found."""
        data = self._get(
            "channels",
            params={"part": "id", "id": channel_id, "maxResults": "1"},
            quota_cost=_CHANNELS_QUOTA,
            is_search=False,
        )
        items = data.get("items", [])
        return isinstance(items, list) and len(items) > 0

    def resolve_channel_by_handle(self, handle: str) -> str | None:
        """Resolve a @handle to a YouTube channel ID."""
        normalised = handle if handle.startswith("@") else f"@{handle}"
        data = self._get(
            "channels",
            params={"part": "id", "forHandle": normalised, "maxResults": "1"},
            quota_cost=_CHANNELS_QUOTA,
            is_search=False,
        )
        return self._extract_first_id(data)

    def resolve_channel_by_username(self, username: str) -> str | None:
        """Resolve a /user/name legacy username to a YouTube channel ID."""
        data = self._get(
            "channels",
            params={"part": "id", "forUsername": username, "maxResults": "1"},
            quota_cost=_CHANNELS_QUOTA,
            is_search=False,
        )
        return self._extract_first_id(data)

    def search_channel_by_name(self, name: str) -> str | None:
        """Last-resort: search for a channel by name using the search.list bucket."""
        data = self._get(
            "search",
            params={
                "part": "id",
                "type": "channel",
                "q": name,
                "maxResults": "1",
            },
            quota_cost=_SEARCH_QUOTA,
            is_search=True,
        )
        items: list[dict[str, object]] = data.get("items", [])  # type: ignore[assignment]
        for item in items:
            snippet = item.get("id", {})
            if isinstance(snippet, dict):
                cid = snippet.get("channelId")
                if isinstance(cid, str) and cid.startswith("UC"):
                    return cid
        return None

    # ------------------------------------------------------------------
    # Video discovery
    # ------------------------------------------------------------------

    def search_videos(
        self,
        channel_id: str,
        keyword: str,
        published_after: datetime,
        *,
        page_token: str | None = None,
        max_results: int = 50,
    ) -> tuple[list[dict[str, object]], str | None]:
        """Search for videos in a channel matching a keyword after a given date."""
        params: dict[str, str] = {
            "part": "id",
            "channelId": channel_id,
            "type": "video",
            "q": keyword,
            "publishedAfter": published_after.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "order": "relevance",
            "maxResults": str(min(max_results, 50)),
        }
        if page_token:
            params["pageToken"] = page_token
        data = self._get(
            "search",
            params=params,
            quota_cost=_SEARCH_QUOTA,
            is_search=True,
        )
        items: list[dict[str, object]] = data.get("items", [])  # type: ignore[assignment]
        next_token: str | None = data.get("nextPageToken")  # type: ignore[assignment]
        return items, next_token

    def get_videos_details(self, video_ids: list[str]) -> list[dict[str, object]]:
        """Retrieve content details and snippet for up to 50 video IDs in one call."""
        if not video_ids:
            return []
        batches = [video_ids[i : i + 50] for i in range(0, len(video_ids), 50)]
        results: list[dict[str, object]] = []
        for batch in batches:
            data = self._get(
                "videos",
                params={
                    "part": "snippet,contentDetails,liveStreamingDetails",
                    "id": ",".join(batch),
                    "maxResults": "50",
                },
                quota_cost=_VIDEOS_QUOTA,
                is_search=False,
            )
            batch_items: list[dict[str, object]] = data.get("items", [])  # type: ignore[assignment]
            results.extend(batch_items)
        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _reset_if_new_pt_day(self) -> None:
        today_pt = datetime.now(QUOTA_RESET_TIMEZONE).date()
        if today_pt != self._quota_date:
            self._quota_used = 0
            self._search_quota_used = 0
            self._quota_date = today_pt

    def _check_quota(self, cost: int, *, is_search: bool) -> None:
        self._reset_if_new_pt_day()
        if is_search:
            if self._search_quota_used + cost > self._search_quota_limit:
                raise QuotaExhaustedError(
                    f"YouTube search.list quota exhausted: "
                    f"{self._search_quota_used}/{self._search_quota_limit} calls used. "
                    f"Resets at midnight America/Los_Angeles."
                )
        elif self._quota_used + cost > self._quota_limit:
            raise QuotaExhaustedError(
                f"YouTube API quota exhausted: "
                f"{self._quota_used}/{self._quota_limit} units used. "
                f"Resets at midnight America/Los_Angeles."
            )

    def _record_quota(self, cost: int, *, is_search: bool) -> None:
        self._requests_made += 1
        if is_search:
            self._search_quota_used += cost
        else:
            self._quota_used += cost

    def _sanitize_text(self, text: str) -> str:
        if not self._api_key:
            return text
        return text.replace(self._api_key, "[REDACTED]")

    def _get(
        self,
        endpoint: str,
        params: dict[str, str],
        *,
        quota_cost: int,
        is_search: bool = False,
    ) -> dict[str, object]:
        url = f"{_BASE_URL}/{endpoint}"
        full_params = dict(params)
        full_params["key"] = self._api_key  # added last; never logged

        last_error_name = "UnknownError"
        for attempt in range(1, self._max_retries + 1):
            self._check_quota(quota_cost, is_search=is_search)
            try:
                response = self._client.get(url, params=full_params)
            except httpx.TimeoutException as exc:
                last_error_name = type(exc).__name__
                logger.warning("YouTube API timeout on attempt %d/%d", attempt, self._max_retries)
                if attempt < self._max_retries:
                    time.sleep(2 ** (attempt - 1))
                continue
            except httpx.RequestError as exc:
                last_error_name = type(exc).__name__
                logger.warning(
                    "YouTube API request error on attempt %d/%d: %s",
                    attempt,
                    self._max_retries,
                    last_error_name,
                )
                if attempt < self._max_retries:
                    time.sleep(2 ** (attempt - 1))
                continue

            # Every HTTP response from the server counts toward quota (including retries/errors).
            self._record_quota(quota_cost, is_search=is_search)

            if response.status_code == 200:
                result: dict[str, object] = response.json()
                return result

            if response.status_code == 403:
                body: dict[str, object] = {}
                with contextlib.suppress(Exception):
                    body = response.json()
                reason = self._extract_error_reason(body)
                if reason in {"quotaExceeded", "dailyLimitExceeded"}:
                    if is_search:
                        self._search_quota_used = self._search_quota_limit
                    else:
                        self._quota_used = self._quota_limit
                    raise QuotaExhaustedError(
                        "YouTube API quota exceeded (HTTP 403). "
                        "Quota resets daily at midnight America/Los_Angeles."
                    )
                message = self._sanitize_text(self._extract_error_message(body))
                raise ChannelResolutionError(f"YouTube API access denied: {message}")

            if response.status_code == 401:
                raise ChannelResolutionError(
                    "YouTube API credentials are invalid. Check your YOUTUBE_API_KEY."
                )

            if response.status_code in _RETRY_STATUSES:
                last_error_name = f"HTTP_{response.status_code}"
                logger.warning(
                    "YouTube API retryable error %s on attempt %d/%d",
                    response.status_code,
                    attempt,
                    self._max_retries,
                )
                if attempt < self._max_retries:
                    time.sleep(2 ** (attempt - 1))
                continue

            body = {}
            with contextlib.suppress(Exception):
                body = response.json()
            message = self._sanitize_text(self._extract_error_message(body))
            raise ChannelResolutionError(f"YouTube API error {response.status_code}: {message}")

        raise ChannelResolutionError(
            f"YouTube API request failed after {self._max_retries} attempts ({last_error_name})."
        )

    @staticmethod
    def _extract_first_id(data: dict[str, object]) -> str | None:
        items: list[dict[str, object]] = data.get("items", [])  # type: ignore[assignment]
        for item in items:
            cid = item.get("id")
            if isinstance(cid, str) and cid.startswith("UC"):
                return cid
        return None

    @staticmethod
    def _extract_error_reason(body: dict[str, object]) -> str:
        try:
            errors = body["error"]["errors"]  # type: ignore[index]
            if isinstance(errors, list) and errors:
                reason = errors[0].get("reason", "")
                return str(reason)
        except (KeyError, TypeError, IndexError):
            pass
        return ""

    @staticmethod
    def _extract_error_message(body: dict[str, object]) -> str:
        try:
            message = body["error"]["message"]  # type: ignore[index]
            return str(message)
        except (KeyError, TypeError):
            return "Unknown error"
