from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    monthly_income: Mapped[int] = mapped_column(BigInteger)
    employment_months: Mapped[int] = mapped_column(BigInteger)
    external_score: Mapped[int]
    product: Mapped[str]
    # status, rejection_reasons and evaluated_at copy the current (highest id)
    # evaluation, so reads and filters use this table only.
    status: Mapped[str]
    rejection_reasons: Mapped[list[dict[str, str]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Evaluation(Base):
    """Append-only history: rows are inserted, never updated or deleted."""

    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"))
    status: Mapped[str]
    rejection_reasons: Mapped[list[dict[str, str]]] = mapped_column(JSON)
    policy: Mapped[dict[str, str | int]] = mapped_column(JSON)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    application: Mapped[Application] = relationship()
