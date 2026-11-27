"""Offline preservation and slide-job lifecycle regression tests."""

import hashlib
import threading
import time
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.domain.extraction import ExtractionCancelled, ExtractionResult, FrameMetadata
from app.domain.slides import Crop, SlideConfig, SlideError, SlideManifest
from app.services.imaging.board import Image, isolate_board, perspective
from app.services.imaging.obstruction import obstruction_masks
from app.services.imaging.pipeline import (
    SlideProcessor,
    load_image,
    read_slide_manifest,
    sample_timestamps,
)
from app.services.imaging.reconstruction import reconstruct
from app.services.imaging.similarity import compare


@pytest.fixture
def config() -> SlideConfig:
    return SlideConfig(adaptive_enabled=False, min_free_disk_mb=0)


def question(text: str = "Question 1: which city?") -> Image:
    image = np.full((240, 400, 3), 210, dtype=np.uint8)
    cv2.putText(image, text, (10, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (10, 10, 10), 1)
    for i, value in enumerate(["A: City A", "B: City B", "C: City C", "D: City D"]):
        cv2.putText(image, value, (20, 85 + i * 35), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (10, 10, 10), 1)
    return image


def generation(path: Path, images: list[Image]) -> Path:
    path.mkdir(parents=True)
    frames = []
    for index, image in enumerate(images):
        name = f"frame_{index * 60000:09d}.png"
        assert cv2.imwrite(str(path / name), image)
        frames.append(
            FrameMetadata(
                filename=name,
                requested_timestamp=index * 60,
                actual_timestamp=index * 60,
                width=image.shape[1],
                height=image.shape[0],
            )
        )
    result = ExtractionResult(
        video_id="1",
        source_path="/unused",
        source_size_bytes=1,
        source_mtime_ns=1,
        video_duration=len(images) * 60,
        interval_seconds=60,
        start_timestamp=0,
        end_timestamp=len(images) * 60,
        frames=frames,
        frame_count=len(frames),
        processing_duration=0,
    )
    (path / "manifest.json").write_text(result.model_dump_json())
    return path


def test_crop_preserves_pixels(config: SlideConfig) -> None:
    image = question()
    result = isolate_board(
        image, config.model_copy(update={"crop": Crop(left=0.1, right=0.9, top=0.1, bottom=0.9)})
    )
    assert np.array_equal(result.image, image[24:216, 40:360])
    assert not result.fallback


def test_uncertain_board_keeps_full_frame(config: SlideConfig) -> None:
    image = question()
    result = isolate_board(image, config)
    assert result.fallback
    assert np.array_equal(result.image, image)


def test_rectangular_board_detection(config: SlideConfig) -> None:
    image = np.zeros((240, 400, 3), dtype=np.uint8)
    cv2.rectangle(image, (4, 4), (395, 235), (255, 255, 255), 2)
    result = isolate_board(image, config)
    assert not result.fallback
    assert result.image.shape[0] > 220


def test_perspective(config: SlideConfig) -> None:
    image = question()
    corners = np.array([[0, 0], [399, 0], [399, 239], [0, 239]], dtype=np.float32)
    result = perspective(image, corners)
    assert result.shape == (239, 399, 3)
    assert np.mean(result) > 150


@pytest.mark.parametrize(
    "values", [{"left": 0.8, "right": 0.2}, {"top": -1}, {"bottom": float("nan")}]
)
def test_crop_validation(values: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        Crop(**values)


def test_template_is_not_duplicate(config: SlideConfig) -> None:
    assert not compare(question(), question("Question 2: which year?"), config).duplicate


def test_annotation_and_answer_preserved(config: SlideConfig) -> None:
    a = question()
    b = a.copy()
    cv2.line(b, (20, 90), (200, 90), (0, 220, 220), 2)
    assert not compare(a, b, config).duplicate
    assert compare(a, a.copy(), config).duplicate


def test_stationary_foreground_not_certified(config: SlideConfig) -> None:
    image = question()
    cv2.rectangle(image, (200, 80), (350, 239), (60, 100, 160), -1)
    masks = obstruction_masks([image, image, image], config)
    rebuilt = reconstruct([image] * 3, masks, config)
    assert rebuilt.method == "original"
    assert np.array_equal(rebuilt.image, image)


@pytest.mark.parametrize("method", ["masked_pixel_fusion", "temporal_median"])
def test_obstruction_recovery_from_actual_observations(
    config: SlideConfig, method: Literal["masked_pixel_fusion", "temporal_median"]
) -> None:
    clean = question()
    blocked = clean.copy()
    cv2.rectangle(blocked, (200, 80), (300, 220), (0, 0, 180), -1)
    mask = np.zeros(clean.shape[:2], dtype=np.uint8)
    mask[80:221, 200:301] = 255
    result = reconstruct(
        [blocked, clean, clean],
        [mask, np.zeros_like(mask), np.zeros_like(mask)],
        config,
        method=method,
    )
    assert result.method == method
    assert np.array_equal(result.image, clean)
    assert result.unresolved_fraction == 0


def test_reconstruction_rejects_annotation_change(config: SlideConfig) -> None:
    clean = question()
    changed = clean.copy()
    cv2.line(changed, (15, 100), (150, 100), (0, 0, 255), 2)
    masks = [np.zeros(clean.shape[:2], dtype=np.uint8) for _ in range(3)]
    result = reconstruct([clean, changed, changed], masks, config)
    assert result.method == "original"
    assert np.array_equal(result.image, clean)


def test_permanently_hidden_region_not_invented(config: SlideConfig) -> None:
    clean = question()
    mask = np.zeros(clean.shape[:2], dtype=np.uint8)
    mask[80:221, 200:301] = 255
    result = reconstruct([clean] * 3, [mask] * 3, config)
    assert result.method == "original"
    assert result.unresolved_fraction > 0


def test_alignment_uncertainty_falls_back(config: SlideConfig) -> None:
    a = question()
    b = np.roll(a, 20, axis=1)
    masks = [np.zeros(a.shape[:2], dtype=np.uint8)] * 3
    assert reconstruct([a, b, b], masks, config).method == "original"


def test_sampling_boundaries_and_limits(config: SlideConfig) -> None:
    assert sample_timestamps(60, 80, config, 10) == [65, 70, 75]
    assert sample_timestamps(60, 80, config, 1) == [65]
    assert sample_timestamps(60, 64, config, 10) == []
    assert sample_timestamps(60, 80, config, 0) == []


def test_pipeline_manifest_and_source_integrity(tmp_path: Path, config: SlideConfig) -> None:
    a, b = question(), question("Question 2: which year?")
    frames = generation(tmp_path / "frames", [a, a, b])
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in frames.iterdir()}
    result = SlideProcessor().process(frames, tmp_path / "output", video_id=1, config=config)
    assert len(result.slides) == 2 and result.duplicate_count == 1
    assert [d.action for d in result.decisions] == ["retained", "excluded", "retained"]
    assert read_slide_manifest(tmp_path / "output").video_id == 1
    assert hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in frames.iterdir()}
    assert all(s.quality.verified_accuracy is None for s in result.slides)
    data = result.model_dump()
    data["duplicate_count"] = 0
    with pytest.raises(ValidationError):
        SlideManifest.model_validate(data)


