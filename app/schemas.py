from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain import Product, Reason, Status

MAX_INT = 9_007_199_254_740_991  # 2**53 - 1: largest integer JSON carries losslessly


class HealthResponse(BaseModel):
    status: str


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "amount": 2400000,
                    "monthly_income": 1500000,
                    "employment_months": 24,
                    "external_score": 750,
                    "product": "PHONE",
                }
            ]
        },
    )

    # strict per field: a model-wide strict would also reject "PHONE" for the enum.
    amount: int = Field(strict=True, ge=1, le=MAX_INT)
    monthly_income: int = Field(strict=True, ge=0, le=MAX_INT)
    employment_months: int = Field(strict=True, ge=0, le=MAX_INT)
    external_score: int = Field(strict=True, ge=0, le=1000)
    product: Product


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: int
    monthly_income: int
    employment_months: int
    external_score: int
    product: Product
    status: Status
    rejection_reasons: list[Reason]
    created_at: datetime
    evaluated_at: datetime

    @field_validator("created_at", "evaluated_at")
    @classmethod
    def to_utc(cls, value: datetime) -> datetime:
        # SQLite returns naive datetimes (stored in UTC); Postgres returns aware ones.
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


class ListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown query parameter -> 422

    status: Status | None = None
    product: Product | None = None
    limit: int = Field(50, ge=1, le=100)
    offset: int = Field(0, ge=0, le=MAX_INT)
