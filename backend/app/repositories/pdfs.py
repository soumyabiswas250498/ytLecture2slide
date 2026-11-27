"""Transactional PDF generation claims, durable state, and PDF Library queries."""

from datetime import UTC, datetime
from math import ceil
from typing import Any, Literal, cast

from sqlalchemy import ColumnElement, func, inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.pdfs import (
    PdfCompressionMode,
    PdfConfig,
    PdfConflict,
    PdfLibraryItem,
    PdfLibraryPage,
    PdfState,
)
from app.infrastructure.models import ChannelRecord, PdfGenerationRecord, VideoRecord, utc_now


def _ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _parse_compression(raw_config: str | None) -> PdfCompressionMode:
    if not raw_config or raw_config == "{}":
        return "lossless"
    try:
        return PdfConfig.model_validate_json(raw_config).compression
    except Exception:
        return "lossless"


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class PdfRepository:
    """SQLAlchemy repository for independent PDF generation state and library listing."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    @staticmethod
    def _to_state(record: PdfGenerationRecord) -> PdfState:
        from app.domain.pdfs import PdfStatus

        return PdfState(
            video_id=record.video_id,
            source_slide_generation=record.source_slide_generation,
            status=cast(PdfStatus, record.status),
            requested=record.requested,
            progress=record.progress,
            completed_pages=record.completed_pages,
            total_pages=record.total_pages,
            pdf_path=record.pdf_path,
            pdf_filename=record.pdf_filename,
            page_count=record.page_count,
            file_size_bytes=record.file_size_bytes,
            compression=_parse_compression(record.configuration),
            configuration=record.configuration,
            started_at=_ensure_utc(record.started_at) if record.started_at is not None else None,
            completed_at=(
                _ensure_utc(record.completed_at) if record.completed_at is not None else None
            ),
            retry_count=record.retry_count,
            error=record.error,
        )

    def get(self, video_id: int) -> PdfState:
        with self.sessions() as session:
            row = session.get(PdfGenerationRecord, video_id)
            return self._to_state(row) if row else PdfState(video_id=video_id)

    def save(self, video_id: int, **values: Any) -> PdfState:
        now = utc_now()
        with self.sessions() as session:
            row = session.get(PdfGenerationRecord, video_id)
            if row is None:
                row = PdfGenerationRecord(video_id=video_id, created_at=now, updated_at=now)
                session.add(row)
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = now
            session.commit()
            session.refresh(row)
            return self._to_state(row)

    def claim(
        self,
        video_id: int,
        configuration: PdfConfig,
        *,
        total_pages: int,
        source_slide_generation: str,
    ) -> PdfState:
        now = utc_now()
        try:
            with self.sessions() as session:
                if session.get(PdfGenerationRecord, video_id) is None:
                    session.add(
                        PdfGenerationRecord(video_id=video_id, created_at=now, updated_at=now)
                    )
                    session.flush()
                changed = session.execute(
                    update(PdfGenerationRecord)
                    .where(
                        PdfGenerationRecord.video_id == video_id,
                        PdfGenerationRecord.requested.is_(False),
                        PdfGenerationRecord.status != "generating",
                    )
                    .values(
                        requested=True,
                        status="pending",
                        progress=0.0,
                        completed_pages=0,
                        total_pages=total_pages,
                        source_slide_generation=source_slide_generation,
                        error=None,
                        retry_count=0,
                        started_at=None,
                        configuration=configuration.model_dump_json(),
                        updated_at=now,
                    )
                )
                if changed.rowcount != 1:  # type: ignore[attr-defined]
                    raise PdfConflict("PDF generation is already queued or active.")
                session.commit()
        except IntegrityError as exc:
            raise PdfConflict("Another request claimed PDF generation.") from exc
        return self.get(video_id)

    def recoverable(self) -> list[PdfState]:
        with self.sessions() as session:
            if not inspect(session.get_bind()).has_table("pdf_generations"):
                return []
            return [
                self._to_state(row)
                for row in session.scalars(
                    select(PdfGenerationRecord).where(PdfGenerationRecord.requested.is_(True))
                )
            ]

    def list_library(
        self,
        *,
        search: str | None = None,
        channel_id: int | None = None,
        published_after: datetime | None = None,
        published_before: datetime | None = None,
        sort_by: Literal[
            "generated_at", "published_at", "title", "page_count", "file_size_bytes"
        ] = "generated_at",
        sort_order: Literal["asc", "desc"] = "desc",
        page: int = 1,
        page_size: int = 20,
    ) -> PdfLibraryPage:
        with self.sessions() as session:
            filters: list[ColumnElement[bool]] = [
                PdfGenerationRecord.pdf_path.is_not(None),
                PdfGenerationRecord.pdf_filename.is_not(None),
                PdfGenerationRecord.page_count > 0,
            ]
            if search and search.strip():
                pattern = f"%{_escape_like(search.strip())}%"
                filters.append(VideoRecord.title.ilike(pattern, escape="\\"))
            if channel_id is not None:
                filters.append(VideoRecord.channel_id == channel_id)
            if published_after is not None:
                filters.append(VideoRecord.published_at >= published_after)
            if published_before is not None:
                filters.append(VideoRecord.published_at <= published_before)

            agg_stmt = (
                select(
                    func.count(PdfGenerationRecord.video_id),
                    func.coalesce(func.sum(PdfGenerationRecord.file_size_bytes), 0),
                    func.coalesce(func.sum(PdfGenerationRecord.page_count), 0),
                )
                .select_from(PdfGenerationRecord)
                .join(VideoRecord, VideoRecord.id == PdfGenerationRecord.video_id)
                .where(*filters)
            )
            agg_row = session.execute(agg_stmt).one()
            total = int(agg_row[0] or 0)
            total_bytes = int(agg_row[1] or 0)
            total_pages_sum = int(agg_row[2] or 0)
            total_pages = max(1, ceil(total / page_size)) if total > 0 else 1

            sort_col_map = {
                "generated_at": PdfGenerationRecord.completed_at,
                "published_at": VideoRecord.published_at,
                "title": VideoRecord.title,
                "page_count": PdfGenerationRecord.page_count,
                "file_size_bytes": PdfGenerationRecord.file_size_bytes,
            }
            sort_col = sort_col_map[sort_by]
            order_expr = sort_col.asc() if sort_order == "asc" else sort_col.desc()

            rows_stmt = (
                select(PdfGenerationRecord, VideoRecord, ChannelRecord.name)
                .join(VideoRecord, VideoRecord.id == PdfGenerationRecord.video_id)
                .outerjoin(ChannelRecord, ChannelRecord.id == VideoRecord.channel_id)
                .where(*filters)
                .order_by(order_expr, VideoRecord.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            rows = session.execute(rows_stmt).all()
            items = [
                PdfLibraryItem(
                    video_id=pdf.video_id,
                    youtube_video_id=video.youtube_video_id,
                    video_title=video.title,
                    channel_id=video.channel_id,
                    channel_name=channel_name or video.channel_name or "Unknown Channel",
                    published_at=_ensure_utc(video.published_at),
                    generated_at=_ensure_utc(pdf.completed_at or pdf.updated_at),
                    page_count=pdf.page_count,
                    file_size_bytes=pdf.file_size_bytes,
                    pdf_filename=pdf.pdf_filename or "",
                    compression=_parse_compression(pdf.configuration),
                    source_slide_generation=pdf.source_slide_generation,
                    is_excluded=video.is_excluded,
                )
                for pdf, video, channel_name in rows
            ]
            return PdfLibraryPage(
                items=items,
                total=total,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
                total_bytes=total_bytes,
                total_pages_sum=total_pages_sum,
            )

    def get_library_item(self, video_id: int) -> PdfLibraryItem | None:
        with self.sessions() as session:
            row = session.execute(
                select(PdfGenerationRecord, VideoRecord, ChannelRecord.name)
                .join(VideoRecord, VideoRecord.id == PdfGenerationRecord.video_id)
                .outerjoin(ChannelRecord, ChannelRecord.id == VideoRecord.channel_id)
                .where(
                    PdfGenerationRecord.video_id == video_id,
                    PdfGenerationRecord.pdf_path.is_not(None),
                    PdfGenerationRecord.pdf_filename.is_not(None),
                    PdfGenerationRecord.page_count > 0,
                )
            ).one_or_none()
            if row is None:
                return None
            pdf, video, channel_name = row
            return PdfLibraryItem(
                video_id=pdf.video_id,
                youtube_video_id=video.youtube_video_id,
                video_title=video.title,
                channel_id=video.channel_id,
                channel_name=channel_name or video.channel_name or "Unknown Channel",
                published_at=_ensure_utc(video.published_at),
                generated_at=_ensure_utc(pdf.completed_at or pdf.updated_at),
                page_count=pdf.page_count,
                file_size_bytes=pdf.file_size_bytes,
                pdf_filename=pdf.pdf_filename or "",
                compression=_parse_compression(pdf.configuration),
                source_slide_generation=pdf.source_slide_generation,
                is_excluded=video.is_excluded,
            )
