"""yt-dlp video acquisition adapter isolated from business logic."""

import re
import time
from pathlib import Path
from threading import Event
from typing import Any

from yt_dlp import YoutubeDL  # type: ignore[import-untyped]
from yt_dlp.utils import DownloadError as YtDlpDownloadError  # type: ignore[import-untyped]

from app.domain.downloads import (
    DownloadCancelledError,
    DownloadError,
    DownloadInterruptedError,
    DownloadProgress,
    DownloadRequest,
    DownloadStatus,
    ProgressCallback,
    UnsupportedFormatError,
)

_SAFE_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,32}$")
_TRANSIENT_HINTS = (
    "timed out",
    "timeout",
    "connection reset",
    "temporarily unavailable",
    "http error 429",
    "http error 5",
    "network",
    "unable to download webpage",
    "eof occurred",
)
_NON_RECOVERABLE_HINTS = (
    "private video",
    "video unavailable",
    "this video has been removed",
    "members-only",
    "sign in to confirm",
    "requested format is not available",
    "no video formats found",
    "copyright",
    "account associated with this video has been terminated",
)


def sanitize_youtube_video_id(video_id: str) -> str:
    """Validate YouTube video ID to prevent path traversal and invalid filenames."""
    cleaned = video_id.strip()
    if not _SAFE_VIDEO_ID_RE.match(cleaned):
        raise DownloadError(f"Invalid YouTube video ID '{video_id}'.", recoverable=False)
    return cleaned


def resolve_safe_destination(destination_dir: Path, filename: str) -> Path:
    """Resolve a target path inside destination_dir and reject path traversal."""
    root = destination_dir.resolve()
    target = (root / filename).resolve()
    if not target.is_relative_to(root):
        raise DownloadError("Resolved file path escapes the configured download directory.")
    return target


