"""Discovery service: orchestrates channel ID resolution and video discovery.

Design:
- Synchronous; runs entirely in-process (no background worker yet).
- Uses an in-memory lock to prevent overlapping discovery runs.
- Preserves existing video processing_status on duplicate youtube_video_id.
- Skips inactive channels.
- Never guesses a channel ID; raises ChannelResolutionError on failure.
- Stops gracefully when quota is exhausted, preserving already-discovered videos.
"""

import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import isodate  # type: ignore[import-untyped]

from app.core.config import Settings
from app.domain.channels import ChannelEntity, DuplicateChannelError
from app.domain.videos import (
    ChannelResolutionError,
    DiscoveryAlreadyRunningError,
    DiscoveryRunSummary,
    LivestreamStatus,
    QuotaExhaustedError,
)
from app.infrastructure.youtube_client import YouTubeApiClient, next_quota_reset_utc
from app.repositories.channels import ChannelRepository
from app.repositories.videos import VideoRepository
from app.services.exclusion import VideoExclusionService

logger = logging.getLogger("app.discovery")

_discovery_lock = threading.Lock()
_discovery_running = False


def _parse_duration_seconds(iso_duration: str) -> int:
    """Parse an ISO 8601 duration string (e.g. PT1H23M45S) to total seconds."""
    try:
        duration = isodate.parse_duration(iso_duration)
        return int(duration.total_seconds())
    except Exception:
        return 0


def _resolve_livestream_status(video_item: dict[str, object]) -> LivestreamStatus:
    """Determine livestream status from a videos.list resource."""
    snippet = video_item.get("snippet", {})
    if isinstance(snippet, dict):
        raw = snippet.get("liveBroadcastContent", "none")
        if raw == "upcoming":
            return LivestreamStatus.UPCOMING
        if raw == "live":
            return LivestreamStatus.LIVE
    # Completed livestreams report liveBroadcastContent="none" with liveStreamingDetails populated.
    details = video_item.get("liveStreamingDetails", {})
    if isinstance(details, dict) and details:
        return LivestreamStatus.COMPLETED
    return LivestreamStatus.NONE


def _extract_channel_url_parts(channel_url: str) -> tuple[str, str | None]:
    """Return (url_type, identifier).

    url_type: "id" | "handle" | "user" | "c"
    identifier: the relevant path segment
    """
    parsed = urlsplit(channel_url)
    segments = [s for s in parsed.path.split("/") if s]
    if not segments:
        return "unknown", None
    first = segments[0]
    if first.startswith("@"):
        return "handle", first
    if first == "channel" and len(segments) >= 2:
        return "id", segments[1]
    if first == "user" and len(segments) >= 2:
        return "user", segments[1]
    if first == "c" and len(segments) >= 2:
        return "c", segments[1]
    return "unknown", None


