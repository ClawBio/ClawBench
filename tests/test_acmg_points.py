"""TDD for the Tavtigian/ClinGen Bayesian points combiner.

Point magnitudes (Tavtigian et al. 2018/2020): very_strong=8, strong=4, moderate=2, supporting=1,
stand_alone=8; benign codes are negative. Class bins: P>=10, LP 6-9, VUS 0-5, LB -1..-6, B<=-7.
Direction is taken from the canonical vocabulary, never the model.
"""
from __future__ import annotations

import acmg_points as P


def test_points_for_pathogenic():
    assert P.points_for("PVS1", "very_strong") == 8
    assert P.points_for("PS1", "strong") == 4
    assert P.points_for("PM2", "moderate") == 2
    assert P.points_for("PP3", "supporting") == 1


def test_points_for_benign_is_negative():
    assert P.points_for("BA1", "stand_alone") == -8
    assert P.points_for("BS1", "strong") == -4
    assert P.points_for("BP4", "supporting") == -1


def test_classify_points_bins():
    assert P.classify_points(10) == "Pathogenic"
    assert P.classify_points(12) == "Pathogenic"
    assert P.classify_points(9) == "Likely Pathogenic"
    assert P.classify_points(6) == "Likely Pathogenic"
    assert P.classify_points(5) == "Uncertain Significance"
    assert P.classify_points(0) == "Uncertain Significance"
    assert P.classify_points(-1) == "Likely Benign"
    assert P.classify_points(-6) == "Likely Benign"
    assert P.classify_points(-7) == "Benign"


def test_classify_codes_lof_reaches_pathogenic():
    # the crux: PVS1 + PM2 = 10 = Pathogenic under points, but only Likely Pathogenic under Richards rules
    cls, total = P.classify_codes([{"code": "PVS1", "strength": "very_strong"},
                                   {"code": "PM2", "strength": "moderate"}])
    assert total == 10 and cls == "Pathogenic"


def test_classify_codes_pvs1_alone_is_lp():
    cls, total = P.classify_codes([{"code": "PVS1", "strength": "very_strong"}])
    assert total == 8 and cls == "Likely Pathogenic"


def test_classify_codes_pm2_alone_is_vus():
    cls, total = P.classify_codes([{"code": "PM2", "strength": "moderate"}])
    assert total == 2 and cls == "Uncertain Significance"


def test_classify_codes_ba1_is_benign():
    cls, total = P.classify_codes([{"code": "BA1", "strength": "stand_alone"}])
    assert total == -8 and cls == "Benign"


def test_unknown_code_or_strength_contributes_zero():
    assert P.points_for("ZZ9", "moderate") == 0
    assert P.points_for("PM2", "bogus") == 0