class _QuietLogger:
    """Do not expose upstream signed URLs, headers or credentials in application logs."""

    def debug(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        pass

    def error(self, message: str) -> None:
        pass


class YtDlpVideoDownloader:
    """Official yt-dlp Python integration implementing VideoDownloaderAdapter."""

    def __init__(self, runtime: str = "deno", runtime_path: str | None = None) -> None:
        self._runtime = runtime
        self._runtime_path = runtime_path

    def download(
        self,
        request: DownloadRequest,
        *,
        on_progress: ProgressCallback | None = None,
        cancel_event: Event | None = None,
        shutdown_event: Event | None = None,
    ) -> Path:
        safe_id = sanitize_youtube_video_id(request.youtube_video_id)
        dest_dir = request.destination_dir.resolve()
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Predictable staging template; yt-dlp appends .part while downloading and
        # renames to the final extension upon completion.
        outtmpl = str(resolve_safe_destination(dest_dir, f"{safe_id}.%(ext)s"))
        started_at = time.monotonic()
        last_activity_at = started_at
        last_downloaded_bytes = -1

        def _progress_hook(info: dict[str, Any]) -> None:
            nonlocal last_activity_at, last_downloaded_bytes

            if shutdown_event is not None and shutdown_event.is_set():
                raise DownloadInterruptedError("Download interrupted by server shutdown.")
            if cancel_event is not None and cancel_event.is_set():
                raise DownloadCancelledError("Download cancelled by user.")

            now = time.monotonic()
            if (
                request.max_total_timeout_seconds is not None
                and now - started_at > request.max_total_timeout_seconds
            ):
                raise DownloadError(
                    "Download exceeded configured overall timeout.", recoverable=True
                )

            status = info.get("status")
            if status == "downloading":
                downloaded = int(info.get("downloaded_bytes") or 0)
                if downloaded > last_downloaded_bytes:
                    last_downloaded_bytes = downloaded
                    last_activity_at = now
                elif now - last_activity_at > request.inactivity_timeout_seconds:
                    raise DownloadError(
                        "Download stalled due to network inactivity.", recoverable=True
                    )

                if on_progress is not None:
                    total_raw = info.get("total_bytes") or info.get("total_bytes_estimate")
                    total = int(total_raw) if total_raw else None
                    pct = (downloaded / total * 100.0) if total and total > 0 else 0.0
                    pct = min(max(pct, 0.0), 99.9)
                    speed_raw = info.get("speed")
                    eta_raw = info.get("eta")
                    on_progress(
                        DownloadProgress(
                            video_id=request.video_id,
                            youtube_video_id=safe_id,
                            status=DownloadStatus.DOWNLOADING,
                            progress_percent=round(pct, 1),
                            downloaded_bytes=downloaded,
                            total_bytes=total,
                            speed_bytes_per_sec=(
                                float(speed_raw) if speed_raw is not None else None
                            ),
                            eta_seconds=float(eta_raw) if eta_raw is not None else None,
                            is_live=True,
                        )
                    )

        format_spec = self._build_format_selector(
            max_resolution=request.max_resolution,
            audio_enabled=request.audio_enabled,
        )

        ydl_opts: dict[str, Any] = {
            "js_runtimes": {self._runtime: {"path": self._runtime_path}},
            "remote_components": set(),
            "logger": _QuietLogger(),
            "format": format_spec,
            "outtmpl": outtmpl,
            "noplaylist": True,
            "writesubtitles": False,
            "writeautomaticsub": False,
            "writethumbnail": False,
            "writeinfojson": False,
            "writedescription": False,
            "continuedl": True,
            "overwrites": False,
            "nopart": False,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "socket_timeout": request.connect_timeout_seconds,
            "retries": 0,  # Retry policy is managed at the service layer.
            "progress_hooks": [_progress_hook],
            "format_sort": [f"res:{request.max_resolution}", "ext:mp4:webm"],
        }

        if shutdown_event is not None and shutdown_event.is_set():
            raise DownloadInterruptedError("Download interrupted before start.")
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelledError("Download cancelled before start.")

        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(request.video_url, download=True)
                if not isinstance(info, dict):
                    raise DownloadError("yt-dlp returned no media metadata.", recoverable=False)
                downloaded_path = self._resolve_downloaded_file(ydl, info, dest_dir, safe_id)
        except (DownloadCancelledError, DownloadInterruptedError, DownloadError):
            raise
        except YtDlpDownloadError as exc:
            raise self._classify_ytdlp_error(str(exc)) from exc
        except Exception as exc:
            raise DownloadError(
                "Unexpected acquisition failure. Check runtime and storage permissions.",
                recoverable=False,
            ) from exc

        if shutdown_event is not None and shutdown_event.is_set():
            raise DownloadInterruptedError("Download interrupted by server shutdown.")
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelledError("Download cancelled by user.")

        if not downloaded_path.exists() or not downloaded_path.is_file():
            raise DownloadError(
                "yt-dlp completed without producing an output file.", recoverable=False
            )

        return downloaded_path

    @staticmethod
    def _build_format_selector(*, max_resolution: int, audio_enabled: bool) -> str:
        if audio_enabled:
            return f"bestvideo[height<={max_resolution}]+bestaudio/best[height<={max_resolution}]"
        # Video-only: never fall back to muxed audio+video streams.
        return (
            f"bestvideo[height<={max_resolution}][acodec=none][ext=mp4]/"
            f"bestvideo[height<={max_resolution}][acodec=none]/"
            f"bestvideo[height<={max_resolution}]"
        )

    @staticmethod
    def _resolve_downloaded_file(
        ydl: Any,
        info: dict[str, Any],
        dest_dir: Path,
        safe_id: str,
    ) -> Path:
        requested = info.get("requested_downloads")
        if isinstance(requested, list) and requested:
            filepath = requested[0].get("filepath")
            if isinstance(filepath, str) and filepath:
                resolved = Path(filepath).resolve()
                if resolved.is_relative_to(dest_dir):
                    return resolved

        prepared = ydl.prepare_filename(info)
        resolved = Path(prepared).resolve()
        if resolved.is_relative_to(dest_dir) and resolved.exists():
            return resolved

        for candidate in sorted(dest_dir.glob(f"{safe_id}.*")):
            if candidate.suffix != ".part" and not candidate.name.endswith(".ytdl"):
                return candidate.resolve()

        return resolved

    @staticmethod
    def _classify_ytdlp_error(message: str) -> DownloadError:
        lower = message.lower()
        if "403" in lower or "javascript" in lower or "challenge" in lower:
            return DownloadError(
                "YouTube rejected acquisition. Verify the configured JavaScript runtime and "
                "matching yt-dlp-ejs installation, update the locked yt-dlp packages if needed, "
                "and confirm the video is accessible from this network. Access restrictions "
                "are not bypassed.",
                recoverable=False,
            )
        if "requested format is not available" in lower or "no video formats found" in lower:
            return UnsupportedFormatError(
                "No compatible video-only stream within resolution limit is available.",
                recoverable=False,
            )
        if any(hint in lower for hint in _NON_RECOVERABLE_HINTS):
            return DownloadError(
                "Video unavailable or access restricted. Confirm permission and availability.",
                recoverable=False,
            )
        if any(hint in lower for hint in _TRANSIENT_HINTS):
            return DownloadError(
                "Temporary acquisition failure. Check network connectivity and retry.",
                recoverable=True,
            )
        return DownloadError(
            "Acquisition failed. Check availability, runtime dependencies and network access.",
            recoverable=False,
        )
