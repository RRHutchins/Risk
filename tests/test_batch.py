"""Tests for batch mode (Stage 7), with a fake batch service."""

import csv
import json
import shutil
from pathlib import Path

import pytest

from risk_engine.batch import BatchError, collect, plan_batch, read_values, submit, wait
from risk_engine.config import PROJECT_ROOT, load_settings
from risk_engine.costs import Ledger
from tests.fake_claude import FakeBatches, FakeClaude
from tests.test_report_stage56 import all_answers

DEMO = PROJECT_ROOT / "samples" / "demo_tender"


@pytest.fixture
def settings(tmp_path):
    s = load_settings()
    s["budget"]["ledger_file"] = str(tmp_path / "ledger.csv")
    s["output_folder"] = str(tmp_path / "outputs")
    s["simulation"]["iterations"] = 2000
    return s


@pytest.fixture
def parent(tmp_path):
    root = tmp_path / "packs"
    shutil.copytree(DEMO, root / "Pack A")
    shutil.copytree(DEMO, root / "Pack B")
    (root / "Empty pack").mkdir()
    (root / "values.csv").write_text("folder,value\nPack A,2.5m\nPack B,1000000\n")
    return root


def test_batch_end_to_end(settings, parent):
    values = read_values(parent / "values.csv")
    assert values == {"Pack A": 2_500_000, "Pack B": 1_000_000}
    packs = plan_batch(parent, settings, values)
    assert [p.name for p in packs] == ["Empty pack", "Pack A", "Pack B"]
    assert packs[0].problem == "no readable text"

    client = FakeClaude(all_answers)
    client.messages.batches = FakeBatches(all_answers)
    job_dir = submit(packs, settings, client, parent, use_claude=True, merge=True)
    sent = client.messages.batches.submitted
    assert len(sent) == 8 and len({r["custom_id"] for r in sent}) == 8      # 4 pieces x 2 packs
    assert sent[0]["params"]["system"][0]["cache_control"] == {"type": "ephemeral"}

    wait(job_dir, client, poll_seconds=0, progress=lambda m: None)
    summary = collect(job_dir, settings, client, progress=lambda m: None)
    rows = {r["pack"]: r for r in csv.DictReader(open(summary))}
    assert rows["Empty pack"]["problem"] == "no readable text"
    for name in ("Pack A", "Pack B"):
        assert rows[name]["problem"] == "" and Path(rows[name]["report"]).exists()
        assert rows[name]["reviewed"] == "4" and float(rows[name]["quotes_verified_share"]) == 1.0

    batch_rows = [r for r in Ledger(Path(settings["budget"]["ledger_file"])).rows() if r["mode"] == "batch"]
    assert len(batch_rows) == 8
    # batch pricing is half the normal price for the same tokens
    from risk_engine.costs import Usage, price_usage
    u = Usage(input=1200, output=1500, cache_read=0, cache_write=3000)
    assert price_usage("claude-sonnet-5-5", u, settings["pricing"], batch=True) == pytest.approx(
        price_usage("claude-sonnet-5-5", u, settings["pricing"]) / 2)


def test_changed_documents_are_not_mixed_up(settings, parent):
    packs = plan_batch(parent, settings, {})
    client = FakeClaude(all_answers)
    client.messages.batches = FakeBatches(all_answers, polls_before_done=0)
    job_dir = submit(packs, settings, client, parent, use_claude=False, merge=False)
    (parent / "Pack A" / "Site Information.txt").write_text("Changed after sending.")
    summary = collect(job_dir, settings, client, progress=lambda m: None)
    rows = {r["pack"]: r for r in csv.DictReader(open(summary))}
    assert "changed after the batch was sent" in rows["Pack A"]["problem"]
    assert rows["Pack B"]["problem"] == ""


def test_pack_over_cap_is_not_sent(settings, parent):
    settings["budget"]["per_run_cap_usd"] = 0.0001
    packs = plan_batch(parent, settings, {})
    assert all(p.problem for p in packs)
    with pytest.raises(BatchError, match="No packs can be sent"):
        submit(packs, settings, FakeClaude(all_answers), parent, True, True)


def test_bad_values_file(tmp_path):
    f = tmp_path / "v.csv"
    f.write_text("Pack A,lots\n")
    with pytest.raises(BatchError):
        read_values(f)
