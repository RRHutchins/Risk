"""A live run: read the documents, estimate, then extract with Claude."""

from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from risk_engine import __version__
from risk_engine.config import resolve_path
from risk_engine.costs import CostGuard, Ledger, count_tokens_local, estimate_run
from risk_engine.dryrun import read_documents
from risk_engine.extract import (ENGINE_RULES, Extractor, ExtractionStopped, build_schema,
                                 process_results, system_prompt, user_message)
from risk_engine.ingest import Chunk, Document, SkippedFile, chunk_documents
from risk_engine.packs import Pack, load_pack
from risk_engine.records_report import write_records_workbook
from risk_engine.runs import create_run_folder
from risk_engine.sections_report import write_sections_workbook


@dataclass
class Plan:
    folder: Path
    pack: Pack
    docs: list[Document]
    skipped: list[SkippedFile]
    chunks: list[Chunk]
    estimate_usd: float
    cap_usd: float
    spent_to_date_usd: float
    total_budget_usd: float

    @property
    def within_cap(self) -> bool:
        return self.estimate_usd <= self.cap_usd

    @property
    def within_budget(self) -> bool:
        return self.spent_to_date_usd + self.estimate_usd <= self.total_budget_usd


def plan_extraction(folder: Path, settings: dict, pack_name: str | None = None) -> Plan:
    folder = Path(folder).resolve()
    pack = load_pack(pack_name or settings["default_pack"])
    cpt = settings["estimate"]["chars_per_token"]
    docs, skipped = read_documents(folder, settings, pack)
    chunks = chunk_documents(docs, max_chars=int(settings["estimate"]["max_chunk_tokens"] * cpt))
    estimate = estimate_run([count_tokens_local(user_message(c), cpt) for c in chunks],
                            count_tokens_local(system_prompt(pack), cpt), 0, settings)
    extraction_usd = sum(l.cost_usd for l in estimate.lines if l.step == "Extraction")
    ledger = Ledger(resolve_path(settings["budget"]["ledger_file"]))
    return Plan(folder, pack, docs, skipped, chunks,
                estimate_usd=extraction_usd * (1 + estimate.safety_margin),
                cap_usd=settings["budget"]["per_run_cap_usd"],
                spent_to_date_usd=ledger.total_spent_usd(),
                total_budget_usd=settings["budget"]["total_budget_usd"])


def make_client(settings: dict):
    import anthropic

    key = os.environ.get(settings.get("api_key_env_var", "ANTHROPIC_API_KEY"))
    return anthropic.Anthropic(api_key=key)


def run_extraction(plan: Plan, settings: dict, client=None, progress=print) -> dict:
    """Run extraction for a plan. Always saves what was done, even if stopped."""
    client = client or make_client(settings)
    run_id, out_dir = create_run_folder(resolve_path(settings.get("output_folder", "outputs")), plan.folder)
    ledger = Ledger(resolve_path(settings["budget"]["ledger_file"]))
    guard = CostGuard(plan.cap_usd, settings["pricing"])
    extractor = Extractor(client, plan.pack, settings, guard, ledger, run_id, progress)

    stopped = ""
    started = datetime.now(timezone.utc)
    try:
        results = extractor.run(plan.chunks)
    except ExtractionStopped as e:
        stopped = str(e)
        results = extractor.last_results
    finished = datetime.now(timezone.utc)

    processed = process_results(results, plan.docs, plan.pack)
    pieces = {s: sum(1 for r in results if r.status == s) for s in
              ("ok", "refused", "too_long", "unreadable", "skipped")}
    summary = {
        "pieces_total": len(results),
        "pieces_reviewed": pieces["ok"],
        "pieces_not_reviewed": len(results) - pieces["ok"],
        "pieces_by_status": pieces,
        "records_accepted": len(processed["records"]),
        "records_excluded": len(processed["excluded"]),
        "quotes_verified_share": _share(processed),
        "checklist_answered": sum(1 for c in processed["checklist"] if c["status"] == "answered"),
        "checklist_items": len(processed["checklist"]),
        "estimated_usd": round(plan.estimate_usd, 6),
        "actual_usd": round(guard.spent_usd, 6),
        "seconds": round((finished - started).total_seconds(), 1),
        "stopped_because": stopped,
    }
    audit = {
        "run_id": run_id,
        "mode": "extract",
        "folder": str(plan.folder),
        "pack": plan.pack.name,
        "summary": summary,
        "records": processed["records"],
        "excluded": processed["excluded"],
        "checklist": processed["checklist"],
        "pieces": [asdict(r) for r in results],
        "documents": [{"name": d.name, "type": d.kind, "sections": [s.ref for s in d.sections],
                       "warnings": d.warnings, "notes": d.notes} for d in plan.docs],
        "skipped_files": [asdict(s) for s in plan.skipped],
        "models": {"extraction": settings["models"]["extraction"]},
        "prompts": {"system": system_prompt(plan.pack), "engine_rules": ENGINE_RULES,
                    "user_message_template": user_message(Chunk("<document name>", [], "<document text>")),
                    "output_schema": build_schema(plan.pack)},
        "settings": settings,
        "software": {"engine_version": __version__, "python": platform.python_version()},
        "started_utc": started.isoformat(timespec="seconds"),
        "finished_utc": finished.isoformat(timespec="seconds"),
    }
    with open(out_dir / "extraction_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, default=str)
    write_sections_workbook(plan.docs, plan.skipped, out_dir / "sections.xlsx")
    write_records_workbook(processed, summary, results, out_dir / "records.xlsx")
    return {"run_id": run_id, "out_dir": str(out_dir), "summary": summary, **processed,
            "pieces": results, "audit_file": str(out_dir / "extraction_audit.json"),
            "records_file": str(out_dir / "records.xlsx")}


def _share(processed: dict) -> float | None:
    total = len(processed["records"]) + len(processed["excluded"])
    if not total:
        return None
    verified = len(processed["records"]) + sum(1 for r in processed["excluded"] if r["quote_verified"])
    return round(verified / total, 4)
