"""Independent, lossless PyMuPDF image-to-PDF generator and validator."""

import re
import shutil
import time
import unicodedata
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pymupdf

from app.domain.extraction import CancellationSignal
from app.domain.pdfs import (
    COMPRESSION_JPEG_QUALITY,
    PdfCancelled,
    PdfConfig,
    PdfDocumentMetadata,
    PdfError,
    PdfGenerationResult,
    PdfImageInput,
    PdfPageValidation,
)

_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE_RE = re.compile(r"\s+")


def format_timestamp(seconds: float) -> str:
    """Format non-negative seconds as HH:MM:SS."""
    total = max(0, int(seconds))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def sanitize_filename_part(value: str, *, max_length: int, fallback: str) -> str:
    """Sanitize a filename segment while preserving readable Unicode characters."""
    normalized = unicodedata.normalize("NFC", value).strip()
    cleaned = _UNSAFE_FILENAME_RE.sub(" ", normalized)
    cleaned = cleaned.replace("..", " ")
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip(" ._-")
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(" ._-")
    return cleaned or fallback


def build_pdf_filename(
    *,
    published_at: datetime | None,
    channel_name: str,
    title: str,
    youtube_video_id: str | None,
) -> str:
    """Build a readable, path-safe PDF filename containing date, channel, title, and video ID."""
    date_part = (
        published_at.astimezone(UTC).strftime("%Y-%m-%d")
        if published_at is not None
        else datetime.now(UTC).strftime("%Y-%m-%d")
    )
    channel_part = sanitize_filename_part(channel_name, max_length=40, fallback="Channel")
    title_part = sanitize_filename_part(title, max_length=90, fallback="Lecture")
    id_part = (
        sanitize_filename_part(youtube_video_id, max_length=24, fallback="local")
        if youtube_video_id
        else "local"
    )
    return f"{date_part}_{channel_part}_{title_part}_{id_part}.pdf"


def validate_pdf_file(
    pdf_path: Path,
    expected_dimensions: Sequence[tuple[int, int]],
    *,
    require_landscape: bool = True,
) -> list[PdfPageValidation]:
    """Validate PDF readability, page count, orientation, and embedded image dimensions."""
    if pdf_path.is_symlink() or not pdf_path.is_file():
        raise PdfError("Generated PDF file is missing or unsafe.")
    file_size = pdf_path.stat().st_size
    if file_size <= 0:
        raise PdfError("Generated PDF file is empty.")

    validations: list[PdfPageValidation] = []
    try:
        with pymupdf.open(str(pdf_path)) as doc:
            if len(doc) != len(expected_dimensions):
                raise PdfError(
                    f"PDF page count mismatch: expected {len(expected_dimensions)}, got {len(doc)}."
                )
            for idx, (exp_w, exp_h) in enumerate(expected_dimensions):
                page = doc[idx]
                rect = page.rect
                if require_landscape and rect.width <= rect.height:
                    raise PdfError(f"Page {idx + 1} is not landscape ({rect.width}x{rect.height}).")
                images = page.get_images(full=True)
                if len(images) != 1:
                    raise PdfError(
                        f"Page {idx + 1} expected 1 embedded image, found {len(images)}."
                    )
                xref = images[0][0]
                extracted = doc.extract_image(xref)
                if not extracted:
                    raise PdfError(f"Page {idx + 1} embedded image could not be extracted.")
                actual_w = int(extracted["width"])
                actual_h = int(extracted["height"])
                if actual_w != exp_w or actual_h != exp_h:
                    raise PdfError(
                        f"Page {idx + 1} image dimensions mismatch: "
                        f"expected {exp_w}x{exp_h}, got {actual_w}x{actual_h}."
                    )
                validations.append(
                    PdfPageValidation(
                        page_number=idx + 1,
                        width_px=actual_w,
                        height_px=actual_h,
                        page_width_pt=float(rect.width),
                        page_height_pt=float(rect.height),
                    )
                )
    except PdfError:
        raise
    except Exception as exc:
        raise PdfError(f"PDF validation failed: {exc}") from exc

    return validations


