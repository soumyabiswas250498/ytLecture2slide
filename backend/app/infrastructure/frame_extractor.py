"""Single-pass FFmpeg sampling with source PTS and atomic manifests."""

import json
import math
import os
import queue
import re
import shutil
import struct
import subprocess
import threading
import time
import zlib
from contextlib import suppress
from fractions import Fraction
from pathlib import Path
from typing import Literal

from app.domain.downloads import DownloadCancelledError
from app.domain.extraction import (
    CancellationSignal,
    ExtractionCancelled,
    ExtractionError,
    ExtractionResult,
    FrameMetadata,
    ProgressCallback,
)
from app.infrastructure.media_probe import FFprobeValidator
from app.infrastructure.processes import terminate_process


def validate_png(path: Path, width: int, height: int) -> None:
    """Check PNG chunk integrity without loading the image collection into memory."""
    with path.open("rb") as stream:
        if stream.read(8) != b"\x89PNG\r\n\x1a\n":
            raise ExtractionError("Invalid PNG signature.")
        first = True
        decompressor = zlib.decompressobj()
        has_image_data = False
        while True:
            header = stream.read(8)
            if len(header) != 8:
                raise ExtractionError("Truncated PNG.")
            size, kind = struct.unpack(">I4s", header)
            crc = zlib.crc32(kind)
            remaining = size
            if first:
                if kind != b"IHDR" or size != 13:
                    raise ExtractionError("Invalid PNG header.")
                data = stream.read(size)
                if len(data) != size or struct.unpack(">II", data[:8]) != (width, height):
                    raise ExtractionError("Frame resolution differs from source.")
                crc = zlib.crc32(data, crc)
                remaining = 0
                first = False
            while remaining:
                data = stream.read(min(remaining, 65536))
                if not data:
                    raise ExtractionError("Truncated PNG data.")
                remaining -= len(data)
                crc = zlib.crc32(data, crc)
                if kind == b"IDAT":
                    has_image_data = True
                    try:
                        decompressor.decompress(data, 65536)
                        while decompressor.unconsumed_tail:
                            decompressor.decompress(decompressor.unconsumed_tail, 65536)
                    except zlib.error as exc:
                        raise ExtractionError("PNG image data is invalid.") from exc
            checksum = stream.read(4)
            if len(checksum) != 4 or struct.unpack(">I", checksum)[0] != crc:
                raise ExtractionError("PNG checksum mismatch.")
            if kind == b"IEND":
                if not has_image_data or not decompressor.eof:
                    raise ExtractionError("PNG image data is incomplete.")
                return


def read_manifest(directory: Path, *, validate_images: bool = True) -> ExtractionResult:
    if (directory / "manifest.json").is_symlink():
        raise ExtractionError("Unsafe manifest path.")
    result = ExtractionResult.model_validate_json((directory / "manifest.json").read_text())
    if result.frame_count != len(result.frames) or not result.frames:
        raise ExtractionError("Manifest frame count is invalid.")
    if result.status != "extracted":
        raise ExtractionError("Manifest is not a successful extraction.")
    previous = -1.0
    previous_actual = -1.0
    names: set[str] = set()
    for frame in result.frames:
        if frame.requested_timestamp <= previous or frame.filename in names:
            raise ExtractionError("Manifest ordering or filenames are invalid.")
        if (
            frame.actual_timestamp < previous_actual
            or frame.filename != f"frame_{round(frame.requested_timestamp * 1000):09d}.png"
        ):
            raise ExtractionError("Manifest source timestamps or filenames are inconsistent.")
        previous_actual = frame.actual_timestamp
        previous = frame.requested_timestamp
        names.add(frame.filename)
        target = directory / frame.filename
        if target.is_symlink() or not target.resolve().is_relative_to(directory.resolve()):
            raise ExtractionError("Unsafe frame path.")
        if validate_images:
            validate_png(target, frame.width, frame.height)
    return result


