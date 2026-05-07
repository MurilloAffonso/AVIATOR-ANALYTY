"""Pipeline que agrega eventos por rodada e produz snapshots.

Modelo: receba uma sequência (síncrona ou assíncrona) de
:class:`RoundEvent` e :class:`PlayerEvent`. O pipeline mantém estado
in-memory por rodada aberta. Quando um ``ROUND_CRASH`` chega, fecha o
snapshot, dispara callback opcional de persistência e libera memória.

Garantias:

- Anon IDs são usados apenas para deduplicação dentro de uma rodada
  (mesmo jogador chegando por DOM e WS) e descartados ao fechar.
- Nenhum dado individual sai do pipeline. Apenas
  :class:`RoundSnapshot` (agregados) é emitido.
- Tolerante a fora-de-ordem: cashout antes de bet_placed (ou mesmo
  antes de round_start) é aceito; a rodada é criada lazily.

Não toma decisões financeiras. Não reage a sinais de mercado.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.logging_config import get_logger
from app.player_analytics.events import (
    EventKind,
    PlayerEvent,
    RoundEvent,
    RoundSnapshot,
)


logger = get_logger("player_analytics.pipeline")


@dataclass
class _RoundBuffer:
    """Estado mutável de uma rodada em andamento (interno ao pipeline)."""

    round_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    bets: dict[str, float] = field(default_factory=dict)         # anon_id -> stake
    bets_no_amount: set[str] = field(default_factory=set)        # anon_id sem stake
    cashouts: dict[str, tuple[float, Optional[float]]] = field(default_factory=dict)
    # cashouts: anon_id -> (multiplier, payout_or_None)

    def players_seen(self) -> set[str]:
        return set(self.bets.keys()) | self.bets_no_amount | set(self.cashouts.keys())


SnapshotCallback = Callable[[RoundSnapshot], None]


class PlayerEventPipeline:
    """Consome eventos e emite :class:`RoundSnapshot` por rodada fechada.

    Usar como:

        pipeline = PlayerEventPipeline(on_snapshot=lambda s: persist(s))
        pipeline.handle_round(round_event)
        pipeline.handle_player(player_event)
        ...

    Ou em batch::

        pipeline.feed(events)

    Args:
        on_snapshot: callback chamado a cada rodada finalizada.
            Padrão: apenas loga.
        max_open_rounds: limite defensivo. Se exceder, descarta as
            rodadas mais antigas (sinal de coleta degenerada).
    """

    def __init__(
        self,
        on_snapshot: Optional[SnapshotCallback] = None,
        max_open_rounds: int = 10,
    ) -> None:
        self._open: dict[str, _RoundBuffer] = {}
        self._on_snapshot = on_snapshot or self._default_callback
        self._max_open = max_open_rounds

    # ---------- API pública ----------

    def feed(self, events: Iterable[object]) -> list[RoundSnapshot]:
        """Aceita uma mistura de RoundEvent e PlayerEvent.

        Útil para testes e para drenar lotes vindos da fila.
        """
        emitted: list[RoundSnapshot] = []
        for ev in events:
            snap = self.handle(ev)
            if snap is not None:
                emitted.append(snap)
        return emitted

    def handle(self, event: object) -> Optional[RoundSnapshot]:
        if isinstance(event, RoundEvent):
            return self.handle_round(event)
        if isinstance(event, PlayerEvent):
            return self.handle_player(event)
        logger.debug("evento ignorado (tipo desconhecido): %r", type(event).__name__)
        return None

    def handle_round(self, event: RoundEvent) -> Optional[RoundSnapshot]:
        if event.kind is EventKind.ROUND_START:
            self._ensure(event.round_id, event.occurred_at)
            return None

        if event.kind is EventKind.ROUND_CRASH:
            return self._close(event)

        logger.debug("RoundEvent kind inesperado: %s", event.kind)
        return None

    def handle_player(self, event: PlayerEvent) -> Optional[RoundSnapshot]:
        buf = self._ensure(event.round_id, event.occurred_at)

        if event.kind is EventKind.BET_PLACED:
            if event.stake is not None and event.stake > 0:
                buf.bets[event.anon_id] = event.stake
                buf.bets_no_amount.discard(event.anon_id)
            else:
                # Cassino expôs aposta mas não o valor — ainda contamos.
                if event.anon_id not in buf.bets:
                    buf.bets_no_amount.add(event.anon_id)
            return None

        if event.kind is EventKind.CASHOUT:
            if event.cashout_multiplier is None:
                logger.debug("cashout sem multiplicador, ignorando")
                return None
            buf.cashouts[event.anon_id] = (event.cashout_multiplier, event.payout)
            return None

        logger.debug("PlayerEvent kind inesperado: %s", event.kind)
        return None

    # ---------- internos ----------

    def _ensure(self, round_id: str, ts: datetime) -> _RoundBuffer:
        if round_id in self._open:
            return self._open[round_id]
        if len(self._open) >= self._max_open:
            # Descarta a mais antiga.
            oldest = min(self._open.values(), key=lambda b: b.started_at)
            logger.warning(
                "limite de rodadas abertas atingido; descartando %s",
                oldest.round_id,
            )
            del self._open[oldest.round_id]
        buf = _RoundBuffer(round_id=round_id, started_at=ts)
        self._open[round_id] = buf
        return buf

    def _close(self, crash_event: RoundEvent) -> Optional[RoundSnapshot]:
        if crash_event.crash_multiplier is None:
            logger.warning("ROUND_CRASH sem crash_multiplier; descartando")
            self._open.pop(crash_event.round_id, None)
            return None

        buf = self._open.pop(crash_event.round_id, None)
        if buf is None:
            logger.debug(
                "ROUND_CRASH sem rodada aberta (round_id=%s); ignorando",
                crash_event.round_id,
            )
            return None

        snapshot = self._build_snapshot(buf, crash_event)
        try:
            self._on_snapshot(snapshot)
        except Exception:  # noqa: BLE001
            logger.exception("on_snapshot callback falhou")
        return snapshot

    def _build_snapshot(
        self, buf: _RoundBuffer, crash_event: RoundEvent
    ) -> RoundSnapshot:
        all_players = buf.players_seen()
        cashed_players = set(buf.cashouts.keys()) & all_players
        alive_players = all_players - cashed_players

        # Filtra cashouts de jogadores válidos (devem ter aparecido na rodada).
        cashout_multipliers = tuple(
            sorted(m for (m, _p) in buf.cashouts.values())
        )

        stakes = tuple(sorted(buf.bets.values())) if buf.bets else ()
        total_staked: Optional[float] = sum(stakes) if stakes else None

        # Total payout: usa payouts explícitos quando temos, senão
        # reconstrói a partir de stake * multiplier quando ambos existem.
        total_payout: Optional[float] = None
        if buf.cashouts:
            total = 0.0
            saw_any = False
            for anon_id, (mult, payout) in buf.cashouts.items():
                if payout is not None:
                    total += payout
                    saw_any = True
                elif anon_id in buf.bets:
                    total += buf.bets[anon_id] * mult
                    saw_any = True
            if saw_any:
                total_payout = round(total, 2)

        return RoundSnapshot(
            round_id=buf.round_id,
            crash_multiplier=crash_event.crash_multiplier,
            started_at=buf.started_at,
            ended_at=crash_event.occurred_at,
            player_count=len(all_players),
            players_alive_at_crash=len(alive_players),
            cashed_out_count=len(cashed_players),
            total_staked=round(total_staked, 2) if total_staked is not None else None,
            total_paid_out=total_payout,
            cashout_multipliers=cashout_multipliers,
            stakes=stakes,
        )

    def _default_callback(self, snapshot: RoundSnapshot) -> None:
        logger.info(
            "snapshot fechado",
            extra={
                "round_id": snapshot.round_id,
                "player_count": snapshot.player_count,
                "alive_at_crash": snapshot.players_alive_at_crash,
                "crash_multiplier": snapshot.crash_multiplier,
            },
        )