def test_cancel_does_not_publish(tmp_path: Path, config: SlideConfig) -> None:
    frames = generation(tmp_path / "frames", [question()])
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ExtractionCancelled):
        SlideProcessor().process(
            frames, tmp_path / "output", video_id=1, config=config, cancel=cancel
        )
    assert not (tmp_path / "output" / "manifest.json").exists()


def test_symlink_image_rejected(tmp_path: Path, config: SlideConfig) -> None:
    image = tmp_path / "image.png"
    cv2.imwrite(str(image), question())
    link = tmp_path / "link.png"
    link.symlink_to(image)
    with pytest.raises(SlideError):
        load_image(link, config)


def test_large_image_rejected_before_decode(tmp_path: Path, config: SlideConfig) -> None:
    path = tmp_path / "image.png"
    cv2.imwrite(str(path), question())
    with pytest.raises(SlideError):
        load_image(path, config.model_copy(update={"max_image_pixels": 10}))


def seed(client: TestClient, tmp_path: Path) -> int:
    from datetime import UTC, datetime

    from app.infrastructure.models import VideoRecord

    with client.app.state.sessions() as session:  # type: ignore[attr-defined]
        record = VideoRecord(
            youtube_video_id="offline1234",
            title="Synthetic lecture",
            video_url="https://example.com",
            published_at=datetime.now(UTC),
            duration_seconds=180,
        )
        session.add(record)
        session.commit()
        video_id = record.id
    service = client.app.state.extraction_service  # type: ignore[attr-defined]
    assert service._settings.frame_dir is not None
    directory = generation(
        service._settings.frame_dir / str(video_id) / ("a" * 32),
        [question(), question(), question("Question 2")],
    )
    service._repo.save(
        video_id,
        status="extracted",
        frame_directory=str(directory),
        manifest_path=str(directory / "manifest.json"),
        frame_count=3,
    )
    return video_id


