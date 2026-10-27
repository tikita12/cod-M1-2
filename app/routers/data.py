from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response

from app.catalog import agricultural_categories
from app.dependencies import price_service, repository, require_admin
from app.pagination import decode_price_cursor
from app.schemas import CatalogItem, PriceCreate, PricePage, PriceRecord, PriceUpdate, SummaryResponse, TrendResponse

router = APIRouter(prefix="/api/data", tags=["가격 데이터"])
RecordId = Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")]


@router.get("/catalog", response_model=list[CatalogItem], summary="등록할 수 있는 농산물 목록")
def catalog():
    return [{"item_name": name, "category": category} for name, category in sorted(agricultural_categories().items())]


@router.get("/summary", response_model=SummaryResponse, summary="선택한 월의 계절적 가격 하락 경향")
def summary(month: Annotated[int | None, Query(ge=1, le=12)] = None,
            limit: Annotated[int, Query(ge=1, le=100)] = 10, service=Depends(price_service)):
    selected_month = month if month is not None else date.today().month % 12 + 1
    return service.summary(selected_month, limit)


@router.get("", response_model=PricePage, summary="가격 자료 연월 최신순 목록 조회")
def list_prices(limit: Annotated[int, Query(ge=1, le=100)] = 30,
                cursor: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
                item_name: Annotated[str | None, Query(max_length=60)] = None, store=Depends(repository)):
    if cursor is not None:
        try:
            decode_price_cursor(cursor)
        except ValueError:
            raise HTTPException(status_code=422, detail="잘못된 목록 커서입니다. 목록을 새로 조회하세요") from None
    return store.list_page(limit, cursor, item_name)


@router.get('/trend', response_model=TrendResponse, summary='동일 조건의 월별 실제 가격 흐름')
def price_trend(item_name: Annotated[str, Query(min_length=1, max_length=60)],
                service=Depends(price_service)):
    return service.trend(item_name)


@router.post("", status_code=201, response_model=PriceRecord,
             dependencies=[Depends(require_admin)], summary="월별 가격 추가")
def create_price(payload: PriceCreate, service=Depends(price_service)):
    return service.create(payload)


@router.get("/{record_id}", response_model=PriceRecord, summary="가격 한 건 조회")
def get_price(record_id: RecordId, store=Depends(repository)):
    return store.get(record_id)


@router.patch("/{record_id}", response_model=PriceRecord,
              dependencies=[Depends(require_admin)], summary="가격·메모 수정")
def update_price(record_id: RecordId, payload: PriceUpdate, service=Depends(price_service)):
    return service.update(record_id, payload)


@router.delete("/{record_id}", status_code=204, dependencies=[Depends(require_admin)], summary="가격 삭제")
def delete_price(record_id: RecordId, service=Depends(price_service)):
    service.delete(record_id)
    return Response(status_code=204)
