"""Command-line interface.

    python -m risk_engine check              check the installation
    python -m risk_engine ingest FOLDER      read and split documents, list the sections
    python -m risk_engine dry-run FOLDER     read documents and estimate cost (no API calls)
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
        print(f"  API key ({key_var}) ... found (not needed for a dry run)")
    else:
        print(f"  API key ({key_var}) ... not set (fine for now; needed from Stage 3)")
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

    sub.add_parser("ledger", help="show spending to date")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.settings)
        return {"check": cmd_check, "ingest": cmd_ingest, "dry-run": cmd_dry_run,
                "ledger": cmd_ledger}[args.command](args, settings)
    except ConfigError as e:
        print(f"Setup problem: {e}")
        return 1
