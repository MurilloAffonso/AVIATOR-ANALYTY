"""Contrato base para coletores ao vivo.

Todo coletor é estritamente *somente leitura*: observa o jogo, mas
nunca emite ações financeiras (apostas, cashout, mudança de stake, etc.).
Esta restrição é validada em testes e está reforçada na docstring de
cada subclasse.

Coletores não persistem dados diretamente. Eles publicam multiplicadores
brutos numa ``asyncio.Queue`` e o ``CollectorManager`` cuida da
deduplicação e persistência.
"""

from __future__ import annotations

import abc
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.logging_config import get_logger


@dataclass(frozen=True)
class CollectorEvent:
    """Pacote de multiplicadores observados, com metadados de origem.

    Attributes:
        source: Identificador legível do coletor (e.g. ``"dom"``, ``"ws"``).
        multipliers: Lista bruta extraída neste ciclo, em ordem cronológica.
        observed_at: Timestamp UTC do momento da extração.
    """

    source: str
    multipliers: list[float]
    observed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class BaseCollector(abc.ABC):
    """Interface abstrata para coletores de multiplicadores.

    Cada subclasse implementa ``run_async`` numa lógica de produção
    contínua que publica :class:`CollectorEvent` na fila recebida.

    Subclasses *não* devem:
    - clicar, digitar, navegar para páginas de aposta;
    - enviar frames WebSocket;
    - escrever no banco de dados;
    - tomar qualquer decisão financeira.

    Subclasses *devem*:
    - ler dados visíveis ou frames recebidos;
    - publicar eventos na fila;
    - respeitar ``self._stop_event``.
    """

    name: str = "base"

    def __init__(self) -> None:
        self._stop_event = asyncio.Event()
        self._logger = get_logger(f"collector.{self.name}")

    def request_stop(self) -> None:
        """Sinaliza ao coletor que ele deve encerrar no próximo ciclo."""
        self._stop_event.set()

    @property
    def is_stopped(self) -> bool:
        return self._stop_event.is_set()

    @abc.abstractmethod
    async def run_async(self, queue: "asyncio.Queue[CollectorEvent]") -> None:
        """Loop principal do coletor. Deve respeitar ``self._stop_event``.

        Implementações *devem* publicar eventos na ``queue`` sempre que
        observarem multiplicadores novos. *Não* devem persistir nem
        deduplicar — isso é responsabilidade do manager.
        """

    async def emit(
        self,
        queue: "asyncio.Queue[CollectorEvent]",
        multipliers: list[float],
    ) -> None:
        """Helper para publicar um evento na fila."""
        if not multipliers:
            return
        event = CollectorEvent(source=self.name, multipliers=list(multipliers))
        await queue.put(event)
        self._logger.debug(
            "evento publicado: source=%s, n=%d", event.source, len(event.multipliers)
        )
