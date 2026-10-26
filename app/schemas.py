import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.catalog import agricultural_categories

Price = Annotated[Decimal, Field(gt=0, le=10000000, max_digits=14, decimal_places=4, allow_inf_nan=False)]
Quantity = Annotated[Decimal, Field(gt=0, le=100000, max_digits=12, decimal_places=6, allow_inf_nan=False)]
Unit = Literal["kg", "g", "L", "ml", "포기", "개", "마리", "속", "장", "묶음", "봉", "손"]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def clean_text(cls, value):
        if isinstance(value, str):
            if any(ord(ch) < 32 for ch in value) or any(ch in value for ch in "<>"):
                raise ValueError("제어 문자와 HTML 태그 기호는 사용할 수 없습니다")
            return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value)).strip()
        return value


class PriceCreate(InputModel):
    year_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", examples=["2024-11"])
    item_name: str = Field(min_length=1, max_length=60, examples=["배추"])
    variety_name: str = Field(min_length=1, max_length=100, examples=["가을"])
    grade_name: str = Field(min_length=1, max_length=30, examples=["상품"])
    quantity: Quantity = Field(examples=[1])
    unit: Unit = Field(examples=["포기"])
    average_price: Price = Field(examples=[3500])
    note: str = Field(default="", max_length=300)

    @field_validator("year_month")
    @classmethod
    def completed_month(cls, value):
        month = date.fromisoformat(value + "-01")
        if month.year < 1996 or month >= date.today().replace(day=1):
            raise ValueError("1996년 이후의 완료된 월만 등록할 수 있습니다")
        return value

    @field_validator("item_name")
    @classmethod
    def known_item(cls, value):
        if value not in agricultural_categories():
            raise ValueError("농산물 목록에 없는 품목입니다. /api/data/catalog를 확인하세요")
        return value

    @field_validator("grade_name")
    @classmethod
    def valid_grade(cls, value):
        if value not in {"상품", "중품", "L과", "M과", "S과", "大", "中", "小"}:
            raise ValueError("지원하는 농산물 등급을 선택하세요")
        return value


class PriceUpdate(InputModel):
    average_price: Price
    note: str = Field(default="", max_length=300)


class PriceRecord(PriceCreate):
    id: str
    category: str
    comparison_quantity: Decimal
    comparison_unit: str
    source: Literal["manual", "csv"]
    created_at: datetime
    updated_at: datetime


class PricePage(BaseModel):
    items: list[PriceRecord]
    next_cursor: str | None
    has_more: bool


class CatalogItem(BaseModel):
    item_name: str
    category: str


class Candidate(BaseModel):
    rank: int
    item_name: str
    category: str
    month: int
    previous_month: int
    median_change_pct: float
    drop_year_count: int
    sample_year_count: int
    drop_frequency_pct: float
    first_sample_year: int
    last_sample_year: int
    sample_years: list[int]
    matched_pair_count: int
    enough_years: bool
    has_recent_observation: bool
    is_candidate: bool


class SummaryMetadata(BaseModel):
    start_year: int
    end_year: int
    min_years: int
    min_drop_frequency_pct: float
    recent_years: int
    selected_record_count: int
    paired_series_change_count: int
    paired_item_count: int
    method: str
    interpretation: str
    limitations: list[str]
    source_start: str | None
    source_end: str | None
    generated_at: datetime
    storage: Literal["firestore"] = "firestore"
    freshness: str = "매 요청마다 Firestore에서 조회하여 계산"


class SummaryResponse(BaseModel):
    metadata: SummaryMetadata
    target_month: int
    previous_month: int
    candidate_count: int
    candidates: list[Candidate]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=1000)
    month: int = Field(ge=1, le=12)
    owner_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    conversation_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")

    @field_validator("message")
    @classmethod
    def valid_message(cls, value):
        value = unicodedata.normalize("NFC", value).strip()
        if not value or "\x00" in value:
            raise ValueError("질문을 입력해 주세요")
        return value


class TrendPoint(BaseModel):
    month: int = Field(ge=1, le=12)
    price: float | None


class HistoricalPricePoint(TrendPoint):
    year: int


class PriceSeries(BaseModel):
    variety_name: str
    grade_name: str
    quantity: str
    unit: str
    year: int
    points: list[TrendPoint]
    history: list[HistoricalPricePoint]


class TrendResponse(BaseModel):
    item_name: str
    series: list[PriceSeries]
    storage: Literal['firestore']
    generated_at: datetime


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class ChatResponse(BaseModel):
    conversation_id: str
    message: ChatMessage
    created: bool


class ConversationPreview(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class ConversationList(BaseModel):
    items: list[ConversationPreview]


class ConversationDetail(ConversationPreview):
    messages: list[ChatMessage]
