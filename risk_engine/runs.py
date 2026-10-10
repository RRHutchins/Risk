"""Run identifiers and run folders.

Every run gets a unique ID and its own folder under outputs/. The ID starts
with the date and time (to the microsecond) so folders sort in order, and
ends with a random code so two runs started at the same moment never share
an ID. The folder is created exclusively: if it somehow already exists, a
new ID is drawn rather than overwriting an earlier run.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path


def make_run_id(folder: Path) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in Path(folder).name)[:40]
    return f"{stamp}-{secrets.token_hex(3)}_{safe}"


def create_run_folder(output_root: Path, source_folder: Path) -> tuple[str, Path]:
    """Return a new unique run ID and its freshly created output folder."""
    output_root.mkdir(parents=True, exist_ok=True)
    for _ in range(100):
        run_id = make_run_id(source_folder)
        out_dir = output_root / run_id
        try:
            out_dir.mkdir()
        except FileExistsError:
            continue
        return run_id, out_dir
    raise RuntimeError("Could not create a unique run folder.")
