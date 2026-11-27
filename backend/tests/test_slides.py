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
    assert sample_timestamps(60, 80, config, 10) == [65.0, 70.0, 75.0]
    assert sample_timestamps(60, 80, config, 1) == [70.0]
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

    base = question()
    obstructed = base.copy()
    # Add a peach/skin-toned foreground block touching the lower frame to trigger adaptive sampling.
    cv2.rectangle(obstructed, (40, 120), (140, 239), (140, 165, 210), -1)
    image = tmp_path / "input.png"
    cv2.imwrite(str(image), obstructed)
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
    for actual, requested in zip(
        result.additional_sampled_timestamps, [2.5, 3.0, 3.5], strict=True
    ):
        assert requested - 0.5 <= actual <= requested + 0.5
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


def test_authorized_real_preservation_and_reconstruction(tmp_path: Path) -> None:
    """Full-frame no-crop preservation, reconstruction, and JPEG 85 readability check."""
    import os

    root = os.environ.get("PHASE6_REAL_DATA")
    config = SlideConfig()
    if root and Path(root).is_dir():
        directory = Path(root)
        original = load_image(directory / "frames" / "frame_000180000.png", config)
        distinct = load_image(directory / "frames" / "frame_000660000.png", config)
        before = load_image(directory / "frames" / "frame_000720000.png", config)
        annotated = load_image(directory / "frames" / "frame_000780000.png", config)
        images = [original]
        for timestamp in (185, 190, 195, 200):
            images.append(
                load_image(directory / "samples-180" / f"frame_{timestamp * 1000:09d}.png", config)
            )
    else:
        # Representative 1280x720 full-frame lecture fixture compatible with no-crop policy.
        base = np.full((720, 1280, 3), 245, dtype=np.uint8)
        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(base, "Q1. Full-Frame Lecture Slide", (80, 140), font, 1.4, (20, 20, 20), 3)
        cv2.putText(base, "Option A: 42", (100, 315), font, 1.1, (20, 20, 20), 2)
        cv2.putText(base, "Option B: 84", (100, 390), font, 1.1, (20, 20, 20), 2)

        distinct = np.full((720, 1280, 3), 245, dtype=np.uint8)
        cv2.putText(distinct, "Q2. Different Slide Content", (80, 140), font, 1.4, (20, 20, 20), 3)
        cv2.rectangle(distinct, (150, 240), (950, 560), (30, 60, 180), 4)

        before = base.copy()
        annotated = base.copy()
        cv2.circle(annotated, (260, 310), 45, (0, 0, 220), 4)

        # Simulate teacher moving across Option A in primary frame and clearing in samples.
        original = base.copy()
        cv2.rectangle(original, (90, 270), (240, 420), (45, 45, 55), -1)
        s1 = base.copy()
        cv2.rectangle(s1, (350, 270), (500, 420), (45, 45, 55), -1)
        s2 = base.copy()
        cv2.rectangle(s2, (620, 270), (770, 420), (45, 45, 55), -1)
        s3 = base.copy()
        s4 = base.copy()
        images = [original, s1, s2, s3, s4]

    assert not compare(original, distinct, config).duplicate
    assert not compare(before, annotated, config).duplicate
    masks = obstruction_masks(images, config)
    result = reconstruct(images, masks, config)
    assert result.method == "masked_pixel_fusion"
    assert 0.0 <= result.unresolved_fraction < float(np.mean(masks[0] > 0))
    region = np.s_[290:340, 95:180]
    clear = images[3]
    assert np.mean(cv2.absdiff(result.image[region], clear[region])) < np.mean(
        cv2.absdiff(original[region], clear[region])
    )

    # Verify JPEG 85 (compact) PDF generation preserves 1280x720 full-frame readability.
    import pymupdf

    from app.domain.pdfs import PdfConfig, PdfDocumentMetadata, PdfImageInput
    from app.infrastructure.pdf_generator import PyMuPdfGenerator

    slide_path = tmp_path / "full_frame_slide.png"
    cv2.imwrite(str(slide_path), result.image)
    pdf_out = tmp_path / "full_frame_compact.pdf"
    gen = PyMuPdfGenerator()
    pdf_res = gen.generate(
        images=[PdfImageInput(image_path=slide_path, timestamp_seconds=180.0)],
        metadata=PdfDocumentMetadata(title="Full Frame Test"),
        output_path=pdf_out,
        config=PdfConfig(compression="compact"),
    )
    assert pdf_res.compression == "compact"
    assert pdf_res.page_count == 1
    with pymupdf.open(str(pdf_out)) as doc:
        extracted = doc.extract_image(doc[0].get_images(full=True)[0][0])
        assert extracted["width"] == 1280 and extracted["height"] == 720


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
        json={"configuration": {"crop": {"bottom": 0.9}, "max_fusion_frames": 7}},
    )
    assert response.status_code == 202
    config = SlideConfig.model_validate_json(response.json()["configuration"])
    assert not config.adaptive_enabled and config.max_additional_samples == 7
    assert config.max_fusion_frames == 7
    assert config.crop is None  # Full-frame policy ignores crop overrides
    assert wait(client, video_id)["status"] == "processed"