def wait(client: TestClient, video_id: int) -> dict[str, object]:
    for _ in range(150):
        state: dict[str, object] = client.get(f"/api/v1/videos/{video_id}/slide-processing").json()
        if not state["requested"]:
            return state
        time.sleep(0.02)
    raise AssertionError("Worker did not finish")


def test_api_process_preview_reprocess_delete(migrated_client: TestClient, tmp_path: Path) -> None:
    client = migrated_client
    video_id = seed(client, tmp_path)
    path = f"/api/v1/videos/{video_id}"
    response = client.post(
        path + "/slide-processing",
        json={"configuration": {"adaptive_enabled": False, "min_free_disk_mb": 0}},
    )
    assert response.status_code == 202, response.text
    assert wait(client, video_id)["status"] == "processed"
    listing = client.get(path + "/slides").json()
    assert listing["total"] == 2
    item = listing["items"][0]
    preview = path + "/slides/" + listing["generation"] + "/" + item["processed_image_path"]
    assert client.get(preview).status_code == 200
    assert client.post(path + "/slide-processing", json={}).status_code == 409
    assert client.get(path + "/slides/bad/" + item["processed_image_path"]).status_code == 409
    assert client.get(path + "/slides/" + listing["generation"] + "/unknown.png").status_code == 404
    # A failed replacement must preserve the successful pointer and preview.
    service = client.app.state.slide_service  # type: ignore[attr-defined]
    old = service.processor.process

    def fail(*args: object, **kwargs: object) -> SlideManifest:
        raise SlideError("synthetic failure")

    service.processor.process = fail
    assert client.post(path + "/slide-processing", json={"reprocess": True}).status_code == 202
    assert wait(client, video_id)["status"] == "failed"
    assert client.get(preview).status_code == 200
    service.processor.process = old
    assert client.post(path + "/slide-processing/retry").status_code == 202
    assert wait(client, video_id)["status"] == "processed"
    assert client.delete(path + "/slide-processing").status_code == 200
    assert client.get(path + "/frames").json()["total"] == 3
    assert client.get(path + "/slides").status_code == 409


def test_bulk_validation_and_unknown_video(migrated_client: TestClient) -> None:
    assert migrated_client.get("/api/v1/videos/9999/slide-processing").status_code == 404
    response = migrated_client.post("/api/v1/videos/slides/bulk", json={"video_ids": [9999]})
    assert response.status_code == 202 and len(response.json()["errors"]) == 1
    assert (
        migrated_client.post("/api/v1/videos/slides/bulk", json={"video_ids": []}).status_code
        == 422
    )


def test_moving_foreground_masks(config: SlideConfig) -> None:
    clean = question()
    images = []
    for left in (210, 260, 310):
        image = clean.copy()
        cv2.rectangle(image, (left, 70), (left + 60, 239), (0, 0, 180), -1)
        images.append(image)
    masks = obstruction_masks(images, config)
    assert all(np.count_nonzero(mask) > 0 for mask in masks)


def test_adaptive_real_extractor_bounded(tmp_path: Path, config: SlideConfig) -> None:
    import subprocess

    from app.infrastructure.frame_extractor import FFmpegFrameExtractor

    image = tmp_path / "input.png"
    cv2.imwrite(str(image), question())
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-loop",
            "1",
            "-i",
            str(image),
            "-t",
            "4",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
    )
    extractor = FFmpegFrameExtractor(min_free_disk_mb=0)
    frames = tmp_path / "frames"
    extractor.extract(source, frames, video_id="1", interval=2)
    result = SlideProcessor(extractor).process(
        frames,
        tmp_path / "slides",
        video_id=1,
        config=config.model_copy(
            update={
                "adaptive_enabled": True,
                "additional_interval": 0.5,
                "max_additional_samples": 3,
            }
        ),
        source=source,
    )
    assert len(result.additional_sampled_timestamps) == 3
    for actual, requested in zip(result.additional_sampled_timestamps, [0.5, 1, 1.5], strict=True):
        assert requested <= actual < requested + 0.041
    assert result.input_count == 2
    assert len(result.decisions) == 2


