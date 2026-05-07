from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    """Default timezone-aware para ``created_at``.

    Substitui ``datetime.utcnow`` (deprecated em Python 3.12+).
    """
    return datetime.now(timezone.utc)


class RoundResult(Base):
    __tablename__ = "round_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )
