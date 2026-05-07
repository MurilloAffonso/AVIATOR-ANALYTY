"""Eventos do domínio Player Analytics.

Estes dataclasses são a interface entre os coletores (DOM/WS) e o
pipeline analítico. **Nada aqui contém PII de jogadores.** O máximo
que recebemos é um identificador anônimo opaco (hash já pré-computado
pelo coletor) usado apenas para:

- distinguir jogadores únicos *dentro de uma rodada* (count distinto);
- detectar duplicatas vindas de DOM e WS na mesma rodada.

O identificador *não* é persistido. Após o snapshot por rodada ser
agregado, os IDs são descartados.

Campos opcionais existem porque diferentes cassinos expõem subconjuntos
diferentes via WS/DOM. A engine degrada graciosamente: se ``stake`` é
``None``, os módulos de liquidez/whales simplesmente não computam
métricas que dependem dele.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class EventKind(str, Enum):
    """Tipos de evento que o pipeline reconhece."""

    ROUND_START = "round_start"
    BET_PLACED = "bet_placed"
    CASHOUT = "cashout"
    ROUND_CRASH = "round_crash"


@dataclass(frozen=True)
class RoundEvent:
    """Marco de início ou fim de uma rodada.

    Para ``ROUND_CRASH``, ``crash_multiplier`` é obrigatório.
    """

    kind: EventKind
    round_id: str
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    crash_multiplier: Optional[float] = None


@dataclass(frozen=True)
class PlayerEvent:
    """Ação de um jogador anônimo dentro de uma rodada.

    Attributes:
        kind: ``BET_PLACED`` ou ``CASHOUT``.
        round_id: identificador da rodada à qual o evento pertence.
        anon_id: hash opaco do jogador (descartado após o snapshot).
        stake: valor apostado (apenas em ``BET_PLACED``).
        cashout_multiplier: multiplicador no qual fez cashout
            (apenas em ``CASHOUT``).
        payout: ``stake * cashout_multiplier`` (apenas em ``CASHOUT``).
        occurred_at: timestamp UTC.
    """

    kind: EventKind
    round_id: str
    anon_id: str
    stake: Optional[float] = None
    cashout_multiplier: Optional[float] = None
    payout: Optional[float] = None
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass(frozen=True)
class RoundSnapshot:
    """Resumo agregado de uma rodada — única coisa que persistimos.

    Não contém IDs de jogadores. Apenas estatísticas agregadas.
    """

    round_id: str
    crash_multiplier: float
    started_at: datetime
    ended_at: datetime

    # Contagens
    player_count: int             # total que apostou na rodada
    players_alive_at_crash: int   # apostaram e não fizeram cashout antes do crash
    cashed_out_count: int         # = player_count - players_alive_at_crash

    # Volumes (None se o coletor não expõe stake)
    total_staked: Optional[float] = None
    total_paid_out: Optional[float] = None

    # Distribuição de cashouts (lista crua p/ módulos analíticos)
    cashout_multipliers: tuple[float, ...] = ()

    # Distribuição de stakes (lista crua p/ módulos de liquidez/whales)
    stakes: tuple[float, ...] = ()

    @property
    def survival_rate(self) -> float:
        """Fração que sobreviveu ao crash (perdeu)."""
        if self.player_count == 0:
            return 0.0
        return self.players_alive_at_crash / self.player_count

    @property
    def cashout_rate(self) -> float:
        """Fração que fez cashout antes do crash."""
        return 1.0 - self.survival_rate
