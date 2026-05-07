"""Modelos persistidos do Player Analytics Engine.

Apenas agregados anônimos por rodada. Nenhum dado de jogador individual.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RoundSnapshotORM(Base):
    """Snapshot por rodada. Uma linha = uma rodada finalizada.

    ``cashout_multipliers_json`` e ``stakes_json`` armazenam listas
    serializadas. Mantemos como JSON em vez de tabela filha porque o
    consumo é sempre "ler tudo de uma rodada de uma vez" para análise
    estatística — joins seriam overhead sem benefício.
    """

    __tablename__ = "player_round_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    round_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, unique=True)
    crash_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)

    player_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    players_alive_at_crash: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cashed_out_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    total_staked: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_paid_out: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    cashout_multipliers_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    stakes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # ----- helpers de serialização -----

    def set_cashouts(self, values: list[float]) -> None:
        self.cashout_multipliers_json = json.dumps(values)

    def get_cashouts(self) -> list[float]:
        return json.loads(self.cashout_multipliers_json or "[]")

    def set_stakes(self, values: list[float]) -> None:
        self.stakes_json = json.dumps(values)

    def get_stakes(self) -> list[float]:
        return json.loads(self.stakes_json or "[]")
