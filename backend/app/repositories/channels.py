from datetime import UTC, datetime
from math import ceil

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domain.channels import (
    ChannelCreateInput,
    ChannelEntity,
    ChannelNotFoundError,
    ChannelPage,
    ChannelSummary,
    DuplicateChannelError,
)
from app.infrastructure.models import ChannelRecord, utc_now


def _ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _to_entity(record: ChannelRecord) -> ChannelEntity:
    return ChannelEntity(
        id=record.id,
        name=record.name,
        channel_url=record.channel_url,
        youtube_channel_id=record.youtube_channel_id,
        sample_video_url=record.sample_video_url,
        search_keyword=record.search_keyword,
        is_active=record.is_active,
        created_at=_ensure_utc(record.created_at),
        updated_at=_ensure_utc(record.updated_at),
    )


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ChannelRepository:
    """SQLAlchemy repository for persistent channel records."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def create(self, data: ChannelCreateInput) -> ChannelEntity:
        now = utc_now()
        record = ChannelRecord(
            name=data.name,
            channel_url=data.channel_url,
            youtube_channel_id=data.youtube_channel_id,
            sample_video_url=data.sample_video_url,
            search_keyword=data.search_keyword,
            is_active=data.is_active,
            created_at=now,
            updated_at=now,
        )
        with self._sessions() as session:
            try:
                session.add(record)
                session.commit()
                session.refresh(record)
            except IntegrityError as exc:
                session.rollback()
                raise DuplicateChannelError(
                    "A channel with this URL or YouTube channel ID already exists."
                ) from exc
            return _to_entity(record)

    def create_many(self, items: list[ChannelCreateInput]) -> list[ChannelEntity]:
        if not items:
            return []
        now = utc_now()
        records = [
            ChannelRecord(
                name=item.name,
                channel_url=item.channel_url,
                youtube_channel_id=item.youtube_channel_id,
                sample_video_url=item.sample_video_url,
                search_keyword=item.search_keyword,
                is_active=item.is_active,
                created_at=now,
                updated_at=now,
            )
            for item in items
        ]
        with self._sessions() as session:
            try:
                session.add_all(records)
                session.commit()
                for record in records:
                    session.refresh(record)
            except IntegrityError as exc:
                session.rollback()
                raise DuplicateChannelError(
                    "One or more channels duplicate an existing URL or YouTube channel ID."
                ) from exc
            return [_to_entity(record) for record in records]

    def get_by_id(self, channel_id: int) -> ChannelEntity:
        with self._sessions() as session:
            record = session.get(ChannelRecord, channel_id)
            if record is None:
                raise ChannelNotFoundError("Channel not found.")
            return _to_entity(record)

    def find_duplicate(
        self,
        *,
        channel_url: str,
        youtube_channel_id: str | None,
        exclude_id: int | None = None,
    ) -> ChannelEntity | None:
        with self._sessions() as session:
            conditions = [ChannelRecord.channel_url == channel_url]
            if youtube_channel_id is not None:
                conditions.append(ChannelRecord.youtube_channel_id == youtube_channel_id)
            stmt = select(ChannelRecord).where(or_(*conditions))
            if exclude_id is not None:
                stmt = stmt.where(ChannelRecord.id != exclude_id)
            record = session.scalar(stmt.limit(1))
            return _to_entity(record) if record is not None else None

    def get_existing_identities(self) -> tuple[set[str], set[str]]:
        with self._sessions() as session:
            rows = session.execute(
                select(ChannelRecord.channel_url, ChannelRecord.youtube_channel_id)
            ).all()
            urls = {row[0] for row in rows}
            yt_ids = {row[1] for row in rows if row[1] is not None}
            return urls, yt_ids

    def list_channels(
        self,
        *,
        search: str | None = None,
        is_active: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> ChannelPage:
        with self._sessions() as session:
            filters = self._build_filters(search=search, is_active=is_active)

            filtered_total = (
                session.scalar(select(func.count(ChannelRecord.id)).where(*filters)) or 0
            )

            summary_row = session.execute(
                select(
                    func.count(ChannelRecord.id),
                    func.count(ChannelRecord.id).filter(ChannelRecord.is_active.is_(True)),
                )
            ).one()
            total_all = int(summary_row[0] or 0)
            active_all = int(summary_row[1] or 0)
            inactive_all = total_all - active_all

            total_pages = max(1, ceil(filtered_total / page_size)) if filtered_total > 0 else 1
            offset = (page - 1) * page_size
            records = session.scalars(
                select(ChannelRecord)
                .where(*filters)
                .order_by(ChannelRecord.id.desc())
                .offset(offset)
                .limit(page_size)
            ).all()

            return ChannelPage(
                items=[_to_entity(record) for record in records],
                total=filtered_total,
                page=page,
                page_size=page_size,
                total_pages=total_pages,
                summary=ChannelSummary(
                    total=total_all,
                    active=active_all,
                    inactive=inactive_all,
                ),
            )

    def list_all(
        self,
        *,
        search: str | None = None,
        is_active: bool | None = None,
    ) -> list[ChannelEntity]:
        with self._sessions() as session:
            filters = self._build_filters(search=search, is_active=is_active)
            records = session.scalars(
                select(ChannelRecord).where(*filters).order_by(ChannelRecord.id.asc())
            ).all()
            return [_to_entity(record) for record in records]

    def update(
        self,
        channel_id: int,
        *,
        name: str | None = None,
        channel_url: str | None = None,
        youtube_channel_id: str | None = None,
        update_youtube_channel_id: bool = False,
        sample_video_url: str | None = None,
        update_sample_video_url: bool = False,
        search_keyword: str | None = None,
        is_active: bool | None = None,
    ) -> ChannelEntity:
        with self._sessions() as session:
            record = session.get(ChannelRecord, channel_id)
            if record is None:
                raise ChannelNotFoundError("Channel not found.")
            if name is not None:
                record.name = name
            if channel_url is not None:
                record.channel_url = channel_url
            if update_youtube_channel_id:
                record.youtube_channel_id = youtube_channel_id
            if update_sample_video_url:
                record.sample_video_url = sample_video_url
            if search_keyword is not None:
                record.search_keyword = search_keyword
            if is_active is not None:
                record.is_active = is_active
            record.updated_at = utc_now()
            try:
                session.commit()
                session.refresh(record)
            except IntegrityError as exc:
                session.rollback()
                raise DuplicateChannelError(
                    "A channel with this URL or YouTube channel ID already exists."
                ) from exc
            return _to_entity(record)

    def delete(self, channel_id: int) -> None:
        with self._sessions() as session:
            record = session.get(ChannelRecord, channel_id)
            if record is None:
                raise ChannelNotFoundError("Channel not found.")
            session.delete(record)
            session.commit()

    @staticmethod
    def _build_filters(*, search: str | None, is_active: bool | None) -> list[ColumnElement[bool]]:
        filters: list[ColumnElement[bool]] = []
        if search is not None and search.strip():
            escaped = _escape_like(search.strip())
            pattern = f"%{escaped}%"
            filters.append(
                or_(
                    ChannelRecord.name.ilike(pattern, escape="\\"),
                    ChannelRecord.search_keyword.ilike(pattern, escape="\\"),
                )
            )
        if is_active is not None:
            filters.append(ChannelRecord.is_active.is_(is_active))
        return filters