def test_full_frame_ignores_saved_channel_crop_profile(
    migrated_client: TestClient, tmp_path: Path
) -> None:
    client = migrated_client
    ch_resp = client.post(
        "/api/v1/channels",
        json={
            "name": "Crop Channel",
            "channel_url": "https://www.youtube.com/@cropchannel",
            "search_keyword": "IDO",
        },
    )
    assert ch_resp.status_code == 201
    channel_id = ch_resp.json()["id"]
    video_id = seed(client, tmp_path)
    # Attach video to channel and seed a saved channel crop profile
    sessions = client.app.state.sessions  # type: ignore[attr-defined]
    from app.infrastructure.models import VideoRecord

    with sessions() as session:
        rec = session.get(VideoRecord, video_id)
        assert rec is not None
        rec.channel_id = channel_id
        session.commit()

    put_resp = client.put(
        f"/api/v1/channels/{channel_id}/board-profile",
        json={"crop": {"left": 0.1, "top": 0.1, "right": 0.9, "bottom": 0.85}},
    )
    assert put_resp.status_code == 200

    response = client.post(f"/api/v1/videos/{video_id}/slide-processing", json={})
    assert response.status_code == 202
    state = wait(client, video_id)
    assert state["status"] == "processed"
    config = SlideConfig.model_validate_json(str(state["configuration"]))
    assert config.profile_crop is None
    assert config.crop is None

    slides = client.get(f"/api/v1/videos/{video_id}/slides").json()
    assert slides["items"]
    first = slides["items"][0]
    assert first["fallback"] is False
    assert first["quality"]["crop_reliability"] == "full_frame"
    assert first["board_coordinates"] == [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    assert not any("Board boundary" in w for w in first["warnings"])


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


def test_channel_board_profile_persistence_and_fallback(
    migrated_client: TestClient, tmp_path: Path, config: SlideConfig
) -> None:
    client = migrated_client
    ch_resp = client.post(
        "/api/v1/channels",
        json={"name": "Board Channel", "channel_url": "https://www.youtube.com/@boardch"},
    )
    assert ch_resp.status_code == 201, ch_resp.text
    channel_id = ch_resp.json()["id"]

    # Initially no profile
    assert client.get(f"/api/v1/channels/{channel_id}/board-profile").json() is None

    # Save profile
    put_resp = client.put(
        f"/api/v1/channels/{channel_id}/board-profile",
        json={
            "crop": {"left": 0.0, "top": 0.0, "right": 1.0, "bottom": 0.85},
            "reference_width": 400,
            "reference_height": 240,
        },
    )
    assert put_resp.status_code == 200, put_resp.text
    assert put_resp.json()["crop"]["bottom"] == pytest.approx(0.85)

    # Validated profile applies cleanly to matching aspect ratio
    img = question()
    board_ok = isolate_board(
        img,
        config.model_copy(
            update={
                "profile_crop": Crop(left=0.0, top=0.0, right=1.0, bottom=0.85),
                "profile_reference_aspect": 400 / 240,
            }
        ),
    )
    assert board_ok.reliability == "profile_validated"
    assert not board_ok.fallback
    assert board_ok.image.shape[0] == round(240 * 0.85)

    # Aspect ratio mismatch falls back safely to full frame
    board_bad = isolate_board(
        img,
        config.model_copy(
            update={
                "profile_crop": Crop(left=0.0, top=0.0, right=1.0, bottom=0.85),
                "profile_reference_aspect": 0.75,
            }
        ),
    )
    assert board_bad.reliability == "full_frame_fallback"
    assert board_bad.fallback
    assert board_bad.image.shape == img.shape

    # Delete profile
    del_resp = client.delete(f"/api/v1/channels/{channel_id}/board-profile")
    assert del_resp.status_code == 204
    assert client.get(f"/api/v1/channels/{channel_id}/board-profile").json() is None


def test_teacher_movement_grouped_and_annotations_preserved(
    tmp_path: Path, config: SlideConfig
) -> None:
    clean = question()
    teacher_left = clean.copy()
    cv2.rectangle(teacher_left, (15, 110), (75, 239), (30, 40, 60), -1)
    teacher_right = clean.copy()
    cv2.rectangle(teacher_right, (300, 110), (370, 239), (30, 40, 60), -1)
    annotated = clean.copy()
    cv2.line(annotated, (20, 85), (200, 85), (0, 240, 240), 3)

    frames = generation(tmp_path / "frames", [teacher_left, clean, teacher_right, annotated])
    result = SlideProcessor().process(
        frames,
        tmp_path / "slides",
        video_id=1,
        config=config.model_copy(update={"crop": Crop(left=0, top=0, right=1, bottom=1)}),
    )
    assert len(result.slides) == 2
    assert result.duplicate_count == 2
    first = result.slides[0]
    assert first.quality_category == "clear_original"
    assert first.manual_review is False
    assert first.original_image_path == "frame_000060000.png"
    assert result.slides[1].source_timestamps == [180.0]


def test_best_frame_selection_prefers_clear_over_sharp_obstructed(config: SlideConfig) -> None:
    from app.services.imaging.reconstruction import select_best_or_reconstruct

    clean = question()
    # Slightly soften clean image
    soft_clean = cv2.GaussianBlur(clean, (3, 3), 0.5).astype(np.uint8)
    obstructed = clean.copy()
    # Sharp high-frequency pattern inside obstructed teacher region
    for y in range(100, 235, 4):
        cv2.line(obstructed, (200, y), (350, y), (255, 255, 255), 1)
    mask_obs = np.zeros(clean.shape[:2], dtype=np.uint8)
    mask_obs[100:235, 200:350] = 255
    mask_clean = np.zeros(clean.shape[:2], dtype=np.uint8)

    sel = select_best_or_reconstruct(
        [obstructed, soft_clean],
        [mask_obs, mask_clean],
        config,
        is_adaptive=[False, True],
    )
    assert sel.chosen_index == 1
    assert sel.method == "original"
    assert sel.quality_category == "improved_original"


def test_adaptive_budget_distributed_across_video(tmp_path: Path, config: SlideConfig) -> None:
    from app.domain.extraction import FrameMetadata

    class FakeExtractor:
        def extract(
            self,
            source: Path,
            output: Path,
            *,
            video_id: str,
            timestamps: list[float] | None = None,
            **kwargs: object,
        ) -> ExtractionResult:
            output.mkdir(parents=True, exist_ok=True)
            assert timestamps is not None
            frames = []
            for t in timestamps:
                name = f"frame_{int(t * 1000):09d}.png"
                cv2.imwrite(str(output / name), question(f"Q at {t}"))
                frames.append(
                    FrameMetadata(
                        filename=name,
                        requested_timestamp=t,
                        actual_timestamp=t,
                        width=400,
                        height=240,
                    )
                )
            return ExtractionResult(
                video_id=video_id,
                source_path=str(source),
                source_size_bytes=source.stat().st_size,
                source_mtime_ns=source.stat().st_mtime_ns,
                video_duration=240.0,
                interval_seconds=60.0,
                start_timestamp=0.0,
                end_timestamp=240.0,
                frames=frames,
                frame_count=len(frames),
                processing_duration=0.0,
            )

    source = tmp_path / "src.mp4"
    source.write_bytes(b"video")
    imgs = []
    titles = [
        "1: Geography of Bengal",
        "2: History of Jute Mills",
        "3: Industrial Policy 1952",
        "4: Tea Gardens of Darjeeling",
    ]
    for title in titles:
        im = question(title)
        cv2.rectangle(im, (40, 120), (140, 239), (140, 165, 210), -1)
        imgs.append(im)
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    fmeta = []
    for i, im in enumerate(imgs):
        name = f"frame_{i * 60000:09d}.png"
        cv2.imwrite(str(frames_dir / name), im)
        fmeta.append(
            FrameMetadata(
                filename=name,
                requested_timestamp=i * 60,
                actual_timestamp=i * 60,
                width=400,
                height=240,
            )
        )
    (frames_dir / "manifest.json").write_text(
        ExtractionResult(
            video_id="1",
            source_path=str(source.resolve()),
            source_size_bytes=source.stat().st_size,
            source_mtime_ns=source.stat().st_mtime_ns,
            video_duration=240.0,
            interval_seconds=60.0,
            start_timestamp=0.0,
            end_timestamp=240.0,
            frames=fmeta,
            frame_count=4,
            processing_duration=0.0,
        ).model_dump_json()
    )

    result = SlideProcessor(FakeExtractor()).process(
        frames_dir,
        tmp_path / "slides",
        video_id=1,
        config=config.model_copy(
            update={
                "adaptive_enabled": True,
                "adaptive_scale_with_duration": False,
                "max_additional_samples": 6,
                "max_samples_per_segment": 1,
                "additional_interval": 10.0,
            }
        ),
        source=source,
    )
    # Samples must not all be consumed in segment 0; later segments (>120s) receive samples too.
    assert any(t >= 120.0 for t in result.additional_sampled_timestamps)


def test_storage_optimization_skips_redundant_copies(tmp_path: Path, config: SlideConfig) -> None:
    frames = generation(tmp_path / "frames", [question()])
    out = tmp_path / "slides"
    result = SlideProcessor().process(
        frames,
        out,
        video_id=1,
        config=config.model_copy(update={"save_diagnostics": False}),
    )
    slide = result.slides[0]
    assert slide.original_image_path == "frame_000000000.png"
    assert slide.cropped_image_path == "frame_000000000.png"
    assert slide.processed_image_path == "frame_000000000.png"
    assert slide.obstruction_mask_path is None
    pngs = list(out.glob("*.png"))
    assert pngs == []


def test_delete_extracted_frames_blocked_when_slides_exist(
    migrated_client: TestClient, tmp_path: Path
) -> None:
    client = migrated_client
    video_id = seed(client, tmp_path)
    assert client.post(f"/api/v1/videos/{video_id}/slide-processing", json={}).status_code == 202
    state = wait(client, video_id)
    assert state["status"] == "processed"
    # Deleting extracted frames while published slides reference them must fail with 409.
    delete_frames = client.delete(f"/api/v1/videos/{video_id}/extraction")
    assert delete_frames.status_code == 409
    # After deleting slides, deleting extracted frames succeeds.
    assert client.delete(f"/api/v1/videos/{video_id}/slide-processing").status_code == 200
    assert client.delete(f"/api/v1/videos/{video_id}/extraction").status_code == 200


def test_transition_scan_discovers_inter_primary_slide(tmp_path: Path, config: SlideConfig) -> None:
    import subprocess

    from app.infrastructure.frame_extractor import FFmpegFrameExtractor

    q1 = question("Question 1: Capital of West Bengal?")
    q_mid = np.full((240, 400, 3), 240, dtype=np.uint8)
    cv2.rectangle(q_mid, (30, 30), (370, 210), (30, 45, 90), -1)
    cv2.putText(q_mid, "MID SLIDE", (95, 130), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 3)
    q3 = question("Question 3: Industrial Policy?")
    # Build a 90s synthetic video: 0-30s q1, 30-60s q_mid, 60-90s q3.
    # Primary 60s extraction only captures 0s (q1) and 60s (q3); q_mid at 30s is missed!
    p1, p2, p3 = tmp_path / "p1.png", tmp_path / "p2.png", tmp_path / "p3.png"
    cv2.imwrite(str(p1), q1)
    cv2.imwrite(str(p2), q_mid)
    cv2.imwrite(str(p3), q3)
    concat_file = tmp_path / "concat.txt"
    concat_file.write_text(
        f"file '{p1}'\nduration 25\n"
        f"file '{p2}'\nduration 20\n"
        f"file '{p3}'\nduration 25\n"
        f"file '{p3}'\n"
    )
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-vf",
            "fps=1",
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
    extractor.extract(source, frames, video_id="1", interval=60.0)
    out = tmp_path / "slides"
    result = SlideProcessor(extractor).process(
        frames,
        out,
        video_id=1,
        config=config.model_copy(
            update={
                "adaptive_enabled": False,
                "transition_scan_enabled": True,
                "transition_scan_max_probes": 4,
            }
        ),
        source=source,
    )
    # 2 primaries (0s, 60s) + 1 transition-discovered slide (~30s) = 3 chronological slides.
    assert result.input_count == 2
    assert len(result.slides) == 3
    assert any("Discovered via inter-primary transition scan." in s.warnings for s in result.slides)
    timestamps = [s.source_timestamps[0] for s in result.slides]
    assert timestamps == sorted(timestamps)
    assert 25.0 <= timestamps[1] <= 40.0
    assert read_slide_manifest(out).video_id == 1
