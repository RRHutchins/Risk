"""Batch mode: review many document packs unattended at half price.

Every pack's extraction requests go to Anthropic's Message Batches service in
one batch (50% of normal prices; results usually within an hour, at most 24
hours). A job file is saved first, so the work survives the window being
closed: resume with the batch-resume command. When the batch has finished,
each pack is checked, calculated and reported exactly as in a single review;
those later steps are small and use normal (immediate) calls.

Spending controls: each pack's estimate must be within the per-run cap, and
the total within the remaining budget, before anything is sent. A batch
cannot be stopped part-way through, so these checks happen up front.
"""

from __future__ import annotations

import csv
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from risk_engine.calc_pipeline import CalculationError, parse_money, run_calculation
from risk_engine.config import resolve_path
from risk_engine.costs import CostGuard, Ledger
from risk_engine.extract import ChunkResult, Extractor, build_schema, system_prompt, user_message
from risk_engine.pipeline import Plan, plan_extraction, save_extraction
from risk_engine.report_pipeline import run_report
from risk_engine.runs import create_run_folder


class BatchError(Exception):
    """A plain-English problem with a batch job."""


@dataclass
class PackPlan:
    name: str
    plan: Plan
    base_value: float | None
    problem: str = ""


def read_values(path: Path | None) -> dict[str, float]:
    """A CSV of folder name, base value (header row optional)."""
    if not path:
        return {}
    values = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) < 2 or not row[0].strip():
                continue
            try:
                values[row[0].strip()] = parse_money(row[1])
            except CalculationError:
                if values or row[0].strip().lower() not in ("folder", "pack", "name"):
                    raise BatchError(f"In {path}: '{row[1]}' for '{row[0]}' is not a value I can read.")
    return values


def pack_folders(parent: Path) -> list[Path]:
    parent = Path(parent).resolve()
    folders = sorted(p for p in parent.iterdir() if p.is_dir() and not p.name.startswith("."))
    if not folders:
        raise BatchError(f"No pack folders found in {parent}. Put each document pack in its own folder inside it.")
    return folders


def plan_batch(parent: Path | list[Path], settings: dict, values: dict[str, float],
               pack_name: str | None = None) -> list[PackPlan]:
    """Plan every pack: the sub-folders of a parent folder, or a list of folders."""
    folders = [Path(f).resolve() for f in parent] if isinstance(parent, list) else pack_folders(parent)
    missing = [str(f) for f in folders if not f.is_dir()]
    if missing:
        raise BatchError("Folder(s) not found: " + "; ".join(missing))
    packs = []
    for folder in folders:
        plan = plan_extraction(folder, settings, pack_name, batch=True)
        problem = ""
        if not plan.chunks:
            problem = "no readable text"
        elif not plan.within_cap:
            problem = f"estimate ${plan.estimate_usd:.2f} is over the per-run cap"
        packs.append(PackPlan(folder.name, plan, values.get(folder.name), problem))
    return packs


def _custom_id(pack_index: int, chunk_index: int) -> str:
    return f"p{pack_index:03d}-c{chunk_index:04d}"


def _fingerprint(plan: Plan) -> str:
    h = hashlib.sha256()
    for c in plan.chunks:
        h.update(c.doc.encode())
        h.update(c.text.encode())
    return h.hexdigest()


def submit(packs: list[PackPlan], settings: dict, client, parent, use_claude: bool, merge: bool,
           test_label: str | None = None) -> Path:
    """Send every pack's extraction requests as one batch; save the job file."""
    to_send = [(i, p) for i, p in enumerate(packs) if not p.problem]
    if not to_send:
        raise BatchError("No packs can be sent (see the problems listed).")
    model = settings["models"]["extraction"]
    cfg = settings.get("extraction", {})
    requests = []
    for i, p in to_send:
        system = system_prompt(p.plan.pack)
        schema = build_schema(p.plan.pack)
        for j, chunk in enumerate(p.plan.chunks):
            requests.append({"custom_id": _custom_id(i, j), "params": {
                "model": model,
                "max_tokens": int(cfg.get("max_output_tokens", 32000)),
                "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": user_message(chunk)}],
                "output_config": {"effort": cfg.get("effort", "medium"),
                                  "format": {"type": "json_schema", "schema": schema}},
            }})
    batch = client.messages.batches.create(requests=requests)
    job_id, job_dir = create_run_folder(resolve_path(settings.get("output_folder", "outputs")), Path("batch"))
    job = {
        "job_id": job_id, "batch_id": batch.id, "model": model, "parent": str(parent),
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "use_claude": use_claude, "merge": merge, "requests": len(requests), "test_label": test_label,
        "packs": [{"index": i, "name": p.name, "folder": str(p.plan.folder), "base_value": p.base_value,
                   "pack": p.plan.pack.name, "chunks": len(p.plan.chunks), "fingerprint": _fingerprint(p.plan),
                   "estimate_usd": round(p.plan.estimate_usd, 6), "problem": p.problem}
                  for i, p in enumerate(packs)],
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2), encoding="utf-8")
    return job_dir


