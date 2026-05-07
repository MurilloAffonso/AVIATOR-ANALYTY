"""Testes da deduplicação por sequência.

O teste-chave aqui é ``test_repeated_low_value_not_dropped``: ele cobre
exatamente o bug que o coletor antigo tinha — multiplicadores baixos
repetidos eram silenciosamente descartados pelo dedup-por-valor.
"""

from app.collector.dedup import find_new_items


def test_no_previous_returns_all_current():
    assert find_new_items([], [1.0, 2.5, 3.0]) == [1.0, 2.5, 3.0]


def test_empty_current_returns_empty():
    assert find_new_items([1.0, 2.0], []) == []


def test_identical_windows_returns_empty():
    window = [1.0, 2.5, 1.5, 3.2, 1.1]
    assert find_new_items(window, window) == []


def test_one_new_at_end():
    prev = [1.0, 2.5, 1.5, 3.2, 1.1]
    curr = [2.5, 1.5, 3.2, 1.1, 7.8]
    assert find_new_items(prev, curr) == [7.8]


def test_two_new_at_end():
    prev = [1.0, 2.5, 1.5, 3.2, 1.1]
    curr = [1.5, 3.2, 1.1, 7.8, 9.9]
    assert find_new_items(prev, curr) == [7.8, 9.9]


def test_no_overlap_treats_all_as_new():
    """Quando o polling perde rodadas suficientes para não haver overlap,
    devolvemos a janela inteira (preferimos super-reportar a perder dados)."""
    prev = [1.0, 2.5, 1.5]
    curr = [4.5, 7.8, 9.9]
    assert find_new_items(prev, curr) == [4.5, 7.8, 9.9]


def test_repeated_low_value_not_dropped():
    """Regressão do bug original: 1.00x repetido nunca pode ser descartado."""
    prev = [1.00, 1.00, 1.00, 1.00, 1.50]
    curr = [1.00, 1.00, 1.00, 1.50, 1.00]
    # Sliding por 1: prev[-4:] == curr[:4] -> True. Novo: [1.00].
    assert find_new_items(prev, curr) == [1.00]


def test_all_same_value_short_window():
    assert find_new_items([1.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0]) == [1.0]


def test_tolerance_handles_floating_point_noise():
    prev = [1.0, 2.5]
    curr = [1.0 + 1e-12, 2.5, 3.7]
    assert find_new_items(prev, curr) == [3.7]


def test_two_polls_simulation_no_double_counting():
    poll1 = [1.5, 2.0, 1.1, 3.4]
    poll2 = [2.0, 1.1, 3.4, 5.5]

    new1 = find_new_items([], poll1)
    assert new1 == poll1

    new2 = find_new_items(poll1, poll2)
    assert new2 == [5.5]


def test_full_window_replaced_treated_as_new():
    """Janela inteiramente diferente (ex.: poll após 30 minutos parado):
    todo o conteúdo é tratado como novo."""
    prev = [1.0, 1.5, 2.0]
    curr = [3.0, 4.0, 5.0]
    assert find_new_items(prev, curr) == [3.0, 4.0, 5.0]


def test_partial_match_inside_window():
    """Se houver uma cauda comum ainda que pequena, ela deve ser detectada."""
    prev = [9.0, 8.0, 7.0, 1.5]
    curr = [1.5, 2.0, 3.0]
    # prev[-1:] == curr[:1] -> True
    assert find_new_items(prev, curr) == [2.0, 3.0]
