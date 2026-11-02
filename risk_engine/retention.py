"""Delete old run results so client documents are not kept longer than needed.

Run folders under outputs/ hold extracts and quotes from the documents that
were reviewed, and outputs/uploads holds copies of files dragged onto the web
page. Data protection law says personal data must not be kept longer than
needed, so this module finds folders older than the retention period (set in
config/settings.yaml) and deletes them.

A folder's age is taken from the newest file inside it, so a run that was
re-reported recently is kept.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from risk_engine.config import resolve_path

UPLOADS = "uploads"
DEFAULT_KEEP_DAYS = 90


@dataclass
class OldFolder:
    path: Path
    age_days: float


def keep_days(settings: dict) -> int:
    return int((settings.get("retention") or {}).get("keep_days", DEFAULT_KEEP_DAYS))


def _newest_mtime(folder: Path) -> float:
    newest = folder.stat().st_mtime
    for p in folder.rglob("*"):
        try:
            newest = max(newest, p.stat().st_mtime)
        except OSError:
            continue
    return newest


def find_old_folders(output_root: Path, days: int, now: float | None = None) -> list[OldFolder]:
    """Run folders and upload folders whose newest file is older than `days`."""
    now = time.time() if now is None else now
    output_root = Path(output_root)
    if not output_root.exists():
        return []
    candidates = [p for p in output_root.iterdir() if p.is_dir() and p.name != UPLOADS]
    uploads = output_root / UPLOADS
    if uploads.is_dir():
        candidates += [p for p in uploads.iterdir() if p.is_dir()]
    old = []
    for folder in sorted(candidates):
        age = (now - _newest_mtime(folder)) / 86400
        if age > days:
            old.append(OldFolder(folder, age))
    return old


def delete_folders(folders: list[OldFolder], output_root: Path) -> int:
    """Delete the given folders. Refuses anything outside the output folder."""
    root = Path(output_root).resolve()
    deleted = 0
    for f in folders:
        target = f.path.resolve()
        if root not in target.parents:
            raise ValueError(f"Refusing to delete {target}: it is not inside {root}.")
        shutil.rmtree(target)
        deleted += 1
    return deleted


def output_root(settings: dict) -> Path:
    return resolve_path(settings.get("output_folder", "outputs"))
