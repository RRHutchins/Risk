"""Tests for scoring, expected value and Monte Carlo simulation (Stage 4).

The hand-checked example (test_hand_checked_example) is worked through in the
comments so that a reader can confirm every figure with a calculator.
"""

import numpy as np
import pytest

from risk_engine.calculate import (SimulationSettings, _normal_cdf, calculate, impact_score, probability,
                                   rating, score_record, simulate)
from risk_engine.config import load_settings
from risk_engine.packs import load_pack

PACK = load_pack("construction_tender").config


def rec(id, likelihood, low, likely, high, type="threat", group="", flags=None):
    return {"id": id, "title": id, "type": type, "likelihood": likelihood, "impact_min": low,
            "impact_likely": likely, "impact_max": high, "correlation_group": group, "flags": flags or []}


def settings(**sim):
    s = load_settings()
    s["simulation"].update(sim)
    return s


# ----- scoring ------------------------------------------------------------

@pytest.mark.parametrize("likelihood,p", [(1, 0.03), (2, 0.10), (3, 0.25), (4, 0.45), (5, 0.75)])
def test_probability_is_band_midpoint(likelihood, p):
    assert probability(likelihood, PACK) == p


@pytest.mark.parametrize("pct,score", [(0.0, 1), (0.49, 1), (0.5, 2), (0.99, 2), (1.0, 3), (2.99, 3),
                                       (3.0, 4), (6.99, 4), (7.0, 5), (40, 5), (-2.0, 3)])
def test_impact_bands(pct, score):
    assert impact_score(pct, PACK) == score


@pytest.mark.parametrize("score,colour", [(25, "red"), (15, "red"), (14, "amber"), (8, "amber"),
                                          (7, "green"), (1, "green")])
def test_rating_thresholds(score, colour):
    assert rating(score, [], PACK) == colour


def test_uncapped_flags_force_red():
    assert rating(2, ["uncapped_liability"], PACK) == "red"
    assert rating(2, ["uncapped_delay_damages"], PACK) == "red"
    r = score_record(rec("A", 1, 0.1, 0.2, 0.3, flags=["uncapped_liability"]), PACK)
    assert r["score"] == 1 and r["rating"] == "red" and r["rating_overridden"]


def test_score_and_expected_value():
    r = score_record(rec("A", 4, 1.0, 2.0, 6.0), PACK)       # likely 2% -> impact band 3
    assert (r["probability"], r["impact_score"], r["score"], r["rating"]) == (0.45, 3, 12, "amber")
    assert r["expected_value_pct"] == pytest.approx(0.45 * 2.0)
    o = score_record(rec("B", 3, 0.1, 0.5, 1.5, type="opportunity"), PACK)
    assert o["expected_value_pct"] == pytest.approx(-0.25 * 0.5)  # opportunities are negative


# ----- the hand-checked example ---------------------------------------------

def test_hand_checked_example():
    """Two independent threats with fixed impacts on a GBP 1,000,000 contract.

      A: likelihood 3 -> p = 0.25, impact exactly 2%   (GBP 20,000)
      B: likelihood 2 -> p = 0.10, impact exactly 5%   (GBP 50,000)

    Expected value = 0.25 x 2 + 0.10 x 5 = 0.5 + 0.5 = 1.0%  (GBP 10,000)

    Possible totals and their chances:
      neither     0%   0.75 x 0.90 = 0.675
      A only      2%   0.25 x 0.90 = 0.225   (running total 0.900)
      B only      5%   0.75 x 0.10 = 0.075   (running total 0.975)
      both        7%   0.25 x 0.10 = 0.025   (running total 1.000)

    So P50 = 0% (below 0.675), P80 = 2% (between 0.675 and 0.900),
    P95 = 5% (between 0.900 and 0.975), P99 = 7%, mean = 1.0%.
    """
    s = settings(iterations=200_000, percentiles=[50, 80, 95, 99])
    out = calculate([rec("A", 3, 2, 2, 2), rec("B", 2, 5, 5, 5)], PACK, s, base_value=1_000_000)
    assert out["expected_value"]["net_pct"] == pytest.approx(1.0)
    assert out["expected_value"]["net_money"] == pytest.approx(10_000)
    c = out["contingency"]
    assert c["P50"]["pct"] == 0.0
    assert c["P80"]["pct"] == pytest.approx(2.0)
    assert c["P80"]["money"] == pytest.approx(20_000)
    assert c["P95"]["pct"] == pytest.approx(5.0)
    assert c["P99"]["pct"] == pytest.approx(7.0)
    assert c["mean"]["pct"] == pytest.approx(1.0, abs=0.02)           # simulation error only
    occ = {x["id"]: x["occurrence_rate"] for x in out["simulation"]["contributions"]}
    assert occ["A"] == pytest.approx(0.25, abs=0.005) and occ["B"] == pytest.approx(0.10, abs=0.005)


