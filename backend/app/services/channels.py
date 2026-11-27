import csv
import io
import logging
from typing import Any

from app.domain.channels import (
    ChannelCreateInput,
    ChannelEntity,
    ChannelError,
    ChannelPage,
    ChannelValidationError,
    CsvImportSummary,
    CsvRowIssue,
    DuplicateChannelError,
    InvalidCsvError,
    normalize_channel_name,
    normalize_channel_url,
    normalize_sample_video_url,
    normalize_search_keyword,
    normalize_youtube_channel_id,
    resolve_channel_identity,
)
from app.repositories.channels import ChannelRepository

logger = logging.getLogger("app.channels")

CSV_COLUMNS = (
    "channel_name",
    "channel_url",
    "sample_video_url",
    "search_keyword",
    "is_active",
)
REQUIRED_CSV_COLUMNS = frozenset({"channel_name", "channel_url"})
ALLOWED_CSV_COLUMNS = frozenset(CSV_COLUMNS)
MAX_CSV_BYTES = 2 * 1024 * 1024  # 2 MiB guard for single CSV upload
TRUTHY_VALUES = frozenset({"true", "1", "yes", "y", "active"})
FALSY_VALUES = frozenset({"false", "0", "no", "n", "inactive"})


def _parse_csv_bool(raw_value: str | None) -> bool:
    if raw_value is None or not raw_value.strip():
        return True
    normalized = raw_value.strip().lower()
    if normalized in TRUTHY_VALUES:
        return True
    if normalized in FALSY_VALUES:
        return False
    raise ChannelValidationError("is_active must be true/false, yes/no, or 1/0.")


