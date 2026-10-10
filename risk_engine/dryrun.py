"""Reading a folder without calling the API: the 'ingest' and 'dry-run' commands."""

from __future__ import annotations

import json
import platform
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from risk_engine import __version__
from risk_engine.config import api_key_present, resolve_path
from risk_engine.costs import Estimate, Ledger, count_tokens_local, estimate_run
from risk_engine.ingest import Chunk, Document, SkippedFile, chunk_documents, read_folder
from risk_engine.packs import Pack, load_pack
from risk_engine.runs import create_run_folder
from risk_engine.sections_report import write_sections_workbook


def read_documents(folder: Path, settings: dict, pack: Pack) -> tuple[list[Document], list[SkippedFile]]:
    return read_folder(
        folder,
        accepted=pack.accepted_file_types,
        extra_heading_patterns=pack.heading_patterns,
        rows_per_section=(settings.get("ingest") or {}).get("excel_rows_per_section", 50),
    )


def ingest_only(folder: Path, settings: dict, pack_name: str | None = None) -> dict:
    """Read and split the documents, and save the sections for checking."""
    folder = Path(folder).resolve()
    pack = load_pack(pack_name or settings["default_pack"])
    docs, skipped = read_documents(folder, settings, pack)
    run_id, out_dir = create_run_folder(resolve_path(settings.get("output_folder", "outputs")), folder)
    cpt = settings["estimate"]["chars_per_token"]
    result = {
        "run_id": run_id,
        "mode": "ingest",
        "folder": str(folder),
        "pack": pack.name,
        "documents": [_doc_summary(d, cpt, full=True) for d in docs],
        "skipped_files": [asdict(s) for s in skipped],
        "software": {"engine_version": __version__, "python": platform.python_version()},
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    result["sections_file"] = str(write_sections_workbook(docs, skipped, out_dir / "sections.xlsx"))
    result["audit_file"] = str(_write_json(result, out_dir / "ingest_audit.json"))
    return result


def dry_run(folder: Path, settings: dict, pack_name: str | None = None, batch: bool = False) -> dict:
    """Process a folder without calling the API. Returns a result dictionary.

    Writes an audit JSON file and the sections workbook, and adds a $0 entry
    to the spending ledger.
    """
    folder = Path(folder).resolve()
    pack = load_pack(pack_name or settings["default_pack"])
    est_cfg = settings["estimate"]
    cpt = est_cfg["chars_per_token"]

    docs, skipped = read_documents(folder, settings, pack)
    chunks = chunk_documents(docs, max_chars=int(est_cfg["max_chunk_tokens"] * cpt))
    chunk_tokens = [count_tokens_local(c.text, cpt) for c in chunks]
    pack_tokens = count_tokens_local(pack.extraction_context(), cpt)
    synth_tokens = count_tokens_local(pack.synth_prompt, cpt)

    estimate = estimate_run(chunk_tokens, pack_tokens, synth_tokens, settings, batch=batch)
    cap = settings["budget"]["per_run_cap_usd"]
    run_id, out_dir = create_run_folder(resolve_path(settings.get("output_folder", "outputs")), folder)

    ledger = Ledger(resolve_path(settings["budget"]["ledger_file"]))
    for line in estimate.lines:
        ledger.append(run_id, "dry-run", line.step, line.model, line.usage,
                      estimated_usd=line.cost_usd, actual_usd=0.0,
                      note="estimate only; no API call made")

    result = {
        "run_id": run_id,
        "mode": "dry-run",
        "batch_pricing": batch,
        "folder": str(folder),
        "pack": pack.name,
        "documents": [_doc_summary(d, cpt) for d in docs],
        "skipped_files": [asdict(s) for s in skipped],
        "chunks": [_chunk_summary(c, t) for c, t in zip(chunks, chunk_tokens)],
        "tokens": {
            "document_text": sum(chunk_tokens),
            "pack_instructions_per_call": pack_tokens,
            "synthesis_instructions": synth_tokens,
            "method": f"local estimate at {cpt} characters per token (no API call)",
        },
        "estimate": _estimate_summary(estimate),
        "per_run_cap_usd": cap,
        "within_cap": estimate.total_usd <= cap,
        "api_key_present": api_key_present(settings),
        "settings": settings,
        "prompts": {"extraction_context": pack.extraction_context(), "synthesis": pack.synth_prompt},
        "software": {"engine_version": __version__, "python": platform.python_version()},
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    result["sections_file"] = str(write_sections_workbook(docs, skipped, out_dir / "sections.xlsx"))
    result["audit_file"] = str(_write_json(result, out_dir / "dry_run_audit.json"))
    result["ledger_file"] = str(ledger.path)
    return result


def _write_json(data: dict, path: Path) -> Path:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def _doc_summary(doc: Document, cpt: float, full: bool = False) -> dict:
    summary = {
        "name": doc.name,
        "type": doc.kind,
        "sections": [s.ref for s in doc.sections],
        "characters": doc.char_count,
        "tokens": sum(count_tokens_local(s.text, cpt) for s in doc.sections),
        "warnings": doc.warnings,
        "notes": doc.notes,
    }
    if full:
        summary["sections"] = [
            {"ref": s.ref, "clause": s.clause, "heading": s.heading, "locations": s.locations, "text": s.text}
            for s in doc.sections
        ]
    return summary


def _chunk_summary(chunk: Chunk, tokens: int) -> dict:
    return {"doc": chunk.doc, "refs": chunk.refs, "tokens": tokens}


def _estimate_summary(est: Estimate) -> dict:
    return {
        "lines": [
            {"step": l.step, "model": l.model, "calls": l.calls, "usage": asdict(l.usage),
             "cost_usd": round(l.cost_usd, 6)}
            for l in est.lines
        ],
        "subtotal_usd": round(est.subtotal_usd, 6),
        "safety_margin": est.safety_margin,
        "total_usd": round(est.total_usd, 6),
    }
