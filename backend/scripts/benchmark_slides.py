"""Run local slide processing, recording resources and original-file integrity.

Example: python scripts/benchmark_slides.py --frames /data/jobs/frames/1/GEN \
    --output /data/phase6-evaluation --video-id 1 --source /data/jobs/videos/lecture.webm
"""

import argparse
import hashlib
import json
import resource
import sys
import time
from pathlib import Path

from app.domain.slides import SlideConfig
from app.infrastructure.frame_extractor import FFmpegFrameExtractor
from app.services.imaging.pipeline import SlideProcessor


def hashes(directory: Path) -> dict[str, str]:
    result = {}
    for path in directory.iterdir():
        if path.is_file():
            with path.open("rb") as stream:
                result[path.name] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--video-id", type=int, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--configuration", default="{}", help="SlideConfig JSON")
    args = parser.parse_args()
    configuration = SlideConfig.model_validate_json(args.configuration)
    before = hashes(args.frames)
    start = time.monotonic()
    cpu = time.process_time()
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    manifest = SlideProcessor(FFmpegFrameExtractor()).process(
        args.frames, args.output, video_id=args.video_id, config=configuration, source=args.source
    )
    wall = time.monotonic() - start
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    scale = 1 if sys.platform == "darwin" else 1024
    result = {
        "input_count": manifest.input_count,
        "additional_count": len(manifest.additional_sampled_timestamps),
        "output_count": len(manifest.slides),
        "duplicate_count": manifest.duplicate_count,
        "reconstructed_count": sum(s.reconstruction_method != "original" for s in manifest.slides),
        "fallback_count": sum(s.fallback for s in manifest.slides),
        "manual_review_count": sum(s.manual_review for s in manifest.slides),
        "wall_seconds": wall,
        "python_cpu_seconds": time.process_time() - cpu,
        "child_cpu_seconds": children.ru_utime
        + children.ru_stime
        - children_before.ru_utime
        - children_before.ru_stime,
        "peak_python_rss_bytes": usage.ru_maxrss * scale,
        "peak_child_rss_bytes": children.ru_maxrss * scale,
        "output_bytes": sum(p.stat().st_size for p in args.output.rglob("*") if p.is_file()),
        "original_hashes_unchanged": before == hashes(args.frames),
        "verified_reconstruction_accuracy": None,
    }
    (args.output / "benchmark.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