class DiscoveryService:
    """Application service that drives YouTube video discovery runs."""

    def __init__(
        self,
        youtube_client: YouTubeApiClient,
        channel_repo: ChannelRepository,
        video_repo: VideoRepository,
        settings: Settings,
        exclusion_service: VideoExclusionService | None = None,
    ) -> None:
        self._yt = youtube_client
        self._channel_repo = channel_repo
        self._video_repo = video_repo
        self._settings = settings
        self._exclusion_service = exclusion_service

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def discover_all_channels(self) -> DiscoveryRunSummary:
        """Run discovery for every active registered channel."""
        self._acquire_lock()
        summary = DiscoveryRunSummary()
        start = time.monotonic()
        try:
            channels = self._channel_repo.list_all(is_active=True)
            summary.channels_checked = len(channels)
            for channel in channels:
                try:
                    self._discover_channel(channel, summary)
                except QuotaExhaustedError as exc:
                    logger.warning("Quota exhausted: %s", exc)
                    summary.errors.append(str(exc))
                    break
        finally:
            summary.duration_seconds = time.monotonic() - start
            summary.api_requests_made = self._yt.requests_made
            summary.search_requests_made = self._yt.search_quota_used
            summary.quota_reset_at = next_quota_reset_utc()
            self._release_lock()
        return summary

    def discover_one_channel(self, channel_db_id: int) -> DiscoveryRunSummary:
        """Run discovery for a single registered channel by its database ID."""
        self._acquire_lock()
        summary = DiscoveryRunSummary()
        start = time.monotonic()
        try:
            channel = self._channel_repo.get_by_id(channel_db_id)
            if not channel.is_active:
                summary.channels_skipped += 1
                summary.errors.append(f"Channel '{channel.name}' (id={channel_db_id}) is inactive.")
                return summary
            summary.channels_checked = 1
            try:
                self._discover_channel(channel, summary)
            except QuotaExhaustedError as exc:
                logger.warning("Quota exhausted: %s", exc)
                summary.errors.append(str(exc))
        finally:
            summary.duration_seconds = time.monotonic() - start
            summary.api_requests_made = self._yt.requests_made
            summary.search_requests_made = self._yt.search_quota_used
            summary.quota_reset_at = next_quota_reset_utc()
            self._release_lock()
        return summary

    # ------------------------------------------------------------------
    # Channel-level discovery
    # ------------------------------------------------------------------

    def _discover_channel(self, channel: ChannelEntity, summary: DiscoveryRunSummary) -> None:
        """Resolve, search and persist videos for one channel; mutates *summary*."""
        # 1. Resolve channel ID.
        youtube_channel_id = self._ensure_channel_id(channel, summary)
        if youtube_channel_id is None:
            return  # error already recorded in summary

        # 2. Determine search window.
        published_after = datetime.now(UTC) - timedelta(days=self._settings.discovery_lookback_days)
        keyword = channel.search_keyword or self._settings.default_search_keyword
        discovered_at = datetime.now(UTC)

        # 3. Paginate through search results, batch-fetch details, persist.
        page_token: str | None = None
        while True:
            try:
                search_items, page_token = self._yt.search_videos(
                    youtube_channel_id,
                    keyword,
                    published_after,
                    page_token=page_token,
                    max_results=self._settings.discovery_max_results_per_channel,
                )
            except QuotaExhaustedError:
                raise  # propagate to caller
            except ChannelResolutionError as exc:
                logger.error(
                    "Discovery error for channel id=%s name=%s: %s",
                    channel.id,
                    channel.name,
                    exc,
                )
                summary.failed_channels.append(channel.name)
                summary.errors.append(str(exc))
                return

            video_ids = []
            for item in search_items:
                id_obj = item.get("id", {})
                if isinstance(id_obj, dict):
                    vid = id_obj.get("videoId")
                    if isinstance(vid, str):
                        video_ids.append(vid)

            if video_ids:
                self._process_video_batch(
                    video_ids=video_ids,
                    channel=channel,
                    expected_channel_id=youtube_channel_id,
                    discovered_at=discovered_at,
                    summary=summary,
                )

            if not page_token:
                break

    def _ensure_channel_id(
        self, channel: ChannelEntity, summary: DiscoveryRunSummary
    ) -> str | None:
        """Return the resolved youtube_channel_id, persisting it if newly resolved."""
        if channel.youtube_channel_id:
            return channel.youtube_channel_id

        url_type, identifier = _extract_channel_url_parts(channel.channel_url)
        resolved: str | None = None

        try:
            if url_type == "handle" and identifier:
                resolved = self._yt.resolve_channel_by_handle(identifier)
            elif url_type == "user" and identifier:
                resolved = self._yt.resolve_channel_by_username(identifier)
            elif url_type == "c" and identifier:
                # /c/ URLs require a search fallback; try username first.
                resolved = self._yt.resolve_channel_by_username(identifier)
                if resolved is None:
                    resolved = self._yt.search_channel_by_name(identifier)
            elif url_type == "id" and identifier:
                # Already have the ID from the URL — just verify it exists.
                exists = self._yt.resolve_channel_by_id(identifier)
                resolved = identifier if exists else None
        except QuotaExhaustedError:
            raise
        except ChannelResolutionError as exc:
            logger.error(
                "Failed to resolve channel '%s' (id=%s): %s",
                channel.name,
                channel.id,
                exc,
            )
            summary.failed_channels.append(channel.name)
            summary.errors.append(f"Could not resolve channel '{channel.name}': {exc}")
            return None

        if resolved is None:
            msg = (
                f"Could not resolve YouTube channel ID for '{channel.name}' "
                f"({channel.channel_url}). "
                "Check the URL or add the YouTube channel ID manually."
            )
            logger.warning(msg)
            summary.failed_channels.append(channel.name)
            summary.errors.append(msg)
            return None

        # Persist so future runs skip API lookup.
        try:
            self._channel_repo.update(
                channel.id,
                youtube_channel_id=resolved,
                update_youtube_channel_id=True,
            )
            logger.info(
                "Resolved and persisted channel_id=%s for channel id=%s name=%s",
                resolved,
                channel.id,
                channel.name,
            )
        except DuplicateChannelError:
            msg = (
                f"Resolved canonical YouTube channel ID '{resolved}' for '{channel.name}' "
                "already belongs to another registered channel."
            )
            logger.warning(msg)
            summary.failed_channels.append(channel.name)
            summary.errors.append(msg)
            return None
        except Exception as exc:
            logger.warning(
                "Could not persist youtube_channel_id for channel id=%s: %s",
                channel.id,
                exc,
            )
        return resolved

    def _process_video_batch(
        self,
        video_ids: list[str],
        channel: ChannelEntity,
        expected_channel_id: str,
        discovered_at: datetime,
        summary: DiscoveryRunSummary,
    ) -> None:
        """Fetch full details for a batch of video IDs and persist qualifying ones."""
        try:
            details = self._yt.get_videos_details(video_ids)
        except QuotaExhaustedError:
            raise
        except ChannelResolutionError as exc:
            logger.error("Error fetching video details: %s", exc)
            summary.errors.append(str(exc))
            return

        for item in details:
            summary.videos_found += 1
            self._process_video_item(
                item,
                channel=channel,
                expected_channel_id=expected_channel_id,
                discovered_at=discovered_at,
                summary=summary,
            )

    def _process_video_item(  # noqa: C901
        self,
        item: dict[str, object],
        channel: ChannelEntity,
        expected_channel_id: str,
        discovered_at: datetime,
        summary: DiscoveryRunSummary,
    ) -> None:
        """Evaluate a single videos.list resource dict and persist if it qualifies."""
        youtube_video_id = item.get("id")
        if not isinstance(youtube_video_id, str) or not youtube_video_id:
            return

        snippet = item.get("snippet", {})
        content_details = item.get("contentDetails", {})

        if not isinstance(snippet, dict) or not isinstance(content_details, dict):
            return

        # Verify ownership: the video must belong to the registered channel.
        video_channel_id = snippet.get("channelId", "")
        if (
            expected_channel_id
            and isinstance(video_channel_id, str)
            and video_channel_id != expected_channel_id
        ):
            summary.videos_rejected_filter += 1
            logger.debug(
                "Skipping video %s: channelId mismatch (%s vs %s)",
                youtube_video_id,
                video_channel_id,
                expected_channel_id,
            )
            return

        # Livestream filtering.
        livestream_status = _resolve_livestream_status(item)
        if livestream_status in (LivestreamStatus.UPCOMING, LivestreamStatus.LIVE):
            summary.livestreams_deferred += 1
            logger.debug(
                "Deferring video %s: livestream status=%s", youtube_video_id, livestream_status
            )
            return

        # Duration filter.
        raw_duration = content_details.get("duration", "PT0S")
        duration_seconds = _parse_duration_seconds(str(raw_duration))
        if duration_seconds <= self._settings.discovery_min_duration_seconds:
            summary.videos_rejected_duration += 1
            logger.debug(
                "Rejecting video %s: duration %ds <= min %ds",
                youtube_video_id,
                duration_seconds,
                self._settings.discovery_min_duration_seconds,
            )
            return

        # Parse metadata.
        title = str(snippet.get("title", "")).strip() or "(no title)"
        description = str(snippet.get("description", ""))
        thumbnail_url = self._extract_thumbnail(snippet)
        raw_published = snippet.get("publishedAt", "")
        try:
            published_at = datetime.fromisoformat(str(raw_published).replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            published_at = discovered_at

        video_url = f"https://www.youtube.com/watch?v={youtube_video_id}"
        exclusion = (
            self._exclusion_service.classify_title(title)
            if self._exclusion_service is not None
            else None
        )

        _, created = self._video_repo.create_or_skip(
            channel_id=channel.id,
            channel_name=channel.name,
            youtube_channel_id=channel.youtube_channel_id,
            youtube_video_id=youtube_video_id,
            title=title,
            description=description,
            video_url=video_url,
            thumbnail_url=thumbnail_url,
            duration_seconds=duration_seconds,
            published_at=published_at,
            livestream_status=livestream_status,
            discovered_at=discovered_at,
            is_excluded=exclusion.excluded if exclusion is not None else False,
            excluded_keywords=exclusion.matched_keywords if exclusion is not None else None,
        )
        if created:
            summary.new_videos_added += 1
            logger.info("Persisted new video %s: %s", youtube_video_id, title)
        else:
            summary.existing_videos_skipped += 1

    @staticmethod
    def _extract_thumbnail(snippet: dict[str, object]) -> str | None:
        thumbnails = snippet.get("thumbnails", {})
        if not isinstance(thumbnails, dict):
            return None
        for quality in ("high", "medium", "default"):
            thumb = thumbnails.get(quality)
            if isinstance(thumb, dict):
                url = thumb.get("url")
                if isinstance(url, str) and url:
                    return url
        return None

    # ------------------------------------------------------------------
    # Lock management
    # ------------------------------------------------------------------

    @staticmethod
    def _acquire_lock() -> None:
        global _discovery_running  # noqa: PLW0603
        with _discovery_lock:
            if _discovery_running:
                raise DiscoveryAlreadyRunningError(
                    "A discovery run is already in progress. Please wait for it to finish."
                )
            _discovery_running = True

    @staticmethod
    def _release_lock() -> None:
        global _discovery_running  # noqa: PLW0603
        with _discovery_lock:
            _discovery_running = False
