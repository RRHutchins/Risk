"""Stage 9: the generic ISO 31000 pack runs through the whole engine with no
engine code written for it (configuration and prompt files only)."""

from pathlib import Path

import docx
import pytest

from risk_engine.calc_pipeline import run_calculation
from risk_engine.config import PROJECT_ROOT, load_settings
from risk_engine.extract import build_schema
from risk_engine.packs import available_packs, load_pack
from risk_engine.pipeline import plan_extraction, run_extraction
from risk_engine.report_pipeline import run_report
from tests.fake_claude import FakeClaude, record, response

SAMPLE = PROJECT_ROOT / "samples" / "generic_demo"
PACK = load_pack("generic_iso31000")


@pytest.fixture
def settings(tmp_path):
    s = load_settings()
    s["budget"]["ledger_file"] = str(tmp_path / "ledger.csv")
    s["output_folder"] = str(tmp_path / "outputs")
    s["simulation"]["iterations"] = 2000
    return s


def test_both_packs_available_and_valid():
    assert {"construction_tender", "generic_iso31000"} <= set(available_packs())
    schema = build_schema(PACK)
    rec = schema["properties"]["records"]["items"]["properties"]
    assert rec["category"]["enum"] == ["STR", "OPS", "FIN", "CMP", "HSE", "PEO", "TEC", "REP", "EXT"]
    assert rec["flags"]["items"]["enum"] == ["unlimited_exposure"]
    assert "employer" not in (PACK.extract_prompt + PACK.synth_prompt).lower()


def answers(doc, request):
    content = request["messages"][0]["content"]
    if doc:
        return response({"records": [
            record(category="FIN", title="Single funding source", correlation_group="funding", flags=[],
                   quote="The project will be funded entirely by the Lottery grant", suggested_response="reduce",
                   likelihood=2, impact_min=2, impact_likely=8, impact_max=20),
            record(category="CMP", title="Unlimited indemnity to landlord", correlation_group="liability",
                   quote="indemnify it against all losses arising from the use of the building",
                   flags=["unlimited_exposure"], suggested_response="share", likelihood=1,
                   impact_min=1, impact_likely=5, impact_max=40),
            record(type="opportunity", category="OPS", title="Donated surplus food", correlation_group="",
                   quote="Local food businesses may donate surplus stock to the cafe", flags=[],
                   suggested_response="exploit", likelihood=3, impact_min=0.2, impact_likely=1, impact_max=3),
        ], "checklist": [{"id": "budget_and_timescale", "answer": "Grant of GBP 400,000; open by September 2027",
                          "quote": "open a community cafe and training kitchen by September 2027",
                          "source_ref": "1 Objectives"}]})
    if "<records>" in content:
        return response({"groups": []})
    if "<register>" in content:
        return response({"mitigations": [], "asymmetries": [], "clarifications": [], "qualifications": []})
    return response({"headline": "Proceed once the lease indemnity is limited.", "recommendation": "conditional",
                     "rationale": "P80 is {P80_PCT} of the value at risk.", "top_risks": [], "actions": []})


def test_generic_pack_full_review(settings):
    plan = plan_extraction(SAMPLE, settings, pack_name="generic_iso31000")
    assert plan.pack.name == "generic_iso31000" and len(plan.chunks) == 1
    fake = FakeClaude(answers)
    ex = run_extraction(plan, settings, client=fake, progress=lambda m: None)
    assert ex["summary"]["records_accepted"] == 3 and ex["summary"]["quotes_verified_share"] == 1.0
    calc = run_calculation(Path(ex["out_dir"]), settings, 400_000, client=fake, progress=lambda m: None)
    a = calc["audit"]
    assert a["pack"] == "generic_iso31000" and a["base_value_label"] == "Value at risk"
    reds = [r["title"] for r in a["result"]["records"] if r["rating"] == "red"]
    assert reds == ["Unlimited indemnity to landlord"]                  # the pack's own flag forces red
    rep = run_report(Path(calc["out_dir"]), settings, client=fake, progress=lambda m: None)
    b = rep["bundle"]
    assert b["synthesis"]["indicator"]["label"] == "Proceed, with the conditions listed"
    d = docx.Document(rep["report"])
    text = "\n".join(p.text for p in d.paragraphs)
    assert "Risk review: generic_demo" in text and "Overall view" in text
    assert "5. Questions to resolve" in text
    assert "tender" not in text.lower() and "employer" not in text.lower()