class ChannelService:
    """Application service for channel registry, validation, and CSV import/export."""

    def __init__(self, repository: ChannelRepository, default_search_keyword: str) -> None:
        self._repository = repository
        self._default_search_keyword = default_search_keyword

    def create_channel(
        self,
        *,
        name: str,
        channel_url: str,
        youtube_channel_id: str | None = None,
        sample_video_url: str | None = None,
        search_keyword: str | None = None,
        is_active: bool = True,
    ) -> ChannelEntity:
        clean_name = normalize_channel_name(name)
        normalized_url, url_channel_id = normalize_channel_url(channel_url)
        explicit_id = normalize_youtube_channel_id(youtube_channel_id)
        resolved_id = resolve_channel_identity(normalized_url, url_channel_id, explicit_id)
        normalized_sample = normalize_sample_video_url(sample_video_url)
        keyword = normalize_search_keyword(
            search_keyword, default_keyword=self._default_search_keyword
        )

        existing = self._repository.find_duplicate(
            channel_url=normalized_url, youtube_channel_id=resolved_id
        )
        if existing is not None:
            raise DuplicateChannelError(
                self._duplicate_message(existing, normalized_url, resolved_id)
            )

        created = self._repository.create(
            ChannelCreateInput(
                name=clean_name,
                channel_url=normalized_url,
                youtube_channel_id=resolved_id,
                sample_video_url=normalized_sample,
                search_keyword=keyword,
                is_active=is_active,
            )
        )
        logger.info("Created channel id=%s name=%s", created.id, created.name)
        return created

    def get_channel(self, channel_id: int) -> ChannelEntity:
        return self._repository.get_by_id(channel_id)

    def list_channels(
        self,
        *,
        search: str | None = None,
        is_active: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> ChannelPage:
        return self._repository.list_channels(
            search=search, is_active=is_active, page=page, page_size=page_size
        )

    def update_channel(
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
        update_search_keyword: bool = False,
        is_active: bool | None = None,
    ) -> ChannelEntity:
        current = self._repository.get_by_id(channel_id)

        clean_name = normalize_channel_name(name) if name is not None else None

        if channel_url is not None:
            normalized_url, url_channel_id = normalize_channel_url(channel_url)
        else:
            normalized_url = current.channel_url
            _, url_channel_id = normalize_channel_url(current.channel_url)

        if update_youtube_channel_id:
            explicit_id = normalize_youtube_channel_id(youtube_channel_id)
            effective_yt_id = resolve_channel_identity(normalized_url, url_channel_id, explicit_id)
            should_update_yt_id = True
        elif channel_url is not None and url_channel_id is not None:
            effective_yt_id = resolve_channel_identity(
                normalized_url, url_channel_id, current.youtube_channel_id
            )
            should_update_yt_id = effective_yt_id != current.youtube_channel_id
        else:
            effective_yt_id = current.youtube_channel_id
            should_update_yt_id = False

        if (
            channel_url is not None
            and current.youtube_channel_id is not None
            and not update_youtube_channel_id
        ):
            # Ensure changing URL to another /channel/UC... validates against existing explicit ID.
            resolve_channel_identity(normalized_url, url_channel_id, current.youtube_channel_id)

        normalized_sample = (
            normalize_sample_video_url(sample_video_url) if update_sample_video_url else None
        )

        clean_keyword: str | None = None
        if update_search_keyword:
            if search_keyword is None or not search_keyword.strip():
                raise ChannelValidationError("Search keyword cannot be empty.")
            clean_keyword = normalize_search_keyword(
                search_keyword, default_keyword=self._default_search_keyword
            )

        if channel_url is not None or should_update_yt_id:
            duplicate = self._repository.find_duplicate(
                channel_url=normalized_url,
                youtube_channel_id=effective_yt_id,
                exclude_id=channel_id,
            )
            if duplicate is not None:
                raise DuplicateChannelError(
                    self._duplicate_message(duplicate, normalized_url, effective_yt_id)
                )

        updated = self._repository.update(
            channel_id,
            name=clean_name,
            channel_url=normalized_url if channel_url is not None else None,
            youtube_channel_id=effective_yt_id,
            update_youtube_channel_id=should_update_yt_id,
            sample_video_url=normalized_sample,
            update_sample_video_url=update_sample_video_url,
            search_keyword=clean_keyword,
            is_active=is_active,
        )
        logger.info("Updated channel id=%s", updated.id)
        return updated

    def delete_channel(self, channel_id: int) -> None:
        self._repository.delete(channel_id)
        logger.info("Deleted channel id=%s", channel_id)

    def export_csv(
        self,
        *,
        search: str | None = None,
        is_active: bool | None = None,
    ) -> str:
        channels = self._repository.list_all(search=search, is_active=is_active)
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow(CSV_COLUMNS)
        for channel in channels:
            writer.writerow(
                [
                    channel.name,
                    channel.channel_url,
                    channel.sample_video_url or "",
                    channel.search_keyword,
                    "true" if channel.is_active else "false",
                ]
            )
        return buffer.getvalue()

    @staticmethod
    def csv_template() -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\r\n")
        writer.writerow(CSV_COLUMNS)
        return buffer.getvalue()

    def import_csv(self, payload: bytes) -> CsvImportSummary:
        if not payload:
            raise InvalidCsvError("CSV file is empty.")
        if len(payload) > MAX_CSV_BYTES:
            raise InvalidCsvError("CSV file exceeds the 2 MiB size limit.")

        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise InvalidCsvError("CSV file must be UTF-8 encoded.") from exc

        reader = csv.reader(io.StringIO(text))
        try:
            raw_headers = next(reader)
        except StopIteration as exc:
            raise InvalidCsvError("CSV file has no header row.") from exc

        headers = [header.strip().lower() for header in raw_headers]
        if len(headers) != len(set(headers)):
            raise InvalidCsvError("CSV file contains duplicate column headers.")

        header_set = set(headers)
        missing_headers = sorted(REQUIRED_CSV_COLUMNS - header_set)
        if missing_headers:
            raise InvalidCsvError(
                f"CSV header is missing required columns: {', '.join(missing_headers)}."
            )

        unknown_headers = sorted(header_set - ALLOWED_CSV_COLUMNS)
        if unknown_headers:
            raise InvalidCsvError(
                f"CSV contains unsupported columns: {', '.join(unknown_headers)}."
            )

        existing_urls, existing_yt_ids = self._repository.get_existing_identities()
        seen_urls = set(existing_urls)
        seen_yt_ids = set(existing_yt_ids)

        pending_creates: list[ChannelCreateInput] = []
        skipped: list[CsvRowIssue] = []
        errors: list[CsvRowIssue] = []
        total_rows = 0

        for row_number, raw_cells in enumerate(reader, start=2):
            if not any(cell.strip() for cell in raw_cells):
                continue
            total_rows += 1

            if len(raw_cells) != len(headers):
                errors.append(
                    CsvRowIssue(
                        row_number=row_number,
                        channel_name=raw_cells[0].strip() or None if raw_cells else None,
                        channel_url=raw_cells[1].strip() or None if len(raw_cells) > 1 else None,
                        reason=f"Expected {len(headers)} columns, found {len(raw_cells)}.",
                    )
                )
                continue

            row: dict[str, str] = dict(zip(headers, raw_cells, strict=True))
            raw_name = row.get("channel_name", "").strip()
            raw_url = row.get("channel_url", "").strip()
            raw_sample = row.get("sample_video_url", "").strip()
            raw_keyword = row.get("search_keyword", "").strip()
            raw_active = row.get("is_active", "").strip()

            try:
                parsed = self._validate_csv_row(
                    raw_name=raw_name,
                    raw_url=raw_url,
                    raw_sample=raw_sample,
                    raw_keyword=raw_keyword,
                    raw_active=raw_active,
                )
            except ChannelError as exc:
                errors.append(
                    CsvRowIssue(
                        row_number=row_number,
                        channel_name=raw_name or None,
                        channel_url=raw_url or None,
                        reason=str(exc),
                    )
                )
                continue

            duplicate_reason = self._check_csv_duplicate(
                channel_url=parsed.channel_url,
                youtube_channel_id=parsed.youtube_channel_id,
                seen_urls=seen_urls,
                seen_yt_ids=seen_yt_ids,
                existing_urls=existing_urls,
                existing_yt_ids=existing_yt_ids,
            )
            if duplicate_reason is not None:
                skipped.append(
                    CsvRowIssue(
                        row_number=row_number,
                        channel_name=parsed.name,
                        channel_url=parsed.channel_url,
                        reason=duplicate_reason,
                    )
                )
                continue

            seen_urls.add(parsed.channel_url)
            if parsed.youtube_channel_id is not None:
                seen_yt_ids.add(parsed.youtube_channel_id)
            pending_creates.append(parsed)

        imported = self._repository.create_many(pending_creates)
        logger.info(
            "CSV import completed total=%s imported=%s skipped=%s invalid=%s",
            total_rows,
            len(imported),
            len(skipped),
            len(errors),
        )
        return CsvImportSummary(
            total_rows=total_rows,
            imported_count=len(imported),
            skipped_count=len(skipped),
            invalid_count=len(errors),
            imported=imported,
            skipped=skipped,
            errors=errors,
        )

    def _validate_csv_row(
        self,
        *,
        raw_name: str,
        raw_url: str,
        raw_sample: str,
        raw_keyword: str,
        raw_active: str,
    ) -> ChannelCreateInput:
        name = normalize_channel_name(raw_name)
        if not raw_url:
            raise ChannelValidationError("Channel URL is missing and requires manual correction.")
        normalized_url, url_channel_id = normalize_channel_url(raw_url)
        sample_url = normalize_sample_video_url(raw_sample)
        keyword = normalize_search_keyword(
            raw_keyword or None, default_keyword=self._default_search_keyword
        )
        is_active = _parse_csv_bool(raw_active)
        return ChannelCreateInput(
            name=name,
            channel_url=normalized_url,
            youtube_channel_id=url_channel_id,
            sample_video_url=sample_url,
            search_keyword=keyword,
            is_active=is_active,
        )

    @staticmethod
    def _check_csv_duplicate(
        *,
        channel_url: str,
        youtube_channel_id: str | None,
        seen_urls: set[str],
        seen_yt_ids: set[str],
        existing_urls: set[str],
        existing_yt_ids: set[str],
    ) -> str | None:
        if channel_url in existing_urls:
            return "Channel URL already exists in the database."
        if youtube_channel_id is not None and youtube_channel_id in existing_yt_ids:
            return "YouTube channel ID already exists in the database."
        if channel_url in seen_urls:
            return "Duplicate channel URL within CSV."
        if youtube_channel_id is not None and youtube_channel_id in seen_yt_ids:
            return "Duplicate YouTube channel ID within CSV."
        return None

    @staticmethod
    def _duplicate_message(
        existing: ChannelEntity, normalized_url: str, youtube_channel_id: str | None
    ) -> str:
        if existing.channel_url == normalized_url:
            return "A channel with this normalized URL already exists."
        if youtube_channel_id is not None and existing.youtube_channel_id == youtube_channel_id:
            return "A channel with this YouTube channel ID already exists."
        return "Channel already exists."


def serialize_kwargs(data: Any) -> dict[str, Any]:
    return dict(data)
