"""FFprobe-based media validation for downloaded video files."""

import json
import subprocess
from pathlib import Path
from threading import Event
from typing import Any

from app.domain.downloads import (
    DownloadCancelledError,
    DownloadInterruptedError,
    MediaProbeResult,
    MediaValidationError,
)
from app.domain.extraction import CancellationSignal
from app.infrastructure.processes import capture_process


class FFprobeValidator:
    """Validates downloaded video files using the local ffprobe binary."""

    def __init__(self, ffprobe_bin: str = "ffprobe", timeout_seconds: int = 30) -> None:
        self._ffprobe_bin = ffprobe_bin
        self._timeout_seconds = timeout_seconds

    def validate(
        self,
        file_path: Path,
        *,
        max_resolution: int,
        require_no_audio: bool = True,
        cancel_event: CancellationSignal | None = None,
        shutdown_event: Event | None = None,
    ) -> MediaProbeResult:
        """Inspect a local video file and verify resolution, duration, codec, and audio policy."""
        if not file_path.exists() or not file_path.is_file():
            raise MediaValidationError("Downloaded video file does not exist.")

        file_size = file_path.stat().st_size
        if file_size <= 0:
            raise MediaValidationError("Downloaded video file is empty.")

        cmd = [
            self._ffprobe_bin,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(file_path),
        ]

        def check_stop() -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise DownloadCancelledError("Media validation cancelled by user.")
            if shutdown_event is not None and shutdown_event.is_set():
                raise DownloadInterruptedError("Media validation interrupted by server shutdown.")

        try:
            proc = capture_process(cmd, timeout=self._timeout_seconds, check_stop=check_stop)
        except FileNotFoundError as exc:
            raise MediaValidationError(
                f"ffprobe binary '{self._ffprobe_bin}' not found on PATH."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise MediaValidationError("ffprobe timed out while inspecting video file.") from exc
        except OSError as exc:
            raise MediaValidationError(f"Failed to execute ffprobe: {exc}") from exc

        if proc.returncode != 0:
            raise MediaValidationError(
                f"ffprobe failed to inspect video file (exit code {proc.returncode})."
            )

        try:
            payload: dict[str, Any] = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise MediaValidationError("ffprobe produced invalid JSON output.") from exc

        streams = payload.get("streams")
        if not isinstance(streams, list) or not streams:
            raise MediaValidationError("Video file contains no media streams.")

        video_streams = [
            s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"
        ]
        audio_streams = [
            s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"
        ]

        if not video_streams:
            raise MediaValidationError("Video file contains no video stream.")

        has_audio = len(audio_streams) > 0
        if require_no_audio and has_audio:
            raise MediaValidationError("Video file contains an unexpected audio stream.")

        primary_video = video_streams[0]
        width = int(primary_video.get("width") or 0)
        height = int(primary_video.get("height") or 0)
        codec_name = str(primary_video.get("codec_name") or "").strip()

        if width <= 0 or height <= 0:
            raise MediaValidationError("Video stream has invalid dimensions.")
        if not codec_name:
            raise MediaValidationError("Video stream codec could not be determined.")
        if height > max_resolution:
            raise MediaValidationError(
                f"Video height {height}p exceeds maximum allowed {max_resolution}p."
            )

        duration = self._extract_duration(payload, primary_video)
        if duration <= 0.0:
            raise MediaValidationError("Video file has invalid or zero duration.")

        return MediaProbeResult(
            width=width,
            height=height,
            resolution_label=f"{width}x{height}",
            duration_seconds=duration,
            video_codec=codec_name,
            has_audio=has_audio,
            file_size_bytes=file_size,
        )

    @staticmethod
    def _extract_duration(payload: dict[str, Any], primary_video: dict[str, Any]) -> float:
        fmt = payload.get("format")
        raw_duration = None
        if isinstance(fmt, dict):
            raw_duration = fmt.get("duration")
        if raw_duration is None:
            raw_duration = primary_video.get("duration")
        try:
            return float(raw_duration) if raw_duration is not None else 0.0
        except (TypeError, ValueError):
            return 0.0
