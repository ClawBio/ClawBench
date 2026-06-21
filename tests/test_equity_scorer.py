"""TDD for the ancestry-equity scorer (the ClawBio equity-scorer instrument, Exp 2).

GIAB spans three ancestries (HG001 EUR; HG002/HG003 AJ; HG005 EAS). A trustworthy calling pipeline
should achieve accuracy that does not depend on ancestry. The scorer summarises per-sample F1 by
ancestry and flags inequity when the cross-ancestry spread exceeds a tolerance.
"""
from __future__ import annotations

import equity_scorer as EQ


_BY_SAMPLE = {
    "HG001": {"ancestry": "EUR", "f1": 0.9960},
    "HG002": {"ancestry": "AJ", "f1": 0.9955},
    "HG003": {"ancestry": "AJ", "f1": 0.9945},
    "HG005": {"ancestry": "EAS", "f1": 0.9930},
}


def test_per_ancestry_means():
    r = EQ.equity(_BY_SAMPLE)
    assert abs(r["by_ancestry"]["AJ"] - 0.9950) < 1e-9   # mean of HG002, HG003
    assert abs(r["by_ancestry"]["EUR"] - 0.9960) < 1e-9
    assert abs(r["by_ancestry"]["EAS"] - 0.9930) < 1e-9


def test_spread_and_invariance_flag():
    r = EQ.equity(_BY_SAMPLE, tolerance=0.01)
    assert abs(r["spread"] - (0.9960 - 0.9930)) < 1e-6   # max - min ancestry mean
    assert r["equitable"] is True                         # 0.003 < 0.01


def test_inequity_detected_when_one_ancestry_lags():
    by = dict(_BY_SAMPLE)
    by["HG005"] = {"ancestry": "EAS", "f1": 0.93}         # EAS lags badly
    r = EQ.equity(by, tolerance=0.01)
    assert r["equitable"] is False
    assert r["worst_ancestry"] == "EAS"
    assert r["spread"] > 0.06


def test_requires_at_least_two_ancestries():
    one = {"HG001": {"ancestry": "EUR", "f1": 0.99}}
    try:
        EQ.equity(one)
        assert False, "expected a single-ancestry guard"
    except ValueError as e:
        assert "ancestr" in str(e).lower()