def test_cancellation_conflicts_recovery_and_retry_limit(
    migrated_client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.slides import SlideService

    client = migrated_client
    video_id = seed(client, tmp_path)
    service: SlideService = client.app.state.slide_service  # type: ignore[attr-defined]
    entered = threading.Event()
    original = service.processor.process

    def blocked(*args: object, **kwargs: object) -> SlideManifest:
        from typing import cast

        from app.domain.extraction import CancellationSignal

        signal = cast(CancellationSignal, kwargs["cancel"])
        entered.set()
        for _ in range(100):
            if signal.is_set():
                raise ExtractionCancelled("cancelled")
            time.sleep(0.01)
        raise AssertionError("Cancellation not propagated")

    monkeypatch.setattr(service.processor, "process", blocked)
    path = f"/api/v1/videos/{video_id}"
    assert client.post(path + "/slide-processing", json={}).status_code == 202
    assert entered.wait(1)
    assert client.post(path + "/slide-processing", json={}).status_code == 409
    assert client.delete(path + "/extraction").status_code == 409
    assert client.delete(path + "/download").status_code == 409
    assert client.delete(path + "/slide-processing").status_code == 409
    assert client.post(path + "/slide-processing/cancel").status_code == 200
    for _ in range(100):
        if video_id not in service.events:
            break
        time.sleep(0.01)
    assert service.state(video_id).status == "cancelled"
    assert service.state(video_id).output_directory is None
    monkeypatch.setattr(service.processor, "process", original)
    assert client.post(path + "/slide-processing/retry").status_code == 202
    assert wait(client, video_id)["status"] == "processed"
    # Simulate durable requested intent observed after process interruption.
    service.repository.save(video_id, requested=True, status="processing", retry_count=0)
    service.recover()
    assert wait(client, video_id)["status"] == "processed"
    assert service.state(video_id).retry_count == 1
    service.repository.save(
        video_id,
        requested=True,
        status="processing",
        retry_count=service.settings.slide_retry_attempts,
    )
    service.recover()
    assert service.state(video_id).status == "failed"
    assert not service.state(video_id).requested
    # Cancelled jobs are never automatically recovered.
    service.repository.save(video_id, requested=False, status="cancelled")
    service.recover()
    assert service.state(video_id).status == "cancelled"


def test_shutdown_preserves_intent(migrated_client: TestClient, tmp_path: Path) -> None:
    client = migrated_client
    video_id = seed(client, tmp_path)
    service = client.app.state.slide_service  # type: ignore[attr-defined]
    state = service.repository.claim(video_id, SlideConfig(adaptive_enabled=False))
    service.stopping.set()
    service._run(state, threading.Event())
    assert service.state(video_id).requested
    assert service.state(video_id).status == "pending"
    service.stopping.clear()
    service.recover()
    assert wait(client, video_id)["status"] == "processed"


def test_safe_deletion_refuses_symlink(migrated_client: TestClient, tmp_path: Path) -> None:
    client = migrated_client
    video_id = seed(client, tmp_path)
    service = client.app.state.slide_service  # type: ignore[attr-defined]
    target = tmp_path / "external"
    target.mkdir()
    (target / "keep.txt").write_text("preserve")
    (service.root / str(video_id)).symlink_to(target)
    assert client.delete(f"/api/v1/videos/{video_id}/slide-processing").status_code == 422
    assert (target / "keep.txt").read_text() == "preserve"


def test_transient_processing_retry(
    migrated_client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    client = migrated_client
    video_id = seed(client, tmp_path)
    service = client.app.state.slide_service  # type: ignore[attr-defined]
    original = service.processor.process
    calls = 0

    def once(*args: object, **kwargs: object) -> SlideManifest:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError(errno.EBUSY, "busy")
        return original(*args, **kwargs)  # type: ignore[no-any-return]

    monkeypatch.setattr(service.processor, "process", once)
    assert client.post(f"/api/v1/videos/{video_id}/slide-processing", json={}).status_code == 202
    assert wait(client, video_id)["status"] == "processed"
    assert calls == 2 and service.state(video_id).retry_count == 1


def test_authorized_real_preservation_and_reconstruction() -> None:
    """Opt-in local fixtures; no network or copyrighted screenshots in the repository."""
    import os

    root = os.environ.get("PHASE6_REAL_DATA")
    if not root:
        pytest.skip("Set PHASE6_REAL_DATA to the locally retained authorized evaluation dataset")
    directory = Path(root)
    config = SlideConfig()
    original = load_image(directory / "frames" / "frame_000180000.png", config)
    distinct = load_image(directory / "frames" / "frame_000660000.png", config)
    assert not compare(original, distinct, config).duplicate
    before = load_image(directory / "frames" / "frame_000720000.png", config)
    annotated = load_image(directory / "frames" / "frame_000780000.png", config)
    assert not compare(before, annotated, config).duplicate
    images = [original]
    for timestamp in (185, 190, 195, 200):
        images.append(
            load_image(directory / "samples-180" / f"frame_{timestamp * 1000:09d}.png", config)
        )
    masks = obstruction_masks(images, config)
    result = reconstruct(images, masks, config)
    assert result.method == "masked_pixel_fusion"
    assert 0 < result.unresolved_fraction < float(np.mean(masks[0] > 0))
    # Compare a manually identified recovered portion of option A to a visible source.
    region = np.s_[290:340, 95:180]
    clear = images[3]
    assert np.mean(cv2.absdiff(result.image[region], clear[region])) < np.mean(
        cv2.absdiff(original[region], clear[region])
    )


def test_request_overrides_preserve_server_defaults(
    migrated_client: TestClient, tmp_path: Path
) -> None:
    client = migrated_client
    video_id = seed(client, tmp_path)
    service = client.app.state.slide_service  # type: ignore[attr-defined]
    service.settings.slide_processing = SlideConfig(
        adaptive_enabled=False, max_additional_samples=7
    )
    response = client.post(
        f"/api/v1/videos/{video_id}/slide-processing",
        json={"configuration": {"crop": {"bottom": 0.9}}},
    )
    assert response.status_code == 202
    config = SlideConfig.model_validate_json(response.json()["configuration"])
    assert not config.adaptive_enabled and config.max_additional_samples == 7
    assert config.crop and config.crop.bottom == 0.9
    assert wait(client, video_id)["status"] == "processed"


def test_reconstruction_rejects_invalid_observations(config: SlideConfig) -> None:
    with pytest.raises(SlideError):
        reconstruct([], [], config)
    with pytest.raises(SlideError):
        reconstruct([question()], [np.zeros((2, 2), dtype=np.uint8)], config)


def test_real_quadrilateral_correction(config: SlideConfig) -> None:
    from skimage.metrics import structural_similarity

    image = question()
    source = np.array([[0, 0], [399, 0], [399, 239], [0, 239]], dtype=np.float32)
    target = np.array([[40, 30], [450, 10], [470, 270], [20, 250]], dtype=np.float32)
    distorted = cv2.warpPerspective(image, cv2.getPerspectiveTransform(source, target), (500, 300))
    corrected = perspective(distorted.astype(np.uint8), target)
    resized = cv2.resize(corrected, (400, 240))
    score = structural_similarity(image, resized, channel_axis=2, data_range=255)  # type: ignore[no-untyped-call]
    assert float(score) > 0.75


def test_processing_rejects_input_output_and_source_mismatch(
    tmp_path: Path, config: SlideConfig
) -> None:
    from app.infrastructure.frame_extractor import FFmpegFrameExtractor

    frames = generation(tmp_path / "frames", [question()])
    processor = SlideProcessor(FFmpegFrameExtractor())
    with pytest.raises(SlideError, match="different video"):
        processor.process(frames, tmp_path / "slides", video_id=2, config=config)
    with pytest.raises(SlideError, match="separate"):
        processor.process(frames, frames / "slides", video_id=1, config=config)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"changed media")
    with pytest.raises(SlideError, match="source identity"):
        processor.process(
            frames,
            tmp_path / "slides",
            video_id=1,
            config=config.model_copy(update={"adaptive_enabled": True}),
            source=source,
        )


def test_disk_failure_does_not_publish(
    tmp_path: Path, config: SlideConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil
    from collections import namedtuple

    frames = generation(tmp_path / "frames", [question()])
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(shutil, "disk_usage", lambda _: Usage(100, 100, 0))
    with pytest.raises(SlideError, match="free space"):
        SlideProcessor().process(
            frames,
            tmp_path / "slides",
            video_id=1,
            config=config.model_copy(update={"min_free_disk_mb": 1}),
        )
    assert not (tmp_path / "slides" / "manifest.json").exists()
