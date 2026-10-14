"""Charts for the report, drawn from calculated results only.

Colours: threats (costs) red and opportunities (savings) blue, a checked
colour-blind-safe pair; text in neutral ink; light, recessive grid.
"""

from __future__ import annotations

from pathlib import Path

THREAT = "#e34948"
OPPORTUNITY = "#2a78d6"
LINE = "#2a78d6"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"


def _clean(title: str, limit: int = 40) -> str:
    """Drop symbols fonts cannot draw (such as Word's private bullet characters)."""
    text = " ".join("".join(ch for ch in title if not 0xE000 <= ord(ch) <= 0xF8FF).split())
    return text if len(text) <= limit else text[: limit - 2].rstrip() + "..."


def _setup():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK_2,
        "xtick.color": INK_2, "ytick.color": INK_2, "axes.titlecolor": INK, "axes.titlesize": 10,
        "axes.titleweight": "bold", "axes.titlelocation": "left",
    })
    return plt


def _value_axis(base_value, currency_symbol):
    """Converter and label: money when a base value is given, else percent."""
    if base_value:
        return (lambda pct: pct * base_value / 100.0), f"Net risk cost ({currency_symbol.strip() or 'money'})"
    return (lambda pct: pct), "Net risk cost (% of base value)"


def _short(value, base_value, currency_symbol):
    """Compact axis labels: £40k, £1.2m."""
    if not base_value:
        return f"{value:g}%"
    sign, v = ("-" if value < 0 else ""), abs(value)
    if v >= 1e6:
        return f"{sign}{currency_symbol}{v / 1e6:g}m"
    if v >= 1e3:
        return f"{sign}{currency_symbol}{v / 1e3:g}k"
    return f"{sign}{currency_symbol}{v:g}"


def _fmt(value, base_value, currency_symbol):
    if base_value:
        sign = "-" if value < 0 else ""
        return f"{sign}{currency_symbol}{abs(value):,.0f}"
    return f"{value:.2f}%"


def cumulative_curve(simulation: dict, base_value: float | None, currency_symbol: str, path: Path) -> Path:
    plt = _setup()
    conv, xlabel = _value_axis(base_value, currency_symbol)
    xs = [conv(p["value_pct"]) for p in simulation["curve_pct"]]
    ys = [p["percentile"] for p in simulation["curve_pct"]]
    fig, ax = plt.subplots(figsize=(6.3, 3.2), dpi=200)
    ax.plot(xs, ys, color=LINE, linewidth=2)
    for name in ("P50", "P80"):
        pct = simulation["percentiles_pct"].get(name)
        if pct is None:
            continue
        x, y = conv(pct), int(name[1:])
        ax.plot([x, x], [0, y], color=INK_2, linewidth=1, linestyle=(0, (2, 2)))
        ax.plot([xs[0], x], [y, y], color=INK_2, linewidth=1, linestyle=(0, (2, 2)))
        ax.plot([x], [y], marker="o", markersize=5, color=LINE, markeredgecolor="white", markeredgewidth=1.5)
        ax.annotate(f"{name}: {_fmt(x, base_value, currency_symbol)}", (x, y), xytext=(6, -12),
                    textcoords="offset points", color=INK, fontsize=8.5)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Chance cost is at or below (%)")
    ax.set_xlabel(xlabel)
    fig.suptitle("Cumulative curve of simulated net risk cost", x=0.02, ha="left", fontsize=10,
                 fontweight="bold", color=INK)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    if base_value:
        ax.xaxis.set_major_formatter(lambda v, _: _fmt(v, base_value, currency_symbol))
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path


def tornado(contributions: list[dict], base_value: float | None, currency_symbol: str, path: Path,
            top_n: int = 10) -> Path | None:
    items = [c for c in contributions if abs(c["p80_contribution_pct"]) > 1e-9][:top_n]
    if not items:
        return None
    plt = _setup()
    from matplotlib.patches import Patch
    conv, xlabel = _value_axis(base_value, currency_symbol)
    labels = [f"{c['id']}  " + _clean(c["title"]) for c in items][::-1]
    values = [conv(c["p80_contribution_pct"]) for c in items][::-1]
    colours = [OPPORTUNITY if v < 0 else THREAT for v in values]
    fig, ax = plt.subplots(figsize=(6.3, 0.42 * len(items) + 1.2), dpi=200)
    bars = ax.barh(labels, values, color=colours, height=0.6, edgecolor="white", linewidth=1)
    span = max(abs(v) for v in values) or 1
    for bar, v in zip(bars, values):
        # values sit to the right of the bar end (or of zero, for savings),
        # so they never collide with the risk names on the left
        ax.annotate(_fmt(v, base_value, currency_symbol), (max(v, 0), bar.get_y() + bar.get_height() / 2),
                    xytext=(4, 0), textcoords="offset points", ha="left", va="center", color=INK, fontsize=8)
    ax.axvline(0, color=INK_2, linewidth=0.8)
    lo = min(0, min(values)) - 0.25 * span
    ax.set_xlim(lo, max(0, max(values)) + 0.3 * span)
    ax.set_xlabel(xlabel.replace("Net risk cost", "Contribution to P80"))
    fig.suptitle("Largest contributors to the P80 contingency", x=0.02, ha="left", fontsize=10,
                 fontweight="bold", color=INK)
    from matplotlib.ticker import MaxNLocator
    ax.xaxis.set_major_locator(MaxNLocator(5))
    ax.grid(True, axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.set_major_formatter(lambda v, _: _short(v, base_value, currency_symbol))
    if any(v < 0 for v in values):
        ax.legend(handles=[Patch(color=THREAT, label="Threat (cost)"), Patch(color=OPPORTUNITY, label="Opportunity (saving)")],
                  loc="lower right", frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path
