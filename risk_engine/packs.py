"""Load a domain pack: a folder of configuration and prompt files.

The engine never hard-codes anything about a particular kind of risk.
It reads the taxonomy, scales, checklist and prompts from the pack.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from risk_engine.config import PROJECT_ROOT, ConfigError

PACKS_DIR = PROJECT_ROOT / "packs"
REQUIRED_KEYS = ("name", "taxonomy", "likelihood_scale", "impact_scale", "rating", "files")
REQUIRED_FILES = ("extract_prompt", "synth_prompt", "examples", "checklist")


@dataclass
class Pack:
    name: str
    folder: Path
    config: dict
    extract_prompt: str
    synth_prompt: str
    examples: list = field(default_factory=list)
    checklist: list = field(default_factory=list)

    @property
    def taxonomy_codes(self) -> list[str]:
        return [t["code"] for t in self.config["taxonomy"]]

    @property
    def accepted_file_types(self) -> list[str]:
        return [s.lower() for s in self.config.get("accepted_file_types", [])]

    @property
    def heading_patterns(self) -> list[str]:
        return list((self.config.get("ingest") or {}).get("extra_heading_patterns") or [])

    def extraction_context(self) -> str:
        """Everything that is sent unchanged with every extraction call.

        This block is identical on every call, so it is what gets cached.
        """
        parts = [
            self.extract_prompt.strip(),
            "# Taxonomy\n" + yaml.safe_dump(self.config["taxonomy"], sort_keys=False),
            "# Likelihood scale\n" + yaml.safe_dump(self.config["likelihood_scale"], sort_keys=False),
            "# Impact scale\n" + yaml.safe_dump(self.config["impact_scale"], sort_keys=False),
            "# Checklist\n" + yaml.safe_dump(self.checklist, sort_keys=False),
            "# Worked examples\n" + json.dumps(self.examples, indent=1),
        ]
        return "\n\n".join(parts)


def available_packs() -> list[str]:
    return sorted(p.name for p in PACKS_DIR.iterdir() if (p / "pack.yaml").exists())


def load_pack(name: str, packs_dir: Path | None = None) -> Pack:
    folder = (packs_dir or PACKS_DIR) / name
    pack_file = folder / "pack.yaml"
    if not pack_file.exists():
        raise ConfigError(
            f"Domain pack '{name}' not found (looked for {pack_file}). "
            f"Available packs: {', '.join(available_packs()) or 'none'}"
        )
    with open(pack_file, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    missing = [k for k in REQUIRED_KEYS if k not in config]
    if missing:
        raise ConfigError(f"Pack '{name}' pack.yaml is missing: {', '.join(missing)}")

    paths = {}
    for key in REQUIRED_FILES:
        filename = config["files"].get(key)
        if not filename or not (folder / filename).exists():
            raise ConfigError(f"Pack '{name}' is missing its {key} file ({filename}).")
        paths[key] = folder / filename

    with open(paths["examples"], encoding="utf-8") as f:
        examples = json.load(f).get("examples", [])
    with open(paths["checklist"], encoding="utf-8") as f:
        checklist = (yaml.safe_load(f) or {}).get("items", [])

    for pattern in (config.get("ingest") or {}).get("extra_heading_patterns") or []:
        try:
            re.compile(pattern)
        except re.error as e:
            raise ConfigError(f"Pack '{name}' has a heading pattern that is not valid: {pattern} ({e})")

    codes = {t["code"] for t in config["taxonomy"]}
    for item in checklist:
        if item.get("category") and item["category"] not in codes:
            raise ConfigError(
                f"Pack '{name}' checklist item '{item.get('id')}' uses unknown category {item['category']}."
            )

    return Pack(
        name=config["name"],
        folder=folder,
        config=config,
        extract_prompt=paths["extract_prompt"].read_text(encoding="utf-8"),
        synth_prompt=paths["synth_prompt"].read_text(encoding="utf-8"),
        examples=examples,
        checklist=checklist,
    )
