"""Command-line interface.

    python -m risk_engine check              check the installation
    python -m risk_engine ingest FOLDER      read and split documents, list the sections
    python -m risk_engine dry-run FOLDER     read documents and estimate cost (no API calls)
    python -m risk_engine extract FOLDER     find risks with Claude (spends API credit)
    python -m risk_engine calculate RUN      merge duplicates, score, simulate contingency
    python -m risk_engine review FOLDER      extract and calculate in one go
    python -m risk_engine ledger             show spending to date
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from risk_engine.config import ConfigError, api_key_present, load_settings, resolve_path
from risk_engine.costs import Ledger
from risk_engine.packs import available_packs, load_pack

LINE = "-" * 64


def cmd_check(args, settings) -> int:
    print("Checking the installation...\n")
    ok = True
    print(f"  Python version ........... {sys.version.split()[0]}")
    if sys.version_info < (3, 10):
        print("  !! Python 3.10 or newer is needed.")
        ok = False
    for module, label in [("yaml", "PyYAML"), ("pypdf", "pypdf"), ("docx", "python-docx"),
                          ("openpyxl", "openpyxl"), ("anthropic", "anthropic")]:
        try:
            __import__(module)
            print(f"  {label:<24} installed")
        except ImportError:
            print(f"  {label:<24} MISSING - run:  pip install -r requirements.txt")
            ok = False
    print("  Settings file ............ loaded")
    for name in available_packs():
        try:
            pack = load_pack(name)
            print(f"  Domain pack '{name}' ... loaded ({len(pack.taxonomy_codes)} categories, "
                  f"{len(pack.checklist)} checklist items)")
        except ConfigError as e:
            print(f"  Domain pack '{name}' ... PROBLEM: {e}")
            ok = False
    key_var = settings.get("api_key_env_var", "ANTHROPIC_API_KEY")
    if api_key_present(settings):
        print(f"  API key ({key_var}) ... found")
    else:
        print(f"  API key ({key_var}) ... not set (needed for 'extract'; see README)")
    print()
    print("All good." if ok else "Some problems were found; see above.")
    return 0 if ok else 1


def _folder_ok(folder: Path) -> bool:
    if folder.is_dir():
        return True
    print(f"Folder not found: {folder}\nCheck the spelling, or drag the folder into this window to paste its path.")
    return False


def _print_documents(r: dict, show_sections: bool = False) -> None:
    print(f"Folder:      {r['folder']}")
    print(f"Domain pack: {r['pack']}")
    print(f"\nDocuments read: {len(r['documents'])}")
    for d in r["documents"]:
        print(f"  - {d['name']} ({d['type']}, {len(d['sections'])} section(s), about {d['tokens']:,} tokens)")
        for w in d["warnings"]:
            print(f"      WARNING: {w}")
        for n in d["notes"]:
            print(f"      Note: {n}")
        if show_sections:
            for i, sec in enumerate(d["sections"], start=1):
                print(f"        {i:>3}. {sec['ref']}")
    if r["skipped_files"]:
        print("\nFiles not read:")
        for s in r["skipped_files"]:
            print(f"  - {s['name']}: {s['reason']}.")
    if not r["documents"]:
        print("\nNo readable documents were found.")


def cmd_ingest(args, settings) -> int:
    from risk_engine.dryrun import ingest_only

    folder = Path(args.folder)
    if not _folder_ok(folder):
        return 1
    r = ingest_only(folder, settings, pack_name=args.pack)
    print(LINE)
    print("READING DOCUMENTS - no data was sent anywhere and nothing was spent")
    print(LINE)
    _print_documents(r, show_sections=True)
    print(f"\nSections listed in Excel: {r['sections_file']}")
    print(f"Audit file saved:         {r['audit_file']}")
    print(LINE)
    return 0


def cmd_dry_run(args, settings) -> int:
    from risk_engine.dryrun import dry_run

    folder = Path(args.folder)
    if not _folder_ok(folder):
        return 1
    r = dry_run(folder, settings, pack_name=args.pack, batch=args.batch)

    print(LINE)
    print("DRY RUN - no data was sent anywhere and nothing was spent")
    print(LINE)
    _print_documents(r)

    t = r["tokens"]
    print(f"\nText to review: about {t['document_text']:,} tokens in {len(r['chunks'])} piece(s)")
    print(f"Pack instructions: about {t['pack_instructions_per_call']:,} tokens per call (cached)")

    e = r["estimate"]
    print("\nEstimated cost of a real run" + (" (batch pricing)" if r["batch_pricing"] else "") + ":")
    for line in e["lines"]:
        print(f"  {line['step']:<16} {line['model']:<20} {line['calls']:>3} call(s)   ${line['cost_usd']:.4f}")
    print(f"  {'Safety margin':<16} {'':<20} {'':>3}           +{e['safety_margin']:.0%}")
    print(f"  {'ESTIMATED TOTAL':<45}   ${e['total_usd']:.4f}")
    print(f"\nPer-run cap: ${r['per_run_cap_usd']:.2f}  ->  "
          + ("within the cap." if r["within_cap"] else "OVER THE CAP. A real run would be stopped."))
    print(f"\nSections listed in Excel: {r['sections_file']}")
    print(f"Audit file saved:         {r['audit_file']}")
    print(f"Ledger updated:           {r['ledger_file']}")
    print(LINE)
    return 0


def cmd_extract(args, settings) -> int:
    r = _extract(args, settings)
    return 0 if r and not r["summary"]["stopped_because"] else 1


def _extract(args, settings, extra_usd: float = 0.0):
    """Show the plan, confirm, and run extraction. Returns the result, or None."""
    from risk_engine.pipeline import plan_extraction, run_extraction

    folder = Path(args.folder)
    if not _folder_ok(folder):
        return None
    plan = plan_extraction(folder, settings, pack_name=args.pack)
    plan.estimate_usd += extra_usd
    print(LINE)
    print("EXTRACT RISKS WITH CLAUDE")
    print(LINE)
    print(f"Folder:      {plan.folder}")
    print(f"Domain pack: {plan.pack.name}")
    print(f"Documents:   {len(plan.docs)} read, {len(plan.skipped)} not read")
    for d in plan.docs:
        for w in d.warnings:
            print(f"  WARNING ({d.name}): {w}")
    for s in plan.skipped:
        print(f"  Not read: {s.name}: {s.reason}.")
    if not plan.chunks:
        print("\nThere is no readable text to review.")
        return None
    print(f"\nThe text will be sent to Claude ({settings['models']['extraction']}) in {len(plan.chunks)} piece(s).")
    print(f"Estimated cost:     ${plan.estimate_usd:.2f}")
    print(f"Per-run cap:        ${plan.cap_usd:.2f}")
    print(f"Budget remaining:   ${plan.total_budget_usd - plan.spent_to_date_usd:.2f} "
          f"of ${plan.total_budget_usd:.2f}")
    if not plan.within_cap:
        print("\nSTOPPED: the estimate is over the per-run cap. Nothing has been sent.")
        print("To go ahead, raise per_run_cap_usd in config/settings.yaml, or review fewer documents.")
        return None
    if not plan.within_budget:
        print("\nSTOPPED: this run could take you over your total budget. Nothing has been sent.")
        print("To go ahead, raise total_budget_usd in config/settings.yaml.")
        return None
    if not api_key_present(settings):
        key_var = settings.get("api_key_env_var", "ANTHROPIC_API_KEY")
        print(f"\nSTOPPED: no API key found. Nothing has been sent.")
        print(f"Set the {key_var} environment variable first; see Step 6 in README.md.")
        return None
    print("\nDocument text is sent only to the Claude API (Anthropic). The run stops itself if it")
    print("would pass the per-run cap.")
    if not args.yes:
        answer = input("\nType yes and press Enter to start, or just press Enter to cancel: ").strip().lower()
        if answer not in ("yes", "y"):
            print("Cancelled. Nothing has been sent.")
            return None
    print("\nWorking. Each piece usually takes under a minute.")
    r = run_extraction(plan, settings)
    s = r["summary"]
    print(LINE)
    if s["stopped_because"]:
        print(f"RUN STOPPED EARLY: {s['stopped_because']}")
        print("What was done before it stopped has been saved.")
    print(f"Pieces reviewed:          {s['pieces_reviewed']} of {s['pieces_total']}")
    if s["pieces_not_reviewed"]:
        print(f"  NOT reviewed:           {s['pieces_not_reviewed']} (see the 'Pieces reviewed' sheet)")
    print(f"Risk records accepted:    {s['records_accepted']}")
    print(f"Records excluded:         {s['records_excluded']} (quote not verified or record incomplete)")
    if s["quotes_verified_share"] is not None:
        print(f"Quotes verified:          {s['quotes_verified_share']:.1%}")
    print(f"Checklist answered:       {s['checklist_answered']} of {s['checklist_items']}")
    print(f"Cost:                     ${s['actual_usd']:.4f} (estimate was ${s['estimated_usd']:.2f})")
    print(f"Time taken:               {s['seconds']:.0f} seconds")
    print(f"\nRecords to check in Excel: {r['records_file']}")
    print(f"Audit file:                {r['audit_file']}")
    print(LINE)
    return r


def _calculate(run_folder: Path, settings, contract_value, merge, already_spent_usd: float = 0.0) -> int:
    from risk_engine.calc_pipeline import CalculationError, parse_money, run_calculation

    try:
        base = parse_money(contract_value)
        if merge is not False and settings.get("merging", {}).get("enabled", True) and not api_key_present(settings):
            print("Duplicate merging needs the API key (Step 6 in README.md).")
            print("Set it up, or add --no-merge to calculate without merging.")
            return 1
        r = run_calculation(run_folder, settings, base, merge=merge, already_spent_usd=already_spent_usd)
    except CalculationError as e:
        print(f"Problem: {e}")
        return 1
    a = r["audit"]
    res = a["result"]
    cur = a.get("currency") or ""

    def money(v):
        return "" if v is None else f"  ({cur} {v:,.0f})"
    print(LINE)
    print("RISK CALCULATION")
    print(LINE)
    if a["base_value"] is None:
        print("No contract value given, so figures are shown as % of contract value only.")
        print("Add --contract-value 2500000 (for example) to see money as well.")
    else:
        print(f"Contract value:           {cur} {a['base_value']:,.0f}")
    if a["merging"].get("groups") is not None and a["merging"].get("note") != "duplicate merging switched off":
        print(f"Records:                  {a['records_before_merging']} found, "
              f"{a['records_after_merging']} after merging duplicates")
    else:
        print(f"Records:                  {a['records_before_merging']} (duplicate merging switched off)")
    if a["excel_edits"]:
        print(f"Your edits used:          {len(a['excel_edits'])} (from records.xlsx)")
    print(f"Red / amber / green:      {res['ratings']['red']} / {res['ratings']['amber']} / {res['ratings']['green']}")
    ev = res["expected_value"]
    print(f"Expected value (net):     {ev['net_pct']:.2f}% of contract value{money(ev['net_money'])}")
    print("Contingency (simulated):")
    for name, v in res["contingency"].items():
        label = "Mean" if name == "mean" else name
        print(f"  {label:<6} {v['pct']:>7.2f}%{money(v['money'])}")
    top = res["simulation"]["contributions"][:5]
    if top:
        print("Largest contributors to P80:")
        for c in top:
            print(f"  {c['id']}  {c['p80_contribution_pct']:>6.2f}%  {c['title'][:60]}")
    print(f"\nResults in Excel: {r['workbook']}")
    print(f"Audit file:       {r['audit_file']}")
    print(LINE)
    return 0


def cmd_calculate(args, settings) -> int:
    return _calculate(Path(args.run_folder), settings, args.contract_value, False if args.no_merge else None)


def cmd_review(args, settings) -> int:
    from risk_engine.costs import Usage, price_usage

    from risk_engine.calc_pipeline import CalculationError, parse_money
    try:
        parse_money(args.contract_value)
    except CalculationError as e:
        print(f"Problem: {e}")
        return 1
    merge_on = not args.no_merge and settings.get("merging", {}).get("enabled", True)
    extra = 0.0
    if merge_on:  # a generous allowance for the one merging call
        extra = price_usage(settings["models"]["classification"], Usage(input=30000, output=8000),
                            settings["pricing"])
    r = _extract(args, settings, extra_usd=extra)
    if not r or r["summary"]["stopped_because"]:
        return 1
    print()
    return _calculate(Path(r["out_dir"]), settings, args.contract_value, False if args.no_merge else None,
                      already_spent_usd=r["summary"]["actual_usd"])


def cmd_ledger(args, settings) -> int:
    ledger = Ledger(resolve_path(settings["budget"]["ledger_file"]))
    budget = settings["budget"]["total_budget_usd"]
    spent = ledger.total_spent_usd()
    print(LINE)
    print("SPENDING LEDGER")
    print(LINE)
    print(f"Ledger file:        {ledger.path}")
    print(f"Runs recorded:      {ledger.run_count()}")
    print(f"Spent to date:      ${spent:.4f}")
    print(f"Total budget:       ${budget:.2f}")
    print(f"Remaining:          ${budget - spent:.4f}")
    rows = ledger.rows()[-10:]
    if rows:
        print("\nMost recent entries (times are your computer's local time):")
        for row in rows:
            print(f"  {_local_time(row['time_utc'])}  {row['mode']:<8} {row['step']:<15} "
                  f"est ${float(row['estimated_usd']):.4f}  actual ${float(row['actual_usd']):.4f}")
        print("\n(The ledger file itself records times in UTC, so it reads the same anywhere.)")
    print(LINE)
    return 0


def _local_time(utc_text: str) -> str:
    try:
        t = datetime.strptime(utc_text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return t.astimezone().strftime("%d %b %Y %H:%M")
    except ValueError:
        return f"{utc_text} UTC"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m risk_engine", description="Tender Risk Reviewer")
    p.add_argument("--settings", help="use a different settings file (default: config/settings.yaml)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="check the installation")

    i = sub.add_parser("ingest", help="read and split documents, and list the sections")
    i.add_argument("folder", help="folder containing the documents")
    i.add_argument("--pack", help="domain pack to use (default from settings)")

    d = sub.add_parser("dry-run", help="read documents and estimate cost, without calling the API")
    d.add_argument("folder", help="folder containing the tender documents")
    d.add_argument("--pack", help="domain pack to use (default from settings)")
    d.add_argument("--batch", action="store_true", help="estimate using batch (unattended) pricing")

    e = sub.add_parser("extract", help="find risks with Claude (spends API credit)")
    e.add_argument("folder", help="folder containing the tender documents")
    e.add_argument("--pack", help="domain pack to use (default from settings)")
    e.add_argument("--yes", action="store_true", help="start without asking for confirmation")

    c = sub.add_parser("calculate", help="merge duplicates, score and simulate contingency for an extract run")
    c.add_argument("run_folder", help="the folder in 'outputs' made by the extract command")
    c.add_argument("--contract-value", help="contract value, e.g. 2500000 or 2.5m")
    c.add_argument("--no-merge", action="store_true", help="skip duplicate merging (no Claude call)")

    v = sub.add_parser("review", help="extract and calculate in one go (spends API credit)")
    v.add_argument("folder", help="folder containing the tender documents")
    v.add_argument("--contract-value", help="contract value, e.g. 2500000 or 2.5m")
    v.add_argument("--pack", help="domain pack to use (default from settings)")
    v.add_argument("--yes", action="store_true", help="start without asking for confirmation")
    v.add_argument("--no-merge", action="store_true", help="skip duplicate merging")

    sub.add_parser("ledger", help="show spending to date")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.settings)
        return {"check": cmd_check, "ingest": cmd_ingest, "dry-run": cmd_dry_run,
                "extract": cmd_extract, "calculate": cmd_calculate,
                "review": cmd_review, "ledger": cmd_ledger}[args.command](args, settings)
    except ConfigError as e:
        print(f"Setup problem: {e}")
        return 1