def test_opportunity_reduces_the_total():
    s = settings(iterations=50_000)
    threat_only = calculate([rec("A", 5, 4, 4, 4)], PACK, s)
    both = calculate([rec("A", 5, 4, 4, 4), rec("O", 5, 1, 1, 1, type="opportunity")], PACK, s)
    assert both["expected_value"]["net_pct"] == pytest.approx(0.75 * 4 - 0.75 * 1)
    assert both["contingency"]["mean"]["pct"] < threat_only["contingency"]["mean"]["pct"]


# ----- distributions and correlation --------------------------------------------

def test_pert_mean_matches_formula():
    """A PERT on (1, 2, 6) has mean (1 + 4x2 + 6) / 6 = 2.5. With p = 0.75 the
    risk's simulated mean is 0.75 x 2.5 = 1.875."""
    s = SimulationSettings(iterations=200_000)
    out = simulate([score_record(rec("A", 5, 1, 2, 6), PACK)], s)
    assert out["mean_pct"] == pytest.approx(1.875, rel=0.01)
    lo = min(c["value_pct"] for c in out["curve_pct"] if c["value_pct"] > 0)
    assert lo >= 1.0 and out["curve_pct"][-1]["value_pct"] <= 6.0


def test_triangular_option():
    s = SimulationSettings(iterations=200_000, distribution="triangular")
    out = simulate([score_record(rec("A", 5, 1, 2, 6), PACK)], s)
    assert out["mean_pct"] == pytest.approx(0.75 * 3.0, rel=0.01)   # triangular mean (1+2+6)/3 = 3


def test_correlated_risks_occur_together_more_often():
    a, b = rec("A", 3, 1, 1, 1, group="ground"), rec("B", 3, 1, 1, 1, group="ground")
    records = [score_record(r, PACK) for r in (a, b)]
    together = simulate(records, SimulationSettings(iterations=100_000, correlation_in_group=0.5))
    apart = simulate(records, SimulationSettings(iterations=100_000, correlation_in_group=0.0))
    # both at once (total 2%): independent 0.25 x 0.25 = 0.0625; correlated is higher
    def share_both(out):
        return 1 - next(c["percentile"] for c in out["curve_pct"] if c["value_pct"] >= 2) / 100
    assert share_both(apart) == pytest.approx(0.0625, abs=0.015)
    assert share_both(together) > 0.09
    assert together["mean_pct"] == pytest.approx(apart["mean_pct"], abs=0.02)   # means unchanged
    assert together["correlation_groups"] == {"ground": ["A", "B"]}


def test_correlation_widens_the_spread_but_not_the_mean():
    records = [score_record(rec(f"R{i}", 3, 0.5, 1, 3, group="programme"), PACK) for i in range(6)]
    together = simulate(records, SimulationSettings(iterations=50_000, correlation_in_group=0.5))
    apart = simulate(records, SimulationSettings(iterations=50_000, correlation_in_group=0.0))
    assert together["percentiles_pct"]["P90"] > apart["percentiles_pct"]["P90"]
    assert together["mean_pct"] == pytest.approx(apart["mean_pct"], rel=0.03)


def test_same_inputs_give_same_numbers():
    records = [rec("A", 3, 0.5, 1, 3, group="g"), rec("B", 4, 1, 2, 5, group="g"), rec("C", 2, 0, 1, 9)]
    s = settings()
    first, second = calculate(records, PACK, s, 2e6), calculate(records, PACK, s, 2e6)
    assert first == second


def test_different_seed_gives_close_but_different_numbers():
    records = [rec("A", 3, 0.5, 1, 3), rec("B", 4, 1, 2, 5)]
    a = calculate(records, PACK, settings(seed=1))["contingency"]["P80"]["pct"]
    b = calculate(records, PACK, settings(seed=2))["contingency"]["P80"]["pct"]
    assert a != b and a == pytest.approx(b, rel=0.05)


def test_contributions_explain_p80():
    records = [rec("A", 4, 1, 2, 6), rec("B", 2, 0.5, 1, 2), rec("C", 3, 2, 4, 9)]
    out = calculate(records, PACK, settings(iterations=50_000))
    contributions = out["simulation"]["contributions"]
    assert sum(c["p80_contribution_pct"] for c in contributions) == pytest.approx(
        out["contingency"]["P80"]["pct"], rel=0.1)
    assert contributions[0]["id"] == "C"     # largest contributor first


def test_no_records():
    out = calculate([], PACK, settings())
    assert out["contingency"]["P80"]["pct"] == 0 and out["expected_value"]["net_pct"] == 0


def test_bad_simulation_settings_are_refused():
    with pytest.raises(ValueError):
        SimulationSettings.from_settings({"simulation": {"correlation_in_group": 1.0}})
    with pytest.raises(ValueError):
        SimulationSettings.from_settings({"simulation": {"distribution": "normal"}})


def test_normal_cdf_accuracy():
    x = np.array([-3.0, -1.0, 0.0, 0.5, 1.96, 3.0])
    expected = [0.0013499, 0.1586553, 0.5, 0.6914625, 0.9750021, 0.9986501]
    assert np.allclose(_normal_cdf(x), expected, atol=1e-6)
