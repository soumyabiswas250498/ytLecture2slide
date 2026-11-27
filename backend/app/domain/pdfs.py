"""Validated PDF generation contracts; no HTTP, database, or YouTube dependencies."""

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PdfStatus = Literal["pending", "generating", "generated", "failed", "cancelled"]
PdfCompressionMode = Literal["lossless", "maximum_quality", "high_quality", "compact"]

COMPRESSION_JPEG_QUALITY: dict[PdfCompressionMode, int | None] = {
    "lossless": None,
    "maximum_quality": 95,
    "high_quality": 90,
    "compact": 85,
}

COMPRESSION_MODE_DESCRIPTIONS: dict[PdfCompressionMode, str] = {
    "lossless": "Original PNG — zero compression artifacts, largest file size.",
    "maximum_quality": (
        "JPEG quality 95 — near-lossless visual fidelity with significant size reduction."
    ),
    "high_quality": "JPEG quality 90 — crisp text and annotations with smaller files.",
    "compact": "JPEG quality 85 — smallest file size; inspect small text and thin strokes.",
}


class PdfError(Exception):
    """PDF generation or validation could not safely complete."""


class PdfConflict(PdfError):
    """Another operation conflicts with PDF generation or state."""


class PdfNotFoundError(PdfError):
    """Requested PDF record or file does not exist."""


class PdfCancelled(PdfError):
    """PDF generation was cancelled or interrupted."""


class PdfConfig(BaseModel):
    """Typed configuration for image-to-PDF generation."""

    model_config = ConfigDict(extra="forbid")

    images_per_page: Literal[1] = 1
    orientation: Literal["landscape"] = "landscape"
    compression: PdfCompressionMode = "compact"
    smartboard_cropping: Literal[False] = False
    include_page_numbers: bool = True
    include_timestamps: bool = True
    cover_page: Literal[False] = False
    ocr_enabled: Literal[False] = False
    manual_review_required: Literal[False] = False
    footer_height_pt: int = Field(default=28, ge=18, le=72)
    min_free_disk_mb: int = Field(default=500, ge=0)


class PdfImageInput(BaseModel):
    """Single chronological image input for PDF generation."""

    image_path: Path
    timestamp_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_timestamp_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    slide_id: str | None = None


class PdfDocumentMetadata(BaseModel):
    """Metadata embedded into generated PDF documents."""

    title: str = Field(min_length=1)
    channel_name: str = Field(default="Unknown Channel")
    source_url: str = Field(default="")
    youtube_video_id: str | None = None
    published_at: datetime | None = None


class PdfPageValidation(BaseModel):
    """Verified geometry and embedded image dimensions of one PDF page."""

    page_number: int = Field(ge=1)
    width_px: int = Field(ge=1)
    height_px: int = Field(ge=1)
    page_width_pt: float = Field(gt=0)
    page_height_pt: float = Field(gt=0)


class PdfGenerationResult(BaseModel):
    """Validated result of a completed PDF generation."""

    output_path: Path
    page_count: int = Field(ge=1)
    file_size_bytes: int = Field(ge=1)
    duration_seconds: float = Field(ge=0)
    compression: PdfCompressionMode = "compact"
    pages: list[PdfPageValidation]


class PdfState(BaseModel):
    """Persisted PDF generation state for a video."""

    model_config = ConfigDict(from_attributes=True)

    video_id: int
    source_slide_generation: str | None = None
    status: PdfStatus = "pending"
    requested: bool = False
    progress: float = 0.0
    completed_pages: int = 0
    total_pages: int = 0
    pdf_path: str | None = None
    pdf_filename: str | None = None
    page_count: int = 0
    file_size_bytes: int = 0
    compression: PdfCompressionMode = "compact"
    configuration: str = "{}"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retry_count: int = 0
    error: str | None = None


class PdfLibraryItem(BaseModel):
    """Summary row for a generated PDF in the PDF Library."""

    video_id: int
    youtube_video_id: str
    video_title: str
    channel_id: int | None
    channel_name: str
    published_at: datetime
    generated_at: datetime
    page_count: int
    file_size_bytes: int
    pdf_filename: str
    compression: PdfCompressionMode = "compact"
    source_slide_generation: str | None = None
    is_excluded: bool = False


class PdfLibraryPage(BaseModel):
    """Paginated PDF Library response with aggregate summary."""

    items: list[PdfLibraryItem]
    total: int
    page: int
    page_size: int
    total_pages: int
    total_bytes: int
    total_pages_sum: int