def wait(job_dir: Path, client, poll_seconds: int = 60, progress=print, max_wait_seconds: int | None = None) -> None:
    job = json.loads((Path(job_dir) / "job.json").read_text(encoding="utf-8"))
    start = time.monotonic()
    while True:
        b = client.messages.batches.retrieve(job["batch_id"])
        if b.processing_status == "ended":
            return
        counts = b.request_counts
        done = counts.succeeded + counts.errored + counts.canceled + counts.expired
        progress(f"  {datetime.now():%H:%M}  {done} of {job['requests']} pieces done; still working...")
        if max_wait_seconds is not None and time.monotonic() - start > max_wait_seconds:
            raise BatchError("Still running. Resume later with the batch-resume command.")
        time.sleep(poll_seconds)


def collect(job_dir: Path, settings: dict, client, progress=print) -> Path:
    """Turn finished batch results into the usual outputs for each pack."""
    job_dir = Path(job_dir)
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    results_by_id = {r.custom_id: r for r in client.messages.batches.results(job["batch_id"])}
    ledger = Ledger(resolve_path(settings["budget"]["ledger_file"]))
    rows = []
    for info in job["packs"]:
        row = {"pack": info["name"], "problem": info["problem"]}
        if info["problem"]:
            rows.append(row)
            continue
        started = datetime.now(timezone.utc)
        plan = plan_extraction(Path(info["folder"]), settings, info["pack"], batch=True)
        if len(plan.chunks) != info["chunks"] or _fingerprint(plan) != info["fingerprint"]:
            row["problem"] = "the documents changed after the batch was sent; review this pack again"
            rows.append(row)
            continue
        run_id, out_dir = create_run_folder(resolve_path(settings.get("output_folder", "outputs")), plan.folder)
        guard = CostGuard(plan.cap_usd, settings["pricing"])
        reader = Extractor(None, plan.pack, settings, guard, ledger, run_id)
        pieces = []
        for j, chunk in enumerate(plan.chunks):
            res = ChunkResult(j, chunk.doc, chunk.refs)
            item = results_by_id.get(_custom_id(info["index"], j))
            if item is None or item.result.type != "succeeded":
                kind = "missing" if item is None else item.result.type
                res.status, res.message = "skipped", f"not reviewed: batch request {kind}"
            else:
                msg = item.result.message
                from risk_engine.extract import _usage_from
                usage = _usage_from(msg)
                res.cost_usd = guard.record(job["model"], usage, batch=True)
                res.usage, res.model = usage.__dict__, msg.model
                res.request_id = item.custom_id
                ledger.append(run_id, "batch", f"Extraction {j + 1}", job["model"], usage, actual_usd=res.cost_usd,
                              note=f"{chunk.doc}; batch {job['batch_id']}")
                reader._read_answer(msg, res)
            pieces.append(res)
        finished = datetime.now(timezone.utc)
        ex = save_extraction(plan, settings, pieces, run_id, out_dir, started, finished, "", guard.spent_usd, mode="batch")
        s = ex["summary"]
        row.update({"documents": len(plan.docs), "pieces": s["pieces_total"], "reviewed": s["pieces_reviewed"],
                    "records": s["records_accepted"], "excluded": s["records_excluded"],
                    "quotes_verified_share": s["quotes_verified_share"],
                    "checklist_answered": f"{s['checklist_answered']} of {s['checklist_items']}",
                    "extraction_usd": round(s["actual_usd"], 4), "run_folder": ex["out_dir"]})
        try:
            calc = run_calculation(Path(ex["out_dir"]), settings, info["base_value"], client=client,
                                   merge=job["merge"], progress=lambda m: None, already_spent_usd=s["actual_usd"])
            rep = run_report(Path(calc["out_dir"]), settings, client=client, use_claude=job["use_claude"],
                             already_spent_usd=s["actual_usd"] + calc["audit"]["cost_usd"], progress=lambda m: None)
            b = rep["bundle"]
            c = b["calculation"]["result"]["contingency"]
            checklist = b["extraction"]["checklist"]
            row.update({"pieces_not_reviewed": s["pieces_not_reviewed"],
                        "checklist_items": len(checklist),
                        "checklist_all_reported": all(item["status"] for item in checklist),
                        "figures_removed": len(b["synthesis"].get("removed_figures") or []),
                        "pack_type": b["pack"], "audit": rep["audit"]})
            row.update({"red": b["calculation"]["result"]["ratings"]["red"], "P50_pct": round(c["P50"]["pct"], 3),
                        "P80_pct": round(c["P80"]["pct"], 3), "indicator": b["synthesis"]["indicator"]["label"],
                        "total_usd": b["cost_usd"], "report": rep["report"]})
        except CalculationError as e:
            row["problem"] = str(e)
        row["seconds"] = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
        progress(f"  {info['name']}: {row.get('records', 0)} records, report "
                 f"{'written' if row.get('report') else 'NOT written: ' + row['problem']}")
        rows.append(row)

    summary = job_dir / "batch_summary.csv"
    fields = ["pack", "documents", "pieces", "reviewed", "pieces_not_reviewed", "records", "excluded",
              "quotes_verified_share", "checklist_answered", "checklist_items", "checklist_all_reported",
              "figures_removed", "red", "P50_pct", "P80_pct", "indicator", "extraction_usd", "total_usd",
              "seconds", "problem", "pack_type", "report", "run_folder", "audit"]
    with open(summary, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return summary
