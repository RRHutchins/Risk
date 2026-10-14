"""Tests for the Stage 8 test-and-tune tools, with a fake batch service."""

import csv
import shutil
from pathlib import Path

import pytest

from risk_engine.batch import collect, plan_batch, submit
from risk_engine.cli import _batch_finish
from risk_engine.config import PROJECT_ROOT, load_settings
from risk_engine.testing import compare, evaluate, previous_results, prompt_version, record_results
from tests.fake_claude import FakeBatches, FakeClaude
from tests.test_report_stage56 import all_answers

DEMO = PROJECT_ROOT / "samples" / "demo_tender"
TARGETS = {"quotes_verified_share_min": 0.98, "cost_per_pack_max_usd": 2.0}


@pytest.fixture
def settings(tmp_path):
    s = load_settings()
    s["budget"]["ledger_file"] = str(tmp_path / "ledger.csv")
    s["output_folder"] = str(tmp_path / "outputs")
    s["testing"]["results_file"] = str(tmp_path / "test_results.csv")
    s["simulation"]["iterations"] = 2000
    return s


def row(**kw):
    base = {"records": "10", "excluded": "0", "quotes_verified_share": "1.0", "checklist_all_reported": "True",
            "figures_removed": "0", "total_usd": "0.80", "problem": ""}
    base.update(kw)
    return base


@pytest.mark.parametrize("changes,failed", [
    ({}, None),
    ({"quotes_verified_share": "0.95", "excluded": "1"}, "target_quotes"),
    ({"figures_removed": "2"}, "target_numbers"),
    ({"total_usd": "2.50"}, "target_cost"),
    ({"checklist_all_reported": "False"}, "target_checklist"),
])
def test_targets(changes, failed):
    out = evaluate(row(**changes), TARGETS)
    if failed:
        assert out[failed] == "FAIL" and out["all_targets_met"] == "FAIL"
    else:
        assert out["all_targets_met"] == "PASS"


def test_prompt_version_changes_with_the_prompts(tmp_path, monkeypatch):
    import risk_engine.packs as packs
    shutil.copytree(PROJECT_ROOT / "packs" / "construction_tender", tmp_path / "construction_tender")
    monkeypatch.setattr(packs, "PACKS_DIR", tmp_path)
    before = prompt_version("construction_tender")
    (tmp_path / "construction_tender" / "extract_prompt.md").write_text("A different prompt.")
    assert prompt_version("construction_tender") != before


def test_test_run_records_measures_and_compares(settings, tmp_path, capsys):
    parent = tmp_path / "packs"
    shutil.copytree(DEMO, parent / "Pack A")
    shutil.copytree(DEMO, parent / "Pack B")

    def one_run(label):
        client = FakeClaude(all_answers)
        client.messages.batches = FakeBatches(all_answers, polls_before_done=0)
        job = submit(plan_batch(parent, settings, {}), settings, client, parent, True, True, test_label=label)
        assert _batch_finish(job, settings, client) == 0

    one_run("first")
    one_run("second")
    rows = list(csv.DictReader(open(settings["testing"]["results_file"])))
    assert [r["label"] for r in rows] == ["first", "first", "second", "second"]
    r = rows[0]
    assert r["records"] == "5" and float(r["quotes_verified_share"]) == 1.0     # before merging
    assert r["checklist_items"] == "10" and r["prompt_version"]
    assert r["target_quotes"] == "PASS" and r["target_cost"] == "PASS"
    assert r["target_numbers"] == "FAIL"          # the fake summary writes "7.5", which is removed
    out = capsys.readouterr().out
    assert "Test results (second)" in out and "Pack A: no change" in out


def test_compare_names_changes():
    prev = {"Pack A": {"records": "4", "quotes_verified_share": "1.0", "prompt_version": "aaaa", "P80_pct": "3.4"}}
    lines = compare([{"pack": "Pack A", "records": "6", "quotes_verified_share": "1.0", "prompt_version": "bbbb",
                      "P80_pct": "3.9"}, {"pack": "Pack C"}], prev)
    assert lines[0].startswith("Pack A: prompt version aaaa -> bbbb") and "records 4 -> 6" in lines[0]
    assert lines[1] == "Pack C: first run"