class FFmpegFrameExtractor:
    def __init__(
        self,
        *,
        min_free_disk_mb: int = 500,
        threads: int = 1,
        strategy: Literal["seek", "sequential"] = "seek",
        max_frames: int = 100000,
        max_filter_bytes: int = 32000,
    ) -> None:
        self._min_free_bytes = min_free_disk_mb * 1024 * 1024
        self._threads = threads
        self._strategy = strategy
        self._max_frames = max_frames
        self._max_filter_bytes = max_filter_bytes

    def _check_disk(self, directory: Path) -> None:
        if shutil.disk_usage(directory).free < self._min_free_bytes:
            raise ExtractionError("Insufficient free disk space for frame extraction.")

    def extract(
        self,
        source: Path,
        output: Path,
        *,
        video_id: str,
        interval: float = 60,
        start: float = 0,
        end: float | None = None,
        timestamps: list[float] | None = None,
        on_progress: ProgressCallback | None = None,
        cancel: CancellationSignal | None = None,
    ) -> ExtractionResult:
        begun = time.monotonic()
        if cancel and cancel.is_set():
            raise ExtractionCancelled("Extraction cancelled.")
        try:
            probe = FFprobeValidator().validate(
                source, max_resolution=65536, require_no_audio=False, cancel_event=cancel
            )
        except DownloadCancelledError as exc:
            raise ExtractionCancelled("Extraction interrupted during media validation.") from exc
        stop = probe.duration_seconds if end is None else min(end, probe.duration_seconds)
        if not all(math.isfinite(x) for x in (interval, start, stop)):
            raise ExtractionError("Timestamps and interval must be finite.")
        if interval < 0.001 or start < 0 or stop <= start:
            raise ExtractionError("Invalid sampling interval or time range.")
        if timestamps is None:
            if math.ceil((stop - start) / interval) > self._max_frames:
                raise ExtractionError("Requested frame count exceeds configured extraction limit.")
            requested = [start + i * interval for i in range(math.ceil((stop - start) / interval))]
        else:
            if len(timestamps) > self._max_frames:
                raise ExtractionError("Requested frame count exceeds configured extraction limit.")
            requested = sorted(set(timestamps))
        if not requested or any(not math.isfinite(t) or t < start or t >= stop for t in requested):
            raise ExtractionError("Requested timestamps must lie within the video time range.")
        milliseconds = [round(t * 1000) for t in requested]
        if len(set(milliseconds)) != len(milliseconds):
            raise ExtractionError("Timestamps collide at millisecond filename precision.")
        output.mkdir(parents=True, exist_ok=True)
        if any(output.iterdir()):
            raise ExtractionError("Output directory must be empty; existing results are preserved.")
        try:
            with (output / ".extraction.lock").open("x"):
                pass
        except FileExistsError as exc:
            raise ExtractionError("Extraction already owns this output directory.") from exc
        self._check_disk(output)
        stat = source.stat()
        if timestamps is None:
            selection = (
                f"gte(t,{start})*lt(t,{stop})*"
                f"(isnan(prev_pts)+lt(prev_pts*TB,{start})+"
                f"gt(floor((t-{start})/{interval}),floor((prev_pts*TB-{start})/{interval})))"
            )
        else:
            selection = "+".join(
                f"gte(t,{t})*(isnan(prev_pts)+lt(prev_pts*TB,{t}))" for t in requested
            )
        command = [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-nostats",
            "-threads",
            str(self._threads),
            "-filter_threads",
            str(self._threads),
            "-noautorotate",
            "-i",
            str(source.resolve()),
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-dn",
            "-vf",
            f"setpts=PTS-STARTPTS,trim=end={stop},select='{selection}',showinfo",
            "-fps_mode",
            "vfr",
            "-threads",
            str(self._threads),
            "-compression_level",
            "6",
            str(output / "sample_%09d.png"),
        ]
        # Large explicit lists use seeking to stay below subprocess argument limits.
        strategy = self._strategy
        if len(selection.encode()) > self._max_filter_bytes:
            strategy = "seek"
        if strategy == "sequential":
            actual = self._decode(command, output, cancel, on_progress, len(requested))
        else:
            actual = []
            prefix = command[: command.index("-i")]
            for i, timestamp in enumerate(requested):
                # Input seeking decodes only the target GOP; copyts preserves source PTS.
                seek_command = prefix + [
                    "-ss",
                    str(timestamp),
                    "-copyts",
                    "-start_at_zero",
                    "-i",
                    str(source.resolve()),
                    "-map",
                    "0:v:0",
                    "-an",
                    "-sn",
                    "-dn",
                    "-vf",
                    "showinfo",
                    "-frames:v",
                    "1",
                    "-fps_mode",
                    "vfr",
                    "-threads",
                    str(self._threads),
                    "-compression_level",
                    "6",
                    "-start_number",
                    str(i + 1),
                    str(output / "sample_%09d.png"),
                ]
                selected_pts = self._decode(seek_command, output, cancel, None, 1)
                if (
                    not selected_pts
                    or selected_pts[0] >= stop
                    or not (output / f"sample_{i + 1:09d}.png").is_file()
                ):
                    raise ExtractionError("No source frame exists at a requested timestamp.")
                actual.append(selected_pts[0])
                if on_progress:
                    on_progress(i + 1, len(requested))
        frames: list[FrameMetadata] = []
        selected = 0
        for i, target in enumerate(requested):
            # A VFR frame can satisfy several requested timestamps after a long gap.
            while selected < len(actual) and actual[selected] + 1e-5 < target:
                selected += 1
            if selected == len(actual):
                raise ExtractionError("No source frame exists at or after a requested timestamp.")
            name = f"frame_{milliseconds[i]:09d}.png"
            if cancel and cancel.is_set():
                raise ExtractionCancelled("Extraction cancelled during frame validation.")
            self._check_disk(output)
            shutil.copyfile(output / f"sample_{selected + 1:09d}.png", output / name)
            validate_png(output / name, probe.width, probe.height)
            frames.append(
                FrameMetadata(
                    filename=name,
                    requested_timestamp=target,
                    actual_timestamp=actual[selected],
                    width=probe.width,
                    height=probe.height,
                )
            )
        if cancel and cancel.is_set():
            raise ExtractionCancelled("Extraction cancelled before publication.")
        final_stat = source.stat()
        if (stat.st_size, stat.st_mtime_ns) != (final_stat.st_size, final_stat.st_mtime_ns):
            raise ExtractionError("Source video changed during extraction.")
        result = ExtractionResult(
            video_id=video_id,
            source_path=str(source.resolve()),
            source_size_bytes=stat.st_size,
            source_mtime_ns=stat.st_mtime_ns,
            video_duration=probe.duration_seconds,
            interval_seconds=interval if timestamps is None else None,
            start_timestamp=start,
            end_timestamp=stop,
            frames=frames,
            frame_count=len(frames),
            processing_duration=time.monotonic() - begun,
            strategy=strategy,
            decoder_threads=self._threads,
            source_codec=probe.video_codec,
        )
        temporary = output / "manifest.json.tmp"
        with temporary.open("w") as stream:
            json.dump(result.model_dump(mode="json"), stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output / "manifest.json")
        read_manifest(output)
        for sample in output.glob("sample_*.png"):
            sample.unlink()
        return result

    def _decode(
        self,
        command: list[str],
        output: Path,
        cancel: CancellationSignal | None,
        on_progress: ProgressCallback | None,
        expected: int,
    ) -> list[float]:
        lines: queue.Queue[str | None] = queue.Queue(maxsize=256)
        actual: list[float] = []
        time_base: Fraction | None = None
        with subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=os.name == "posix",
        ) as process:
            assert process.stderr is not None

            def consume() -> None:
                assert process.stderr is not None
                for line in process.stderr:
                    lines.put(line)
                lines.put(None)

            reader = threading.Thread(target=consume, daemon=True)
            reader.start()
            try:
                while True:
                    if cancel and cancel.is_set():
                        raise ExtractionCancelled("Extraction cancelled.")
                    self._check_disk(output)
                    try:
                        line = lines.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if line is None:
                        break
                    configuration = re.search(r"config in time_base:\s*(\d+/\d+)", line)
                    if configuration:
                        time_base = Fraction(configuration[1])
                    match = re.search(r"\bn:\s*\d+.*?\bpts:\s*(-?\d+)", line)
                    if match:
                        if time_base is None:
                            raise ExtractionError("FFmpeg did not report a source time base.")
                        actual.append(float(int(match[1]) * time_base))
                        if on_progress:
                            on_progress(max(0, len(actual) - 1), expected)
                if process.wait() != 0:
                    raise ExtractionError(
                        "FFmpeg could not extract frames; inspect the source media."
                    )
            finally:
                terminate_process(process)
                # Drain the bounded queue so the reader can always terminate.
                while reader.is_alive():
                    with suppress(queue.Empty):
                        lines.get(timeout=0.1)
                reader.join()
        return actual
