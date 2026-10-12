"""Scoring, expected value and Monte Carlo simulation.

Every number in the output comes from here. Claude supplies judgements
(a likelihood score and an impact range, each with a reason); this module
turns them into scores, ratings, expected values and contingency figures,
using the scales and thresholds in the domain pack.

All impacts are percentages of the base value (for a tender, the contract
value). Money is the percentage times the base value, divided by 100.
Opportunities count as negative cost.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def probability(likelihood: int, pack_config: dict) -> float:
    """The simulation probability for a likelihood score (the band midpoint)."""
    for band in pack_config["likelihood_scale"]:
        if band["score"] == likelihood:
            return float(band["midpoint"])
    raise ValueError(f"likelihood {likelihood} is not on the pack's scale")


def impact_score(impact_pct: float, pack_config: dict) -> int:
    """The impact band for a percentage. A value on a band's upper limit falls
    in the band above (0.5% is 'Moderate' when 'Minor' is under 0.5%)."""
    magnitude = abs(impact_pct)
    for band in pack_config["impact_scale"]:
        top = band.get("upper_pct")
        if top is None or magnitude < top:
            return int(band["score"])
    return int(pack_config["impact_scale"][-1]["score"])


def rating(score: int, flags: list[str], pack_config: dict) -> str:
    r = pack_config["rating"]
    if set(flags or []) & set(r.get("always_red_flags", [])):
        return "red"
    if score >= r["red_min"]:
        return "red"
    if score >= r["amber_min"]:
        return "amber"
    return "green"


def sign(record: dict) -> int:
    """+1 for a threat (a cost), -1 for an opportunity (a saving)."""
    return -1 if record.get("type") == "opportunity" else 1


def score_record(record: dict, pack_config: dict) -> dict:
    """Scores, rating and expected value for one record (added as new fields)."""
    p = probability(record["likelihood"], pack_config)
    i = impact_score(record["impact_likely"], pack_config)
    score = int(record["likelihood"]) * i
    out = dict(record)
    out.update({
        "probability": p,
        "impact_score": i,
        "score": score,
        "rating": rating(score, record.get("flags", []), pack_config),
        "rating_overridden": rating(score, [], pack_config) != rating(score, record.get("flags", []), pack_config),
        # expected value = probability x most likely impact, opportunities negative
        "expected_value_pct": sign(record) * p * float(record["impact_likely"]),
    })
    return out


# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------

def _normal_cdf(x: np.ndarray) -> np.ndarray:
    """Standard normal distribution function, via the error function
    (Abramowitz and Stegun 7.1.26; error below 0.0000002)."""
    z = np.abs(x) / math.sqrt(2.0)
    t = 1.0 / (1.0 + 0.3275911 * z)
    poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))))
    erf = 1.0 - poly * np.exp(-z * z)
    return 0.5 * (1.0 + np.sign(x) * erf)


def _draw_impacts(rng: np.random.Generator, low: float, mode: float, high: float, n: int,
                  distribution: str) -> np.ndarray:
    if high <= low:
        return np.full(n, float(low))
    if distribution == "triangular":
        return rng.triangular(low, mode, high, n)
    # PERT: a beta distribution stretched over [low, high] with the given mode
    alpha = 1.0 + 4.0 * (mode - low) / (high - low)
    beta = 1.0 + 4.0 * (high - mode) / (high - low)
    return low + rng.beta(alpha, beta, n) * (high - low)


def _correlated_normals(rng: np.random.Generator, n: int, k: int, rho: float) -> np.ndarray:
    """n draws of k standard normals with pairwise correlation rho."""
    corr = np.full((k, k), rho) + np.eye(k) * (1.0 - rho)
    return rng.standard_normal((n, k)) @ np.linalg.cholesky(corr).T


@dataclass
class SimulationSettings:
    iterations: int = 10000
    seed: int = 20261010
    distribution: str = "pert"
    correlation_in_group: float = 0.5
    percentiles: tuple = (10, 50, 80, 90)

    @classmethod
    def from_settings(cls, settings: dict) -> "SimulationSettings":
        s = settings.get("simulation", {})
        sim = cls(iterations=int(s.get("iterations", 10000)), seed=int(s.get("seed", 20261010)),
                  distribution=str(s.get("distribution", "pert")).lower(),
                  correlation_in_group=float(s.get("correlation_in_group", 0.5)),
                  percentiles=tuple(int(p) for p in s.get("percentiles", [10, 50, 80, 90])))
        if sim.distribution not in ("pert", "triangular"):
            raise ValueError("simulation: distribution must be pert or triangular")
        if not 0.0 <= sim.correlation_in_group < 1.0:
            raise ValueError("simulation: correlation_in_group must be at least 0 and less than 1")
        if sim.iterations < 100:
            raise ValueError("simulation: iterations must be at least 100")
        return sim


def simulate(records: list[dict], sim: SimulationSettings) -> dict:
    """Simulate the total net risk cost (percent of base value).

    Method:
      1. Each risk occurs in an iteration with its probability.
      2. If it occurs, its impact is drawn from a PERT (or triangular)
         distribution on its minimum, most likely and maximum.
      3. Risks sharing a correlation group are positively correlated, both in
         whether they occur (a Gaussian copula) and in how large they are (rank
         reordering of the impact draws, the Iman-Conover method), using the
         configured correlation.
      4. The total for an iteration is threats minus opportunities.
    Records must already be scored (they need a 'probability').
    The same records and settings always give the same numbers.
    """
    n = sim.iterations
    rng = np.random.default_rng(sim.seed)
    k = len(records)
    occur_u = np.empty((n, k))
    impacts = np.empty((n, k))

    # Draw in a fixed order (record order) so results are repeatable.
    for j, r in enumerate(records):
        impacts[:, j] = _draw_impacts(rng, float(r["impact_min"]), float(r["impact_likely"]),
                                      float(r["impact_max"]), n, sim.distribution)
    groups: dict[str, list[int]] = {}
    for j, r in enumerate(records):
        label = str(r.get("correlation_group") or "").strip().lower()
        if label:
            groups.setdefault(label, []).append(j)
    grouped = {j for members in groups.values() if len(members) > 1 and sim.correlation_in_group > 0
               for j in members}
    occur_u[:, [j for j in range(k) if j not in grouped]] = rng.random((n, k - len(grouped)))
    for label in sorted(groups):
        members = groups[label]
        if len(members) < 2 or sim.correlation_in_group <= 0:
            continue
        occur_u[:, members] = _normal_cdf(_correlated_normals(rng, n, len(members), sim.correlation_in_group))
        ranks = _correlated_normals(rng, n, len(members), sim.correlation_in_group).argsort(axis=0).argsort(axis=0)
        for c, j in enumerate(members):
            impacts[:, j] = np.sort(impacts[:, j])[ranks[:, c]]

    probs = np.array([float(r["probability"]) for r in records])
    signs = np.array([sign(r) for r in records], dtype=float)
    per_risk = (occur_u < probs) * impacts * signs          # n x k, signed cost per risk
    total = per_risk.sum(axis=1) if k else np.zeros(n)

    def pct(q):
        return float(np.percentile(total, q))

    p80 = pct(80)
    near_p80 = (total >= pct(75)) & (total <= pct(85))
    contributions = []
    for j, r in enumerate(records):
        contributions.append({
            "id": r.get("id"),
            "title": r.get("title"),
            "type": r.get("type"),
            "mean_pct": float(per_risk[:, j].mean()),
            "p80_contribution_pct": float(per_risk[near_p80, j].mean()) if near_p80.any() else 0.0,
            "occurrence_rate": float((occur_u[:, j] < probs[j]).mean()),
        })
    contributions.sort(key=lambda c: (-abs(c["p80_contribution_pct"]), -abs(c["mean_pct"]), str(c["id"])))

    return {
        "iterations": n,
        "seed": sim.seed,
        "distribution": sim.distribution,
        "correlation_in_group": sim.correlation_in_group,
        "correlation_groups": {g: [records[j].get("id") for j in m] for g, m in sorted(groups.items()) if len(m) > 1},
        "mean_pct": float(total.mean()),
        "percentiles_pct": {f"P{q}": pct(q) for q in sim.percentiles},
        "p80_pct": p80,
        "curve_pct": [{"percentile": q, "value_pct": pct(q)} for q in range(0, 101)],
        "contributions": contributions,
    }


# ---------------------------------------------------------------------------
# Putting it together
# ---------------------------------------------------------------------------

def to_money(pct: float, base_value: float | None) -> float | None:
    return None if base_value is None else pct * base_value / 100.0


def calculate(records: list[dict], pack_config: dict, settings: dict, base_value: float | None = None) -> dict:
    """Score every record, sum expected values and run the simulation."""
    sim = SimulationSettings.from_settings(settings)
    scored = [score_record(r, pack_config) for r in records]
    for r in scored:
        r["expected_value_money"] = to_money(r["expected_value_pct"], base_value)
    ev_threats = sum(r["expected_value_pct"] for r in scored if sign(r) > 0)
    ev_opps = sum(r["expected_value_pct"] for r in scored if sign(r) < 0)
    result = simulate(scored, sim)
    contingency = {name: {"pct": v, "money": to_money(v, base_value)}
                   for name, v in result["percentiles_pct"].items()}
    contingency["mean"] = {"pct": result["mean_pct"], "money": to_money(result["mean_pct"], base_value)}
    return {
        "base_value": base_value,
        "records": scored,
        "ratings": {c: sum(1 for r in scored if r["rating"] == c) for c in ("red", "amber", "green")},
        "expected_value": {
            "threats_pct": ev_threats, "opportunities_pct": ev_opps, "net_pct": ev_threats + ev_opps,
            "threats_money": to_money(ev_threats, base_value),
            "opportunities_money": to_money(ev_opps, base_value),
            "net_money": to_money(ev_threats + ev_opps, base_value),
        },
        "contingency": contingency,
        "simulation": result,
    }
