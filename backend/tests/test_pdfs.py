"""Comprehensive tests for Phase 7 PDF generation, validation, API, and PDF Library."""

import io
import threading
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.channels import ChannelCreateInput
from app.domain.pdfs import (
    PdfCancelled,
    PdfConfig,
    PdfDocumentMetadata,
    PdfError,
    PdfImageInput,
)
from app.domain.slides import (
    FrameDecision,
    Slide,
    SlideConfig,
    SlideManifest,
    SlideQuality,
)
from app.domain.videos import LivestreamStatus
from app.infrastructure.database import create_database_engine, session_factory
from app.infrastructure.models import ExtractionRecord, SlideProcessingRecord
from app.infrastructure.pdf_generator import (
    PyMuPdfGenerator,
    build_pdf_filename,
    format_timestamp,
    validate_pdf_file,
)
from app.main import create_app
from app.repositories.channels import ChannelRepository
from app.repositories.pdfs import PdfRepository
from app.repositories.videos import VideoRepository


def _make_png(path: Path, width: int, height: int, color: tuple[int, int, int], label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = np.full((height, width, 3), color, dtype=np.uint8)
    cv2.putText(
        img,
        label,
        (24, max(40, height // 2)),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (15, 15, 15),
        2,
        cv2.LINE_AA,
    )
    assert cv2.imwrite(str(path), img)


def _setup_video_with_slides(
    tmp_path: Path,
    *,
    youtube_id: str = "vid_pdf_001",
    title: str = "WBPSC IDO History Class 01",
    channel_name: str = "BSSEI Competitive",
    slide_count: int = 3,
    is_excluded: bool = False,
    include_uncertain: bool = False,
) -> tuple[Settings, int, Path]:
    storage = tmp_path / "storage"
    db_path = storage / "database" / "app.db"
    settings = Settings(
        app_env="test",
        storage_dir=storage,
        temp_dir=storage / "jobs",
        database_path=db_path,
        pdf_dir=storage / "pdfs",
        pdf_min_free_disk_mb=0,
    )
    storage.mkdir(parents=True, exist_ok=True)
    (storage / "database").mkdir(parents=True, exist_ok=True)
    engine = create_database_engine(db_path)
    from app.infrastructure.database import Base

    Base.metadata.create_all(engine)
    sessions = session_factory(engine)
    channels = ChannelRepository(sessions)
    videos = VideoRepository(sessions)

    ch = channels.create(
        ChannelCreateInput(
            name=channel_name,
            channel_url=f"https://www.youtube.com/@{channel_name.replace(' ', '')}",
            youtube_channel_id=None,
            sample_video_url=None,
            search_keyword="IDO",
            is_active=True,
        )
    )
    video, _ = videos.create_or_skip(
        channel_id=ch.id,
        youtube_video_id=youtube_id,
        title=title,
        description="Lecture description",
        video_url=f"https://www.youtube.com/watch?v={youtube_id}",
        thumbnail_url=None,
        duration_seconds=3600,
        published_at=datetime(2026, 11, 20, 10, 0, tzinfo=UTC),
        livestream_status=LivestreamStatus.NONE,
        discovered_at=datetime(2026, 11, 20, 12, 0, tzinfo=UTC),
        is_excluded=is_excluded,
        excluded_keywords=["Math"] if is_excluded else None,
    )

    assert settings.frame_dir is not None
    assert settings.temp_dir is not None
    ext_dir = settings.frame_dir / str(video.id) / "gen_ext_1"
    slide_dir = settings.temp_dir / "slides" / str(video.id) / ("a" * 32)
    ext_dir.mkdir(parents=True, exist_ok=True)
    slide_dir.mkdir(parents=True, exist_ok=True)

    slides: list[Slide] = []
    decisions: list[FrameDecision] = []
    for idx in range(slide_count):
        ts = float(idx * 60)
        frame_name = f"frame_{int(ts * 1000):09d}.png"
        slide_name = f"slide_{idx + 1:05d}.png"
        _make_png(
            ext_dir / frame_name,
            320,
            180,
            (240 - idx * 15, 240, 245),
            f"Q{idx + 1} t={int(ts)}s",
        )
        _make_png(
            slide_dir / slide_name,
            320,
            180,
            (240 - idx * 15, 240, 245),
            f"Slide {idx + 1}",
        )
        uncertain = include_uncertain and idx == slide_count - 1
        slides.append(
            Slide(
                slide_id=f"slide_{idx + 1:05d}",
                source_frame_ids=[frame_name],
                source_timestamps=[ts],
                processed_image_path=slide_name,
                cropped_image_path=frame_name,
                original_image_path=frame_name,
                board_coordinates=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
                reconstruction_method="original",
                quality=SlideQuality(
                    obstruction_fraction=0.25 if uncertain else 0.01,
                    unresolved_fraction=0.10 if uncertain else 0.0,
                    sharpness=100.0,
                    visible_coverage=0.75 if uncertain else 0.99,
                    clarity_score=80.0,
                    crop_reliability="full_frame",
                    grouping_confidence="low" if uncertain else "high",
                ),
                quality_category="uncertain" if uncertain else "clear_original",
                duplicate_group=f"grp_{idx + 1}",
                fallback=False,
                incomplete=uncertain,
                manual_review=uncertain,
            )
        )
        decisions.append(
            FrameDecision(
                frame_id=frame_name,
                timestamp=ts,
                action="retained",
                slide_id=f"slide_{idx + 1:05d}",
                reason="Distinct slide",
            )
        )

    manifest = SlideManifest(
        video_id=video.id,
        extraction_directory=str(ext_dir),
        configuration=SlideConfig(),
        slides=slides,
        decisions=decisions,
        input_count=slide_count,
        duplicate_count=0,
        processing_duration=1.2,
    )
    (slide_dir / "manifest.json").write_text(manifest.model_dump_json())

    with sessions() as session:
        session.add(
            ExtractionRecord(
                video_id=video.id,
                status="extracted",
                requested=False,
                progress=100.0,
                frame_count=slide_count,
                frame_directory=str(ext_dir),
                manifest_path=str(ext_dir / "manifest.json"),
            )
        )
        session.add(
            SlideProcessingRecord(
                video_id=video.id,
                status="processed",
                requested=False,
                progress=100.0,
                input_count=slide_count,
                output_count=slide_count,
                output_directory=str(slide_dir),
            )
        )
        session.commit()

    engine.dispose()
    return settings, video.id, slide_dir


def test_core_pdf_generator_lossless_chronology_metadata_and_footer(tmp_path: Path) -> None:
    img1 = tmp_path / "img1.png"
    img2 = tmp_path / "img2.png"
    img3 = tmp_path / "img3_portrait.png"
    _make_png(img1, 640, 360, (255, 250, 240), "First 00:00")
    _make_png(img2, 640, 360, (240, 255, 240), "Second 01:05")
    # Portrait image must still produce a landscape page without cropping or distortion.
    _make_png(img3, 200, 300, (240, 240, 255), "Portrait")

    out_pdf = tmp_path / "out" / "lecture.pdf"
    gen = PyMuPdfGenerator()
    progress_calls: list[tuple[int, int]] = []
    result = gen.generate(
        [
            PdfImageInput(image_path=img1, timestamp_seconds=0.0),
            PdfImageInput(image_path=img2, timestamp_seconds=65.0),
            PdfImageInput(image_path=img3, timestamp_seconds=125.0),
        ],
        PdfDocumentMetadata(
            title="Indian History MCQ Class",
            channel_name="BSSEI Competitive",
            source_url="https://www.youtube.com/watch?v=abc123",
            youtube_video_id="abc123",
        ),
        out_pdf,
        config=PdfConfig(compression="lossless", min_free_disk_mb=0),
        on_progress=lambda done, total: progress_calls.append((done, total)),
    )

    assert result.page_count == 3
    assert result.file_size_bytes > 0
    assert progress_calls == [(1, 3), (2, 3), (3, 3)]

    with pymupdf.open(str(out_pdf)) as doc:
        assert len(doc) == 3
        assert doc.metadata["title"] == "Indian History MCQ Class"
        assert doc.metadata["author"] == "BSSEI Competitive"
        assert doc.metadata["subject"] == "https://www.youtube.com/watch?v=abc123"

        expected_dims = [(640, 360), (640, 360), (200, 300)]
        expected_ts = ["00:00:00", "00:01:05", "00:02:05"]
        for i, page in enumerate(doc):
            assert page.rect.width > page.rect.height
            text = page.get_text("text")
            assert f"Timestamp: {expected_ts[i]}" in text
            assert f"Page {i + 1} / 3" in text

            imgs = page.get_images(full=True)
            assert len(imgs) == 1
            xref = imgs[0][0]
            extracted = doc.extract_image(xref)
            assert (extracted["width"], extracted["height"]) == expected_dims[i]
            # Image rect must stay above footer area
            rects = page.get_image_rects(xref)
            assert rects[0].y1 <= expected_dims[i][1] + 0.5

        # Verify pixel-exact lossless preservation on page 1
        orig_bgr = cv2.imread(str(img1), cv2.IMREAD_COLOR)
        ext1 = doc.extract_image(doc[0].get_images(full=True)[0][0])
        decoded = cv2.imdecode(np.frombuffer(ext1["image"], dtype=np.uint8), cv2.IMREAD_COLOR)
        assert orig_bgr is not None and decoded is not None
        assert np.array_equal(orig_bgr, decoded)


def test_core_pdf_generator_arbitrary_local_paths_and_bengali_text(tmp_path: Path) -> None:
    # Render Bengali Unicode text onto a PNG using PyMuPDF Story/Page or high-contrast image
    p1 = tmp_path / "local_a.png"
    p2 = tmp_path / "local_b.png"
    _make_png(p1, 800, 450, (255, 255, 255), "MCQ 1: Bengali & English")
    _make_png(p2, 800, 450, (250, 250, 250), "MCQ 2: Option A B C D")

    out = tmp_path / "arbitrary.pdf"
    gen = PyMuPdfGenerator()
    res = gen.generate_from_paths(
        [p1, p2],
        PdfDocumentMetadata(title="Local Collection", channel_name="Local"),
        out,
        config=PdfConfig(compression="lossless", min_free_disk_mb=0),
    )
    assert res.page_count == 2
    assert validate_pdf_file(out, [(800, 450), (800, 450)])


def test_core_pdf_generator_errors_and_cancellation(tmp_path: Path) -> None:
    gen = PyMuPdfGenerator()
    meta = PdfDocumentMetadata(title="Test", channel_name="Channel")

    with pytest.raises(PdfError):
        gen.generate([], meta, tmp_path / "empty.pdf", config=PdfConfig(min_free_disk_mb=0))

    missing = tmp_path / "does_not_exist.png"
    with pytest.raises(PdfError):
        gen.generate(
            [PdfImageInput(image_path=missing, timestamp_seconds=0.0)],
            meta,
            tmp_path / "missing.pdf",
            config=PdfConfig(compression="lossless", min_free_disk_mb=0),
        )
    assert not (tmp_path / "missing.pdf").exists()

    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not-a-valid-png")
    with pytest.raises(PdfError):
        gen.generate(
            [PdfImageInput(image_path=corrupt, timestamp_seconds=0.0)],
            meta,
            tmp_path / "corrupt.pdf",
            config=PdfConfig(compression="lossless", min_free_disk_mb=0),
        )

    valid = tmp_path / "ok.png"
    _make_png(valid, 320, 180, (255, 255, 255), "OK")
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(PdfCancelled):
        gen.generate(
            [PdfImageInput(image_path=valid, timestamp_seconds=0.0)],
            meta,
            tmp_path / "cancelled.pdf",
            config=PdfConfig(compression="lossless", min_free_disk_mb=0),
            cancel=cancel,
        )
    assert not (tmp_path / "cancelled.pdf").exists()


def test_filename_sanitization_and_timestamp_formatting() -> None:
    assert format_timestamp(0) == "00:00:00"
    assert format_timestamp(3665) == "01:01:05"
    name = build_pdf_filename(
        published_at=datetime(2026, 11, 20, 10, 0, tzinfo=UTC),
        channel_name="../BSSEI/Competitive:*?",
        title="WBPSC IDO | চক্রবৃদ্ধি সুদ <Part-1>",
        youtube_video_id="vqYNwaqFPJM",
    )
    assert "/" not in name and "\\" not in name and ".." not in name
    assert name.startswith("2026-11-20_")
    assert name.endswith("_vqYNwaqFPJM.pdf")
    assert "চক্রবৃদ্ধি" in name


def test_api_pdf_lifecycle_library_zip_and_exclusion(tmp_path: Path) -> None:
    settings, video_id, slide_dir = _setup_video_with_slides(
        tmp_path,
        youtube_id="vqYNwaqFPJM",
        title="Authorized Evaluation Lecture",
        channel_name="BSSEI Competitive",
        slide_count=3,
        include_uncertain=True,
    )
    with TestClient(create_app(settings)) as client:
        # 1. Generate PDF
        res = client.post(f"/api/v1/videos/{video_id}/pdf", json={})
        assert res.status_code == 202

        # Poll until generated
        deadline = time.monotonic() + 10.0
        state = None
        while time.monotonic() < deadline:
            r = client.get(f"/api/v1/videos/{video_id}/pdf")
            assert r.status_code == 200
            state = r.json()
            if state["status"] in {"generated", "failed"}:
                break
            time.sleep(0.05)

        assert state is not None
        assert state["status"] == "generated"
        assert state["page_count"] == 3  # includes uncertain/incomplete slide!
        assert state["source_slide_generation"] == slide_dir.name
        assert state["file_size_bytes"] > 0

        # 2. Duplicate generation prevented without regenerate=True
        dup = client.post(f"/api/v1/videos/{video_id}/pdf", json={})
        assert dup.status_code == 409

        # 3. Library listing, search, and metadata
        lib = client.get("/api/v1/pdfs", params={"search": "Evaluation"})
        assert lib.status_code == 200
        lib_data = lib.json()
        assert lib_data["total"] == 1
        assert lib_data["total_pages_sum"] == 3
        assert lib_data["items"][0]["video_title"] == "Authorized Evaluation Lecture"
        assert lib_data["items"][0]["channel_name"] == "BSSEI Competitive"

        meta = client.get(f"/api/v1/pdfs/{video_id}")
        assert meta.status_code == 200
        assert meta.json()["page_count"] == 3

        # 4. Preview & Individual download
        prev = client.get(f"/api/v1/pdfs/{video_id}/preview")
        assert prev.status_code == 200
        assert prev.headers["content-type"] == "application/pdf"
        assert "inline" in prev.headers["content-disposition"]
        assert prev.content[:4] == b"%PDF"

        dl = client.get(f"/api/v1/pdfs/{video_id}/download")
        assert dl.status_code == 200
        assert "attachment" in dl.headers["content-disposition"]
        assert dl.content[:4] == b"%PDF"

        # 5. Bulk ZIP download (including an unavailable ID)
        zip_res = client.post(
            "/api/v1/pdfs/download-zip",
            json={"video_ids": [video_id, 99999]},
        )
        assert zip_res.status_code == 200
        assert zip_res.headers["content-type"] == "application/zip"
        assert zip_res.headers["x-unavailable-count"] == "1"
        with zipfile.ZipFile(io.BytesIO(zip_res.content)) as zf:
            names = zf.namelist()
            assert len(names) == 1
            assert names[0].endswith("_vqYNwaqFPJM.pdf")
            assert zf.read(names[0])[:4] == b"%PDF"

        # Verify no leftover temp ZIP files in pdf_dir
        assert not list(settings.pdf_dir.glob("*.tmp.zip"))  # type: ignore[union-attr]

        # 6. Delete PDF preserves source slides & frames
        del_res = client.delete(f"/api/v1/videos/{video_id}/pdf")
        assert del_res.status_code == 200
        assert del_res.json()["status"] == "pending"
        assert (slide_dir / "manifest.json").exists()
        assert client.get("/api/v1/pdfs").json()["total"] == 0


def test_excluded_video_enforcement_for_pdf(tmp_path: Path) -> None:
    settings, video_id, _ = _setup_video_with_slides(
        tmp_path,
        youtube_id="excl_vid_01",
        title="Math Practice Set",
        is_excluded=True,
    )
    with TestClient(create_app(settings)) as client:
        res = client.post(f"/api/v1/videos/{video_id}/pdf", json={})
        assert res.status_code == 409

        bulk = client.post("/api/v1/pdfs/bulk", json={"video_ids": [video_id]})
        assert bulk.status_code == 202
        assert bulk.json()["started_ids"] == []
        assert len(bulk.json()["errors"]) == 1


def test_failed_regeneration_preserves_previous_pdf_and_startup_recovery(tmp_path: Path) -> None:
    settings, video_id, slide_dir = _setup_video_with_slides(
        tmp_path,
        youtube_id="regen_vid_01",
        title="Regen Test Lecture",
        slide_count=2,
    )
    with TestClient(create_app(settings)) as client:
        assert client.post(f"/api/v1/videos/{video_id}/pdf", json={}).status_code == 202
        for _ in range(100):
            s = client.get(f"/api/v1/videos/{video_id}/pdf").json()
            if s["status"] == "generated":
                break
            time.sleep(0.05)
        original_path = Path(s["pdf_path"])
        original_bytes = original_path.read_bytes()

        # Corrupt a slide image so regeneration fails
        (slide_dir / "slide_00001.png").write_bytes(b"corrupted-png")
        assert (
            client.post(f"/api/v1/videos/{video_id}/pdf", json={"regenerate": True}).status_code
            == 202
        )
        for _ in range(100):
            s2 = client.get(f"/api/v1/videos/{video_id}/pdf").json()
            if s2["status"] == "failed":
                break
            time.sleep(0.05)
        assert s2["status"] == "failed"
        # Previous PDF bytes and metadata must remain intact
        assert original_path.exists()
        assert original_path.read_bytes() == original_bytes
        assert client.get(f"/api/v1/pdfs/{video_id}/download").status_code == 200

    # Restore valid slide image and simulate interrupted recovery on startup
    _make_png(slide_dir / "slide_00001.png", 320, 180, (240, 240, 245), "Slide 1 Restored")
    engine = create_database_engine(settings.database_path)  # type: ignore[arg-type]
    repo = PdfRepository(session_factory(engine))
    repo.save(video_id, status="pending", requested=True, retry_count=0)
    engine.dispose()

    with TestClient(create_app(settings)) as client2:
        for _ in range(100):
            s3 = client2.get(f"/api/v1/videos/{video_id}/pdf").json()
            if s3["status"] == "generated":
                break
            time.sleep(0.05)
        assert s3["status"] == "generated"
        assert s3["retry_count"] == 1
        assert s3["page_count"] == 2


def test_all_compression_modes_preserve_dimensions_and_record_metadata(tmp_path: Path) -> None:
    import numpy as np

    rng = np.random.default_rng(42)
    img1 = tmp_path / "slide1.png"
    img2 = tmp_path / "slide2.png"
    for p, label in ((img1, "Question 1: Bengali & English"), (img2, "Question 2: Answer Tick")):
        base = rng.integers(190, 245, size=(360, 640, 3), dtype=np.uint8)
        cv2.putText(base, label, (30, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (20, 20, 30), 2)
        assert cv2.imwrite(str(p), base)

    generator = PyMuPdfGenerator()
    meta = PdfDocumentMetadata(
        title="Compression Test",
        channel_name="BSSEI Competitive",
        source_url="https://www.youtube.com/watch?v=comp1234",
        youtube_video_id="comp1234",
    )

    from app.domain.pdfs import PdfCompressionMode

    sizes: dict[str, int] = {}
    modes: tuple[PdfCompressionMode, ...] = (
        "lossless",
        "maximum_quality",
        "high_quality",
        "compact",
    )
    for mode in modes:
        out = tmp_path / f"out_{mode}.pdf"
        res = generator.generate_from_paths(
            [img1, img2],
            meta,
            out,
            config=PdfConfig(compression=mode),
        )
        assert res.page_count == 2
        assert res.compression == mode
        sizes[mode] = res.file_size_bytes
        for page in res.pages:
            assert (page.width_px, page.height_px) == (640, 360)

        with pymupdf.open(str(out)) as doc:
            assert f"compression={mode}" in (doc.metadata or {}).get("creator", "")
            extracted = doc.extract_image(doc[0].get_images(full=True)[0][0])
            expected_ext = "png" if mode == "lossless" else "jpeg"
            assert extracted["ext"] == expected_ext

    assert sizes["compact"] <= sizes["high_quality"] <= sizes["maximum_quality"] < sizes["lossless"]


def test_pdf_settings_persistence_and_regeneration_override(tmp_path: Path) -> None:
    import numpy as np

    settings, video_id, slide_dir = _setup_video_with_slides(
        tmp_path,
        youtube_id="set_vid_01",
        title="Settings Persistence Lecture",
        slide_count=2,
    )
    rng = np.random.default_rng(7)
    for idx in (1, 2):
        arr = rng.integers(180, 245, size=(180, 320, 3), dtype=np.uint8)
        cv2.putText(arr, f"Slide {idx}", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 20, 20), 2)
        assert cv2.imwrite(str(slide_dir / f"slide_{idx:05d}.png"), arr)
    with TestClient(create_app(settings)) as client:
        # Default is compact (JPEG 85)
        cfg_res = client.get("/api/v1/settings/pdf")
        assert cfg_res.status_code == 200
        assert cfg_res.json()["compression"] == "compact"
        assert cfg_res.json()["default_compression"] == "compact"

        # Generate initial compact PDF
        assert client.post(f"/api/v1/videos/{video_id}/pdf", json={}).status_code == 202
        for _ in range(100):
            s1 = client.get(f"/api/v1/videos/{video_id}/pdf").json()
            if s1["status"] == "generated":
                break
            time.sleep(0.05)
        assert s1["compression"] == "compact"
        compact_size = s1["file_size_bytes"]
        compact_bytes = Path(s1["pdf_path"]).read_bytes()

        # Change persistent setting to high_quality -> existing PDF must NOT change
        put_res = client.put("/api/v1/settings/pdf", json={"compression": "high_quality"})
        assert put_res.status_code == 200
        assert put_res.json()["compression"] == "high_quality"
        assert Path(s1["pdf_path"]).read_bytes() == compact_bytes

        # Regenerate with explicit override lossless (retained for backward compatibility)
        regen = client.post(
            f"/api/v1/videos/{video_id}/pdf",
            json={"regenerate": True, "configuration": {"compression": "lossless"}},
        )
        assert regen.status_code == 202
        for _ in range(100):
            s2 = client.get(f"/api/v1/videos/{video_id}/pdf").json()
            if s2["status"] == "generated":
                break
            time.sleep(0.05)
        assert s2["compression"] == "lossless"
        assert s2["file_size_bytes"] > compact_size

    # Persistence across restart
    with TestClient(create_app(settings)) as client2:
        cfg_after = client2.get("/api/v1/settings/pdf")
        assert cfg_after.status_code == 200
        assert cfg_after.json()["compression"] == "high_quality"


def test_channel_metadata_preserved_after_deletion_and_unknown_fallback(tmp_path: Path) -> None:
    settings, video_id, _ = _setup_video_with_slides(
        tmp_path,
        youtube_id="chan_del_01",
        title="Channel Preservation Lecture",
        slide_count=1,
    )
    engine = create_database_engine(settings.database_path)  # type: ignore[arg-type]
    sessions = session_factory(engine)
    videos_repo = VideoRepository(sessions)
    # Create an unlinked video with no channel metadata to test unknown-channel fallback
    unlinked, _ = videos_repo.create_or_skip(
        channel_id=None,
        youtube_video_id="unlinked_01",
        title="Orphan Lecture",
        description="",
        video_url="https://www.youtube.com/watch?v=unlinked_01",
        thumbnail_url=None,
        duration_seconds=1500,
        published_at=datetime(2026, 11, 27, 4, 0, tzinfo=UTC),
        livestream_status=LivestreamStatus.NONE,
        discovered_at=datetime(2026, 11, 27, 5, 0, tzinfo=UTC),
    )
    engine.dispose()

    with TestClient(create_app(settings)) as client:
        # Generate PDF while channel exists
        assert client.post(f"/api/v1/videos/{video_id}/pdf", json={}).status_code == 202
        for _ in range(100):
            st = client.get(f"/api/v1/videos/{video_id}/pdf").json()
            if st["status"] == "generated":
                break
            time.sleep(0.05)

        # Delete the channel via API
        vid_row = client.get("/api/v1/videos").json()["items"]
        linked_vid = next(v for v in vid_row if v["id"] == video_id)
        ch_id = linked_vid["channel_id"]
        assert ch_id is not None
        assert client.delete(f"/api/v1/channels/{ch_id}").status_code == 204

        # Video history and PDF Library must preserve "BSSEI Competitive" (never "Deleted channel")
        lib = client.get("/api/v1/pdfs").json()
        assert lib["total"] == 1
        assert lib["items"][0]["channel_name"] == "BSSEI Competitive"
        assert "BSSEI Competitive" in lib["items"][0]["pdf_filename"]

        # Regenerate PDF after channel deletion -> still uses preserved "BSSEI Competitive"
        assert (
            client.post(f"/api/v1/videos/{video_id}/pdf", json={"regenerate": True}).status_code
            == 202
        )
        for _ in range(100):
            st2 = client.get(f"/api/v1/videos/{video_id}/pdf").json()
            if st2["status"] == "generated":
                break
            time.sleep(0.05)
        assert "BSSEI Competitive" in st2["pdf_filename"]

    # Unknown-channel fallback for unlinked video with NULL channel_name
    assert unlinked.channel_name is None
    fname = build_pdf_filename(
        published_at=unlinked.published_at,
        channel_name=unlinked.channel_name or "Unknown Channel",
        title=unlinked.title,
        youtube_video_id=unlinked.youtube_video_id,
    )
    assert "Unknown Channel" in fname
    assert "Deleted channel" not in fname


def test_alembic_backfill_preserves_linked_and_leaves_unlinked_null(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "backfill.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))

    command.upgrade(alembic_cfg, "e5f6a7b8c9d0")
    now_iso = "2026-11-27T04:00:00+00:00"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO channels
                (id, name, channel_url, youtube_channel_id, search_keyword,
                 is_active, created_at, updated_at)
            VALUES (1, 'TWS Academy', 'https://www.youtube.com/channel/UCxLjute2FI5blJvh0dSIstg',
                    'UCxLjute2FI5blJvh0dSIstg', 'IDO', 1, ?, ?)
            """,
            (now_iso, now_iso),
        )
        conn.execute(
            """
            INSERT INTO videos
                (id, channel_id, youtube_video_id, title, description, video_url,
                 duration_seconds, published_at, livestream_status, discovered_at,
                 processing_status, download_status, download_progress, downloaded_bytes,
                 download_requested, download_retry_count, is_excluded, created_at, updated_at)
            VALUES
                (1, 1, 'tws_vid_01', 'Linked Video', '', 'https://youtube.com/watch?v=tws_vid_01',
                 1500, ?, 'none', ?, 'pending', 'pending', 0.0, 0, 0, 0, 0, ?, ?),
                (2, NULL, 'orphan_01', 'Orphan Video', '', 'https://youtube.com/watch?v=orphan_01',
                 1500, ?, 'none', ?, 'pending', 'pending', 0.0, 0, 0, 0, 0, ?, ?)
            """,
            (now_iso, now_iso, now_iso, now_iso, now_iso, now_iso, now_iso, now_iso),
        )
        conn.commit()

    command.upgrade(alembic_cfg, "head")

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, channel_name, youtube_channel_id FROM videos ORDER BY id"
        ).fetchall()
    assert rows[0] == (1, "TWS Academy", "UCxLjute2FI5blJvh0dSIstg")
    assert rows[1] == (2, None, None)


def test_alembic_updates_persisted_lossless_setting_to_compact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import sqlite3

    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "settings_mig.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))

    command.upgrade(alembic_cfg, "f6a7b8c9d0e1")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value_json, updated_at)
            VALUES (
                'pdf_generation_settings',
                '{"compression": "lossless"}',
                '2026-11-27T04:00:00+00:00'
            )
            """
        )
        conn.commit()

    command.upgrade(alembic_cfg, "head")

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT value_json FROM app_settings WHERE key = 'pdf_generation_settings'"
        ).fetchone()
    assert row is not None
    assert json.loads(row[0])["compression"] == "compact"
