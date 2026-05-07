"""Fixtures compartilhadas para a suite de testes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def in_memory_db(monkeypatch):
    """Substitui ``SessionLocal`` por um engine SQLite em memória.

    Garante que cada teste rode contra um banco isolado, sem efeitos
    colaterais no arquivo ``data/aviator.db``.
    """
    from app import database as db_module
    from app.database import Base

    engine = create_engine("sqlite:///:memory:", future=True)
    TestSession = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )

    # Garante que os modelos estão registrados no Base.metadata.
    from app import models  # noqa: F401
    from app.player_analytics import models as pa_models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_module, "SessionLocal", TestSession)

    # Os módulos do coletor importam SessionLocal pelo nome diretamente,
    # então também precisamos sobrescrever lá.
    from app.collector import browser as browser_mod
    from app.collector import manual as manual_mod
    from app.collector import manager as manager_mod
    from app.player_analytics import storage as pa_storage

    monkeypatch.setattr(browser_mod, "SessionLocal", TestSession)
    monkeypatch.setattr(manual_mod, "SessionLocal", TestSession)
    monkeypatch.setattr(manager_mod, "SessionLocal", TestSession)
    monkeypatch.setattr(pa_storage, "SessionLocal", TestSession)

    yield TestSession


# ---------- Player Analytics fixtures ----------

def _build_snapshot(
    *,
    round_id: str = "r1",
    crash: float = 2.0,
    cashouts=None,
    stakes=None,
    player_count: int | None = None,
    alive: int | None = None,
    started_at: datetime | None = None,
):
    from app.player_analytics.events import RoundSnapshot

    cashouts = list(cashouts or [])
    stakes_list = list(stakes or [])
    if alive is None:
        alive = 0
    if player_count is None:
        player_count = len(cashouts) + alive
    started = started_at or datetime(2024, 1, 1, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=30)

    total_staked = sum(stakes_list) if stakes_list else None
    total_paid = (
        round(
            sum(
                c * (stakes_list[i] if i < len(stakes_list) else 1.0)
                for i, c in enumerate(cashouts)
            ),
            2,
        )
        if stakes_list
        else None
    )

    return RoundSnapshot(
        round_id=round_id,
        crash_multiplier=crash,
        started_at=started,
        ended_at=ended,
        player_count=player_count,
        players_alive_at_crash=alive,
        cashed_out_count=len(cashouts),
        total_staked=total_staked,
        total_paid_out=total_paid,
        cashout_multipliers=tuple(sorted(cashouts)),
        stakes=tuple(sorted(stakes_list)),
    )


@pytest.fixture
def make_snapshot():
    """Factory para construir snapshots ad-hoc nos testes."""
    return _build_snapshot


@pytest.fixture
def sample_snapshot():
    return _build_snapshot(
        round_id="sample",
        crash=3.50,
        cashouts=[1.10, 1.20, 1.50, 1.50, 2.00, 2.50, 3.00],
        alive=3,
        stakes=[5.0, 10.0, 10.0, 10.0, 20.0, 20.0, 50.0, 5.0, 10.0, 10.0],
    )
