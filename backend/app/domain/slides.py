"""Validated slide-processing contracts; no HTTP or database dependencies."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.extraction import ExtractionConflict, ExtractionError

Timestamp = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Normalized = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class SlideError(ExtractionError):
    """Slide processing could not safely complete."""


class SlideConflict(ExtractionConflict):
    """Another media operation conflicts with slide processing."""


class Crop(BaseModel):
    """Normalized rectangle, explicitly chosen by the operator."""

    model_config = ConfigDict(extra="forbid")
    left: float = Field(default=0, ge=0, lt=1, allow_inf_nan=False)
    top: float = Field(default=0, ge=0, lt=1, allow_inf_nan=False)
    right: float = Field(default=1, gt=0, le=1, allow_inf_nan=False)
    bottom: float = Field(default=1, gt=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered(self) -> "Crop":
        if self.left >= self.right or self.top >= self.bottom:
            raise ValueError("Crop must have positive width and height.")
        return self


class SlideConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    crop: Crop | None = None
    board_min_area: float = Field(default=0.85, gt=0, le=1)
    board_border_margin: float = Field(default=0.06, ge=0, le=0.2)
    edge_low_threshold: int = Field(default=60, ge=0, le=255)
    edge_high_threshold: int = Field(default=160, ge=1, le=255)
    board_polygon_epsilon: float = Field(default=0.02, gt=0, le=0.1)
    alignment_min_response: float = Field(default=0.8, ge=0, le=1)
    feature_max_distance: int = Field(default=32, ge=0, le=256)
    feature_min_matches: int = Field(default=12, ge=4, le=1000)
    feature_min_inlier_fraction: float = Field(default=0.8, gt=0, le=1)
    feature_max_inlier_shift: float = Field(default=1, gt=0, le=5)
    comparison_width: int = Field(default=640, ge=160, le=1920)
    pixel_difference: int = Field(default=24, ge=1, le=255)
    group_ssim: float = Field(default=0.85, ge=0, le=1)
    group_edge_agreement: float = Field(default=0.60, ge=0, le=1)
    group_max_changed: float = Field(default=0.22, ge=0, le=1)
    duplicate_ssim: float = Field(default=0.99, ge=0, le=1)
    duplicate_max_changed: float = Field(default=0.00002, ge=0, le=0.01)
    foreground_min_area: float = Field(default=0.015, gt=0, le=0.5)
    foreground_padding: float = Field(default=0.03, ge=0, le=0.1)
    mask_dilation_pixels: int = Field(default=5, ge=0, le=30)
    foreground_max_area: float = Field(default=0.4, gt=0, le=0.8)
    fusion_comparison_blur: Literal[1, 3, 5] = 3
    fusion_max_residual: float = Field(default=0.0001, ge=0, le=0.01)
    adaptive_enabled: bool = True
    additional_interval: float = Field(default=5, ge=0.1, le=60, allow_inf_nan=False)
    max_additional_samples: int = Field(default=40, ge=0, le=1000)
    max_samples_per_segment: int = Field(default=6, ge=1, le=30)
    max_fusion_frames: int = Field(default=5, ge=3, le=9)
    min_free_disk_mb: int = Field(default=500, ge=0)
    max_image_pixels: int = Field(default=10_000_000, ge=1)
    alignment_max_shift: float = Field(default=2, ge=0, le=10)


class SlideQuality(BaseModel):
    obstruction_fraction: float = Field(ge=0, le=1)
    unresolved_fraction: float = Field(ge=0, le=1)
    sharpness: float = Field(ge=0, allow_inf_nan=False)
    measurement_kind: Literal["heuristic_not_accuracy"] = "heuristic_not_accuracy"
    verified_accuracy: None = None


class Slide(BaseModel):
    slide_id: str = Field(pattern=r"^slide_\d{5}$")
    source_frame_ids: list[str] = Field(min_length=1)
    source_timestamps: list[Timestamp] = Field(min_length=1)
    additional_sampled_timestamps: list[Timestamp] = []
    processed_image_path: str = Field(pattern=r"^slide_\d{5}\.png$")
    cropped_image_path: str = Field(pattern=r"^crop_\d{5}\.png$")
    obstruction_mask_path: str = Field(pattern=r"^mask_\d{5}\.png$")
    original_image_path: str = Field(pattern=r"^original_\d{5}\.png$")
    board_coordinates: list[tuple[Normalized, Normalized]] = Field(min_length=4, max_length=4)
    reconstruction_method: Literal["original", "masked_pixel_fusion", "temporal_median"]
    quality: SlideQuality
    duplicate_group: str
    warnings: list[str] = []
    fallback: bool
    incomplete: bool
    manual_review: bool


class FrameDecision(BaseModel):
    frame_id: str
    timestamp: float = Field(ge=0)
    action: Literal["retained", "merged", "excluded"]
    slide_id: str
    reason: str


class SlideManifest(BaseModel):
    version: Literal[1] = 1
    video_id: int = Field(gt=0)
    extraction_directory: str
    configuration: SlideConfig
    slides: list[Slide] = Field(min_length=1)
    decisions: list[FrameDecision]
    input_count: int = Field(gt=0)
    additional_sampled_timestamps: list[Timestamp] = []
    duplicate_count: int = Field(ge=0)
    processing_duration: float = Field(ge=0)
    warnings: list[str] = []
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def integrity(self) -> "SlideManifest":
        ids = {s.slide_id for s in self.slides}
        if len(ids) != len(self.slides) or len(self.decisions) != self.input_count:
            raise ValueError("Slide IDs or decision count are inconsistent.")
        if len({d.frame_id for d in self.decisions}) != self.input_count:
            raise ValueError("Every primary frame requires exactly one decision.")
        if any(d.slide_id not in ids for d in self.decisions):
            raise ValueError("Decision refers to an unknown slide.")
        if self.duplicate_count != sum(d.action == "excluded" for d in self.decisions):
            raise ValueError("Duplicate count is inconsistent.")
        if self.decisions != sorted(self.decisions, key=lambda d: d.timestamp):
            raise ValueError("Decisions must be chronological.")
        if self.slides != sorted(self.slides, key=lambda s: s.source_timestamps[0]):
            raise ValueError("Slides must be chronological.")
        for slide in self.slides:
            if len(slide.source_frame_ids) != len(slide.source_timestamps):
                raise ValueError("Slide source references are inconsistent.")
        by_id = {slide.slide_id: slide for slide in self.slides}
        for decision in self.decisions:
            slide = by_id[decision.slide_id]
            references = dict(zip(slide.source_frame_ids, slide.source_timestamps, strict=True))
            if references.get(decision.frame_id) != decision.timestamp:
                raise ValueError("Decision source reference does not match its slide.")
        return self


class SlideState(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    video_id: int
    status: Literal["pending", "processing", "processed", "failed", "cancelled"] = "pending"
    requested: bool = False
    progress: float = 0
    input_count: int = 0
    completed_count: int = 0
    additional_count: int = 0
    output_count: int = 0
    duplicate_count: int = 0
    reconstructed_count: int = 0
    review_count: int = 0
    retry_count: int = 0
    configuration: str = "{}"
    output_directory: str | None = None
    error: str | None = None
