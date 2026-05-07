"""Persistência de snapshots no SQLite.

Camada fina entre :class:`RoundSnapshot` (dataclass de domínio) e
:class:`RoundSnapshotORM` (modelo do SQLAlchemy). Mantida separada para
que os módulos analíticos não dependam do banco — eles operam em
:class:`RoundSnapshot` puros.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.database import SessionLocal
from app.logging_config import get_logger
from app.player_analytics.events import RoundSnapshot
from app.player_analytics.models import RoundSnapshotORM


logger = get_logger("player_analytics.storage")


def persist_snapshot(snapshot: RoundSnapshot) -> int:
    """Insere ou atualiza um snapshot. Idempotente por ``round_id``.

    Returns:
        Id da linha persistida (auto-incremento).
    """
    with SessionLocal() as session:
        existing = (
            session.query(RoundSnapshotORM)
            .filter(RoundSnapshotORM.round_id == snapshot.round_id)
            .one_or_none()
        )
        if existing is None:
            row = RoundSnapshotORM(
                round_id=snapshot.round_id,
                crash_multiplier=snapshot.crash_multiplier,
                started_at=snapshot.started_at,
                ended_at=snapshot.ended_at,
                player_count=snapshot.player_count,
                players_alive_at_crash=snapshot.players_alive_at_crash,
                cashed_out_count=snapshot.cashed_out_count,
                total_staked=snapshot.total_staked,
                total_paid_out=snapshot.total_paid_out,
            )
            row.set_cashouts(list(snapshot.cashout_multipliers))
            row.set_stakes(list(snapshot.stakes))
            session.add(row)
        else:
            # Atualiza in-place: pode acontecer se receberemos eventos
            # tardios após o crash já persistido.
            existing.crash_multiplier = snapshot.crash_multiplier
            existing.ended_at = snapshot.ended_at
            existing.player_count = snapshot.player_count
            existing.players_alive_at_crash = snapshot.players_alive_at_crash
            existing.cashed_out_count = snapshot.cashed_out_count
            existing.total_staked = snapshot.total_staked
            existing.total_paid_out = snapshot.total_paid_out
            existing.set_cashouts(list(snapshot.cashout_multipliers))
            existing.set_stakes(list(snapshot.stakes))
            row = existing
        session.commit()
        session.refresh(row)
        logger.info(
            "snapshot persistido",
            extra={"round_id": snapshot.round_id, "row_id": row.id},
        )
        return row.id


def load_recent_snapshots(limit: int = 50) -> list[RoundSnapshot]:
    """Carrega os últimos ``limit`` snapshots, mais recente primeiro."""
    with SessionLocal() as session:
        rows = (
            session.query(RoundSnapshotORM)
            .order_by(RoundSnapshotORM.ended_at.desc())
            .limit(limit)
            .all()
        )
    return [_to_domain(r) for r in rows]


def load_all_snapshots() -> list[RoundSnapshot]:
    with SessionLocal() as session:
        rows = (
            session.query(RoundSnapshotORM)
            .order_by(RoundSnapshotORM.ended_at.asc())
            .all()
        )
    return [_to_domain(r) for r in rows]


def _to_domain(row: RoundSnapshotORM) -> RoundSnapshot:
    return RoundSnapshot(
        round_id=row.round_id,
        crash_multiplier=row.crash_multiplier,
        started_at=row.started_at,
        ended_at=row.ended_at,
        player_count=row.player_count,
        players_alive_at_crash=row.players_alive_at_crash,
        cashed_out_count=row.cashed_out_count,
        total_staked=row.total_staked,
        total_paid_out=row.total_paid_out,
        cashout_multipliers=tuple(row.get_cashouts()),
        stakes=tuple(row.get_stakes()),
    )


def persist_many(snapshots: Iterable[RoundSnapshot]) -> int:
    """Helper para testes/imports em lote. Retorna o número persistido."""
    count = 0
    for s in snapshots:
        persist_snapshot(s)
        count += 1
    return count
