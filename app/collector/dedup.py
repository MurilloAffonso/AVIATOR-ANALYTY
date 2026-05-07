"""Deduplicação por sequência para o coletor ao vivo.

A correção do bug original: o coletor antigo deduplica por *valor*
(``set[float]``), o que silenciosamente descarta multiplicadores baixos
repetidos (1.00x, 1.50x, etc.) depois que aparecem pela primeira vez.

Aqui usamos alinhamento de janelas: comparamos a janela visível anterior
com a atual e identificamos só o que entrou de novo no fim da janela,
sem depender da unicidade dos valores.
"""

from __future__ import annotations

from collections.abc import Sequence


def find_new_items(
    previous: Sequence[float],
    current: Sequence[float],
    *,
    tolerance: float = 1e-9,
) -> list[float]:
    """Retorna os itens de ``current`` que ainda não estavam em ``previous``.

    Ambas as sequências devem estar em ordem cronológica (mais antigo
    primeiro, mais recente por último) e representam janelas sobrepostas
    do mesmo fluxo subjacente — por exemplo, a barra de histórico visível
    de uma roda do Aviator.

    Estratégia: encontrar o maior ``k`` tal que ``previous[-k:]`` seja
    igual a ``current[:k]``. Tudo em ``current`` depois desse ponto de
    sobreposição é o que entrou de novo.

    Se nenhuma sobreposição for encontrada (o polling perdeu rodadas
    suficientes para as janelas não compartilharem mais cauda/início),
    a janela inteira de ``current`` é tratada como nova. Esse é o
    fallback mais seguro: pode super-reportar algumas rodadas em casos
    raros, mas nunca *descarta dados silenciosamente*, que é o bug
    que estamos consertando.

    Examples
    --------
    >>> find_new_items([1.0, 2.5, 1.5, 3.2, 1.1], [2.5, 1.5, 3.2, 1.1, 7.8])
    [7.8]
    >>> find_new_items([1.0, 2.5, 1.5, 3.2, 1.1], [1.5, 3.2, 1.1, 7.8, 9.9])
    [7.8, 9.9]
    >>> find_new_items([], [1.0, 2.5])
    [1.0, 2.5]
    >>> find_new_items([1.0, 2.5], [1.0, 2.5])
    []
    """
    if not current:
        return []
    if not previous:
        return list(current)

    prev = list(previous)
    curr = list(current)

    max_k = min(len(prev), len(curr))
    for k in range(max_k, 0, -1):
        if _all_close(prev[-k:], curr[:k], tolerance):
            return curr[k:]

    # Sem sobreposição detectável: tratar tudo como novo.
    return curr


def _all_close(a: list[float], b: list[float], tolerance: float) -> bool:
    if len(a) != len(b):
        return False
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))