class PyMuPdfGenerator:
    """Lossless image-to-PDF generator backed by PyMuPDF."""

    def generate(
        self,
        images: Sequence[PdfImageInput],
        metadata: PdfDocumentMetadata,
        output_path: Path,
        *,
        config: PdfConfig | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        cancel: CancellationSignal | None = None,
    ) -> PdfGenerationResult:
        """Generate a validated, lossless PDF from ordered images and publish atomically."""
        if not images:
            raise PdfError("At least one image is required to generate a PDF.")
        cfg = config if config is not None else PdfConfig()
        if output_path.is_symlink():
            raise PdfError("Refusing to write PDF to a symlink destination.")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        if cfg.min_free_disk_mb > 0:
            free_bytes = shutil.disk_usage(output_path.parent).free
            if free_bytes < cfg.min_free_disk_mb * 1024 * 1024:
                raise PdfError("Insufficient disk space for PDF generation.")

        started = time.monotonic()
        tmp_path = output_path.parent / f".{output_path.stem}.{uuid4().hex}.tmp.pdf"
        expected_dims: list[tuple[int, int]] = []
        total = len(images)

        try:
            with pymupdf.open() as doc:
                doc.set_metadata(
                    {
                        "title": metadata.title,
                        "author": metadata.channel_name,
                        "subject": metadata.source_url,
                        "keywords": metadata.youtube_video_id or "",
                        "creator": f"ytLecture2slide (compression={cfg.compression})",
                    }
                )
                quality = COMPRESSION_JPEG_QUALITY[cfg.compression]
                footer_h = (
                    float(cfg.footer_height_pt)
                    if (cfg.include_page_numbers or cfg.include_timestamps)
                    else 0.0
                )

                for idx, item in enumerate(images):
                    if cancel is not None and cancel.is_set():
                        raise PdfCancelled("PDF generation cancelled.")

                    img_path = item.image_path
                    if img_path.is_symlink() or not img_path.is_file():
                        raise PdfError(f"Input image missing or unsafe: {img_path.name}")

                    try:
                        pix = pymupdf.Pixmap(str(img_path))
                        img_w_px = int(pix.width)
                        img_h_px = int(pix.height)
                    except Exception as exc:
                        raise PdfError(
                            f"Corrupted or unreadable image {img_path.name}: {exc}"
                        ) from exc

                    if img_w_px <= 0 or img_h_px <= 0:
                        raise PdfError(f"Invalid image dimensions for {img_path.name}.")

                    expected_dims.append((img_w_px, img_h_px))
                    img_w = float(img_w_px)
                    img_h = float(img_h_px)
                    page_h = img_h + footer_h
                    if cfg.orientation == "landscape" and img_w <= page_h:
                        page_w = page_h + 1.0
                        x_offset = (page_w - img_w) / 2.0
                    else:
                        page_w = img_w
                        x_offset = 0.0

                    page = doc.new_page(width=page_w, height=page_h)
                    image_rect = pymupdf.Rect(x_offset, 0.0, x_offset + img_w, img_h)
                    if quality is None:
                        page.insert_image(image_rect, filename=str(img_path), keep_proportion=True)
                    else:
                        rgb_pix = (
                            pymupdf.Pixmap(pymupdf.csRGB, pix)
                            if pix.alpha or pix.n - pix.alpha > 3
                            else pix
                        )
                        jpeg_bytes = rgb_pix.tobytes("jpeg", jpg_quality=quality)
                        page.insert_image(image_rect, stream=jpeg_bytes, keep_proportion=True)

                    if footer_h > 0.0:
                        self._draw_footer(
                            page=page,
                            page_width=page_w,
                            image_height=img_h,
                            footer_height=footer_h,
                            page_number=idx + 1,
                            total_pages=total,
                            timestamp_seconds=item.timestamp_seconds,
                            include_page_numbers=cfg.include_page_numbers,
                            include_timestamps=cfg.include_timestamps,
                        )

                    if on_progress is not None:
                        on_progress(idx + 1, total)

                if cancel is not None and cancel.is_set():
                    raise PdfCancelled("PDF generation cancelled.")

                doc.save(str(tmp_path), deflate=True, garbage=3)

            if cancel is not None and cancel.is_set():
                raise PdfCancelled("PDF generation cancelled.")

            pages = validate_pdf_file(
                tmp_path,
                expected_dims,
                require_landscape=(cfg.orientation == "landscape"),
            )
            file_size = tmp_path.stat().st_size
            tmp_path.replace(output_path)
            duration = max(0.0, time.monotonic() - started)
            return PdfGenerationResult(
                output_path=output_path,
                page_count=len(pages),
                file_size_bytes=file_size,
                duration_seconds=duration,
                compression=cfg.compression,
                pages=pages,
            )
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    def generate_from_paths(
        self,
        image_paths: Sequence[Path],
        metadata: PdfDocumentMetadata,
        output_path: Path,
        *,
        timestamps_seconds: Sequence[float] | None = None,
        config: PdfConfig | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        cancel: CancellationSignal | None = None,
    ) -> PdfGenerationResult:
        """Generate a PDF from an arbitrary local collection of image paths."""
        if timestamps_seconds is not None and len(timestamps_seconds) != len(image_paths):
            raise PdfError("timestamps_seconds length must match image_paths length.")
        inputs = [
            PdfImageInput(
                image_path=path,
                timestamp_seconds=timestamps_seconds[i]
                if timestamps_seconds is not None
                else float(i * 60),
            )
            for i, path in enumerate(image_paths)
        ]
        return self.generate(
            inputs,
            metadata,
            output_path,
            config=config,
            on_progress=on_progress,
            cancel=cancel,
        )

    @staticmethod
    def _draw_footer(
        *,
        page: pymupdf.Page,
        page_width: float,
        image_height: float,
        footer_height: float,
        page_number: int,
        total_pages: int,
        timestamp_seconds: float,
        include_page_numbers: bool,
        include_timestamps: bool,
    ) -> None:
        """Render timestamp and page number in a clean strip outside the screenshot area."""
        page.draw_rect(
            pymupdf.Rect(0.0, image_height, page_width, image_height + footer_height),
            color=None,
            fill=(0.97, 0.97, 0.98),
        )
        page.draw_line(
            pymupdf.Point(0.0, image_height),
            pymupdf.Point(page_width, image_height),
            color=(0.85, 0.85, 0.88),
            width=0.75,
        )
        font_size = max(10.0, min(14.0, footer_height * 0.48))
        baseline_y = image_height + (footer_height + font_size * 0.72) / 2.0
        pad_x = 14.0
        text_color = (0.2, 0.22, 0.25)

        if include_timestamps:
            ts_text = f"Timestamp: {format_timestamp(timestamp_seconds)}"
            page.insert_text(
                pymupdf.Point(pad_x, baseline_y),
                ts_text,
                fontsize=font_size,
                fontname="helv",
                color=text_color,
            )

        if include_page_numbers:
            page_text = f"Page {page_number} / {total_pages}"
            text_width = pymupdf.get_text_length(page_text, fontname="helv", fontsize=font_size)
            page.insert_text(
                pymupdf.Point(max(pad_x, page_width - pad_x - text_width), baseline_y),
                page_text,
                fontsize=font_size,
                fontname="helv",
                color=text_color,
            )
