"""Measure local extraction resources and optionally compare sparse input seeking.

Run from backend: uv run python -m scripts.benchmark_extraction SOURCE OUTPUT --compare-seek
"""

import argparse
import json
import resource
import subprocess
import sys
import time
from pathlib import Path

from app.infrastructure.frame_extractor import FFmpegFrameExtractor


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--strategy", choices=["seek", "sequential"], default="seek")
    parser.add_argument("--interval", type=float, default=60)
    parser.add_argument("--end", type=float)
    parser.add_argument("--compare-seek", action="store_true")
    args = parser.parse_args()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.monotonic()
    result = FFmpegFrameExtractor(strategy=args.strategy).extract(
        args.source, args.output, video_id="benchmark", interval=args.interval, end=args.end
    )
    elapsed = time.monotonic() - start
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime
    report: dict[str, object] = {
        "strategy": args.strategy,
        "video_duration_seconds": result.video_duration,
        "sampled_end_seconds": result.end_timestamp,
        "extraction_wall_seconds": elapsed,
        "extraction_cpu_seconds": cpu,
        "average_cpu_percent_one_core": cpu / elapsed * 100,
        "peak_child_rss_bytes": after.ru_maxrss * (1 if sys.platform == "darwin" else 1024),
        "frame_count": result.frame_count,
        "dimensions": [result.frames[0].width, result.frames[0].height],
        "frame_storage_bytes": sum(
            (args.output / f.filename).stat().st_size for f in result.frames
        ),
        "maximum_timestamp_delay_seconds": max(
            f.actual_timestamp - f.requested_timestamp for f in result.frames
        ),
    }
    if args.compare_seek:
        destination = args.output / "seek-comparison"
        destination.mkdir()
        begun = time.monotonic()
        for frame in result.frames:
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-nostdin",
                    "-threads",
                    "1",
                    "-ss",
                    str(frame.requested_timestamp),
                    "-i",
                    str(args.source),
                    "-an",
                    "-sn",
                    "-dn",
                    "-frames:v",
                    "1",
                    "-threads",
                    "1",
                    "-filter_threads",
                    "1",
                    str(destination / frame.filename),
                ],
                check=True,
                capture_output=True,
            )
        report["seek_comparison_wall_seconds"] = time.monotonic() - begun
        report["seek_comparison_note"] = (
            "Timing baseline only; this command does not publish a timestamp manifest."
        )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
