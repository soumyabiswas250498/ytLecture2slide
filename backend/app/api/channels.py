from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from app.domain.channels import ChannelEntity, InvalidCsvError
from app.repositories.channels import ChannelRepository
from app.services.channels import ChannelService

router = APIRouter(prefix="/api/v1/channels", tags=["channels"])


def get_channel_service(request: Request) -> ChannelService:
    repository = ChannelRepository(request.app.state.sessions)
    return ChannelService(
        repository=repository,
        default_search_keyword=request.app.state.settings.default_search_keyword,
    )


ServiceDep = Annotated[ChannelService, Depends(get_channel_service)]


class ChannelCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    channel_url: str = Field(min_length=1, max_length=512)
    youtube_channel_id: str | None = Field(default=None, max_length=64)
    sample_video_url: str | None = Field(default=None, max_length=512)
    search_keyword: str | None = Field(default=None, max_length=120)
    is_active: bool = True


class ChannelUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    channel_url: str | None = Field(default=None, min_length=1, max_length=512)
    youtube_channel_id: str | None = Field(default=None, max_length=64)
    sample_video_url: str | None = Field(default=None, max_length=512)
    search_keyword: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None


class ChannelResponse(BaseModel):
    id: int
    name: str
    channel_url: str
    youtube_channel_id: str | None
    sample_video_url: str | None
    search_keyword: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, entity: ChannelEntity) -> "ChannelResponse":
        return cls(
            id=entity.id,
            name=entity.name,
            channel_url=entity.channel_url,
            youtube_channel_id=entity.youtube_channel_id,
            sample_video_url=entity.sample_video_url,
            search_keyword=entity.search_keyword,
            is_active=entity.is_active,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )


class ChannelSummaryResponse(BaseModel):
    total: int
    active: int
    inactive: int


class ChannelListResponse(BaseModel):
    items: list[ChannelResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    summary: ChannelSummaryResponse


class CsvRowIssueResponse(BaseModel):
    row_number: int
    channel_name: str | None
    channel_url: str | None
    reason: str


class ChannelCsvImportResponse(BaseModel):
    total_rows: int
    imported_count: int
    skipped_count: int
    invalid_count: int
    imported: list[ChannelResponse]
    skipped: list[CsvRowIssueResponse]
    errors: list[CsvRowIssueResponse]


@router.get("", response_model=ChannelListResponse)
def list_channels(
    service: ServiceDep,
    search: str | None = Query(default=None, max_length=120),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ChannelListResponse:
    result = service.list_channels(
        search=search, is_active=is_active, page=page, page_size=page_size
    )
    return ChannelListResponse(
        items=[ChannelResponse.from_entity(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
        summary=ChannelSummaryResponse(
            total=result.summary.total,
            active=result.summary.active,
            inactive=result.summary.inactive,
        ),
    )


@router.post("", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
def create_channel(payload: ChannelCreateRequest, service: ServiceDep) -> ChannelResponse:
    created = service.create_channel(
        name=payload.name,
        channel_url=payload.channel_url,
        youtube_channel_id=payload.youtube_channel_id,
        sample_video_url=payload.sample_video_url,
        search_keyword=payload.search_keyword,
        is_active=payload.is_active,
    )
    return ChannelResponse.from_entity(created)


@router.get("/export")
def export_channels_csv(
    service: ServiceDep,
    search: str | None = Query(default=None, max_length=120),
    is_active: bool | None = Query(default=None),
) -> Response:
    csv_content = service.export_csv(search=search, is_active=is_active)
    return Response(
        content=csv_content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="channels.csv"'},
    )


@router.get("/template")
def download_csv_template(service: ServiceDep) -> Response:
    csv_content = service.csv_template()
    return Response(
        content=csv_content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="channels-template.csv"'},
    )


@router.post("/import", response_model=ChannelCsvImportResponse)
async def import_channels_csv(
    service: ServiceDep,
    file: UploadFile = File(...),  # noqa: B008
) -> ChannelCsvImportResponse:
    if not file.filename:
        raise InvalidCsvError("Please choose a CSV file to upload.")
    content = await file.read()
    summary = service.import_csv(content)
    return ChannelCsvImportResponse(
        total_rows=summary.total_rows,
        imported_count=summary.imported_count,
        skipped_count=summary.skipped_count,
        invalid_count=summary.invalid_count,
        imported=[ChannelResponse.from_entity(item) for item in summary.imported],
        skipped=[
            CsvRowIssueResponse(
                row_number=issue.row_number,
                channel_name=issue.channel_name,
                channel_url=issue.channel_url,
                reason=issue.reason,
            )
            for issue in summary.skipped
        ],
        errors=[
            CsvRowIssueResponse(
                row_number=issue.row_number,
                channel_name=issue.channel_name,
                channel_url=issue.channel_url,
                reason=issue.reason,
            )
            for issue in summary.errors
        ],
    )


@router.get("/{channel_id}", response_model=ChannelResponse)
def get_channel(channel_id: int, service: ServiceDep) -> ChannelResponse:
    return ChannelResponse.from_entity(service.get_channel(channel_id))


@router.patch("/{channel_id}", response_model=ChannelResponse)
def update_channel(
    channel_id: int, payload: ChannelUpdateRequest, service: ServiceDep
) -> ChannelResponse:
    fields = payload.model_fields_set
    updated = service.update_channel(
        channel_id,
        name=payload.name if "name" in fields else None,
        channel_url=payload.channel_url if "channel_url" in fields else None,
        youtube_channel_id=payload.youtube_channel_id,
        update_youtube_channel_id="youtube_channel_id" in fields,
        sample_video_url=payload.sample_video_url,
        update_sample_video_url="sample_video_url" in fields,
        search_keyword=payload.search_keyword,
        update_search_keyword="search_keyword" in fields,
        is_active=payload.is_active if "is_active" in fields else None,
    )
    return ChannelResponse.from_entity(updated)


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_channel(channel_id: int, service: ServiceDep) -> Response:
    service.delete_channel(channel_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
