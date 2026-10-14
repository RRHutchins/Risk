"""The local web page. Start it with:  python -m risk_engine web

Runs only on this computer (http://localhost). Documents are saved inside the
project's outputs folder and sent only to the Claude API.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from risk_engine.calc_pipeline import CalculationError, parse_money, run_calculation  # noqa: E402
from risk_engine.config import api_key_present, load_settings, resolve_path  # noqa: E402
from risk_engine.costs import Ledger, Usage, price_usage  # noqa: E402
from risk_engine.packs import available_packs, load_pack  # noqa: E402
from risk_engine.pipeline import plan_extraction, run_extraction  # noqa: E402
from risk_engine.report_pipeline import run_report  # noqa: E402
from risk_engine.synthesise import fmt_money, fmt_pct  # noqa: E402


def esc(text: str) -> str:
    """Streamlit reads $...$ as a formula; show dollar signs as written."""
    return str(text).replace("$", "\\$")


def save_uploads(files) -> Path:
    folder = resolve_path("outputs") / "uploads" / datetime.now().strftime("%Y%m%d-%H%M%S")
    for f in files:
        rel = Path(*[p for p in Path(f.name).parts if p not in ("..", "/", "\\")])
        target = folder / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f.getvalue())
    return folder


def extra_steps_estimate(settings: dict, merge: bool, use_claude: bool) -> float:
    extra = 0.0
    if merge:
        extra += price_usage(settings["models"]["classification"], Usage(input=30000, output=8000), settings["pricing"])
    if use_claude:
        extra += price_usage(settings["models"]["classification"], Usage(input=30000, output=15000), settings["pricing"])
        extra += price_usage(settings["models"]["synthesis"], Usage(input=25000, output=8000), settings["pricing"])
    return extra


def main() -> None:
    st.set_page_config(page_title="Risk Reviewer", layout="wide")
    settings = load_settings()
    ledger = Ledger(resolve_path(settings["budget"]["ledger_file"]))
    spent = ledger.total_spent_usd()
    budget = settings["budget"]["total_budget_usd"]
    key_ok = api_key_present(settings)

    with st.sidebar:
        st.header("Settings")
        packs = available_packs()
        pack_name = st.selectbox("Domain pack", packs, index=packs.index(settings["default_pack"])
                                 if settings["default_pack"] in packs else 0)
        merge = st.checkbox("Merge duplicate findings", value=settings.get("merging", {}).get("enabled", True))
        use_claude = st.checkbox("Opportunity finder and written summary", value=True)
        st.divider()
        st.subheader("Spending")
        st.write(esc(f"Spent to date: **${spent:.2f}** of ${budget:.2f}"))
        st.write(esc(f"Per-run cap: **${settings['budget']['per_run_cap_usd']:.2f}**"))
        st.write("API key: " + ("found" if key_ok else "**not set** (see README, Step 6)"))
        st.caption("Change these limits in config/settings.yaml.")

    pack = load_pack(pack_name)
    st.title(pack.config.get("report", {}).get("title", "Risk review"))
    st.caption(pack.footer + " Documents are sent only to the Claude API.")

    st.subheader("1. Choose the documents")
    files = st.file_uploader("Drag the folder of documents here (PDF, Word, Excel, text)",
                             accept_multiple_files="directory", key="files")
    typed = st.text_input("Or type the path of a folder on this computer", key="folder_path")
    value_text = st.text_input(f"{pack.base_value_label} (for example 2.5m). Leave blank for percentages only",
                               key="value")
    try:
        base_value = parse_money(value_text.strip() or None)
    except CalculationError as e:
        st.error(esc(e))
        base_value = "invalid"

    if st.button("Check documents and estimate cost", type="secondary"):
        folder = None
        if typed.strip():
            folder = Path(typed.strip().strip('"'))
            if not folder.is_dir():
                st.error(f"Folder not found: {folder}")
                folder = None
        elif files:
            folder = save_uploads(files)
        else:
            st.warning("Add some documents first.")
        if folder:
            st.session_state["plan"] = plan_extraction(folder, settings, pack_name)
            st.session_state.pop("result", None)

    plan = st.session_state.get("plan")
    if plan is not None:
        st.subheader("2. Check and run")
        rows = [{"Document": d.name, "Type": d.kind, "Sections": len(d.sections),
                 "Warnings": "; ".join(d.warnings)} for d in plan.docs]
        st.dataframe(rows, hide_index=True, width="stretch")
        for s in plan.skipped:
            st.warning(esc(f"Not read: {s.name}: {s.reason}."))
        total = plan.estimate_usd + extra_steps_estimate(settings, merge, use_claude)
        c1, c2, c3 = st.columns(3)
        c1.metric("Pieces of text to send", len(plan.chunks))
        c2.metric("Estimated cost", f"${total:.2f}")
        c3.metric("Budget remaining", f"${budget - spent:.2f}")
        problems = []
        if not plan.chunks:
            problems.append("There is no readable text to review.")
        if total > plan.cap_usd:
            problems.append("The estimate is over the per-run cap (config/settings.yaml, per_run_cap_usd).")
        if spent + total > budget:
            problems.append("This run could take you over your total budget.")
        if not key_ok:
            problems.append("No API key found. See README, Step 6, then restart this page.")
        if base_value == "invalid":
            problems.append(f"The {pack.base_value_label.lower()} could not be read.")
        for p in problems:
            st.error(esc(p))
        if st.button(f"Run the review (about ${total:.2f})", type="primary", disabled=bool(problems)):
            with st.status("Working. Each piece of text usually takes under a minute.", expanded=True) as status:
                try:
                    ex = run_extraction(plan, settings, progress=st.text)
                    if ex["summary"]["stopped_because"]:
                        raise CalculationError(ex["summary"]["stopped_because"])
                    st.text("Merging duplicates and calculating contingency...")
                    calc = run_calculation(Path(ex["out_dir"]), settings, base_value, merge=merge,
                                           progress=st.text, already_spent_usd=ex["summary"]["actual_usd"])
                    rep = run_report(Path(calc["out_dir"]), settings, use_claude=use_claude, progress=st.text,
                                     already_spent_usd=ex["summary"]["actual_usd"] + calc["audit"]["cost_usd"])
                    st.session_state["result"] = rep
                    status.update(label="Finished", state="complete")
                except CalculationError as e:
                    status.update(label="Stopped", state="error")
                    st.error(esc(e))

    rep = st.session_state.get("result")
    if rep:
        b = rep["bundle"]
        calc = b["calculation"]["result"]
        cur = pack.currency
        st.subheader("3. Results")
        ind = b["synthesis"]["indicator"]
        n = b["synthesis"].get("narrative")
        c = calc["contingency"]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric(pack.config.get("decision", {}).get("title", "Indicator"), ind["label"] or "none")
        for col, key in ((m2, "P50"), (m3, "P80")):
            v = c[key]
            col.metric(f"{key} contingency", fmt_money(v["money"], cur) if v["money"] is not None else fmt_pct(v["pct"]))
        m4.metric("Red / amber / green", f"{calc['ratings']['red']} / {calc['ratings']['amber']} / {calc['ratings']['green']}")
        if n:
            st.markdown(f"**{esc(n['headline'])}**")
            st.write(esc(n["rationale"]))
            if not n["agrees_with_indicator"]:
                st.warning("The written view differs from the rule-based indicator. Review both before deciding.")
        order = {"red": 0, "amber": 1, "green": 2}
        st.dataframe([{"ID": r["id"], "Risk": r["title"], "Rating": r["rating"].upper(), "Score": r["score"],
                       "Expected value": fmt_money(r["expected_value_money"], cur) if r.get("expected_value_money") is not None
                       else fmt_pct(r["expected_value_pct"])}
                      for r in sorted(calc["records"], key=lambda r: (order.get(r["rating"], 3), -r["score"]))],
                     hide_index=True, width="stretch")
        d1, d2, d3 = st.columns(3)
        for col, key, label, mime in (
            (d1, "report", "Download the Word report",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            (d2, "register", "Download the Excel register",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            (d3, "audit", "Download the audit file", "application/json"),
        ):
            path = Path(rep[key])
            col.download_button(label, path.read_bytes(), file_name=path.name, mime=mime)
        st.caption(esc(f"Also saved in: {Path(rep['report']).parent}   |   Cost of this run: ${b['cost_usd']:.2f}"))


main()
