"""Testes de distribuição emocional e exit heatmap."""

from __future__ import annotations

from app.player_analytics.psychology import (
    emotion_distribution,
    exit_heatmap,
)


def test_emotion_distribution_basic(make_snapshot):
    snap = make_snapshot(
        crash=10.0,
        cashouts=[1.10, 1.50, 1.90, 4.00, 9.00],  # um por bin
        alive=2,
    )
    dist = emotion_distribution(snap)
    assert dist.by_category["medo"] == 1
    assert dist.by_category["cautela"] == 1
    assert dist.by_category["equilibrio"] == 1
    assert dist.by_category["ambicao"] == 1
    assert dist.by_category["euforia"] == 1
    assert dist.crashed == 2
    assert dist.total_players == 7


def test_emotion_fractions_sum_to_one(make_snapshot):
    snap = make_snapshot(
        crash=3.0,
        cashouts=[1.20, 1.40, 2.00, 2.50],
        alive=1,
    )
    dist = emotion_distribution(snap)
    fracs = dist.fractions()
    assert abs(sum(fracs.values()) - 1.0) < 1e-9


def test_emotion_empty_round(make_snapshot):
    snap = make_snapshot(player_count=0, cashouts=[], alive=0)
    dist = emotion_distribution(snap)
    assert dist.fractions() == {}


def test_emotion_only_crashes(make_snapshot):
    snap = make_snapshot(crash=1.05, cashouts=[], alive=10)
    dist = emotion_distribution(snap)
    assert all(v == 0 for v in dist.by_category.values())
    assert dist.fractions()["queimou"] == 1.0


# ---------- heatmap ----------

def test_heatmap_aggregates_across_rounds(make_snapshot):
    s1 = make_snapshot(round_id="a", crash=3.0, cashouts=[1.10, 1.30, 2.50])
    s2 = make_snapshot(round_id="b", crash=3.0, cashouts=[1.10, 1.50, 2.50])
    cells = exit_heatmap([s1, s2], bin_width=0.20, max_multiplier=3.0)

    # Faixa 1.00-1.20: dois cashouts (1.10 e 1.10)
    cell_1_00 = next(c for c in cells if c.multiplier_lo == 1.00)
    assert cell_1_00.count == 2

    # Faixa 1.20-1.40: 1 (1.30)
    cell_1_20 = next(c for c in cells if c.multiplier_lo == 1.20)
    assert cell_1_20.count == 1

    # Faixa 1.40-1.60: 1 (1.50)
    cell_1_40 = next(c for c in cells if c.multiplier_lo == 1.40)
    assert cell_1_40.count == 1


def test_heatmap_top_bin_catches_overflow(make_snapshot):
    snap = make_snapshot(crash=100.0, cashouts=[50.0, 80.0])
    cells = exit_heatmap([snap], bin_width=1.0, max_multiplier=10.0)
    # Os dois cashouts altos caem na última bin
    assert cells[-1].count == 2


def test_heatmap_skips_below_one(make_snapshot):
    """Nenhum cashout pode ser < 1.0 por construção do parser, mas
    se aparecer, não deve criar bin abaixo da grade."""
    snap = make_snapshot(crash=2.0, cashouts=[1.5, 1.7])
    cells = exit_heatmap([snap], bin_width=0.5, max_multiplier=3.0)
    # Soma dos counts == número de cashouts
    assert sum(c.count for c in cells) == 2
