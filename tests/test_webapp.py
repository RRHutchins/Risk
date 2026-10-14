"""Tests for the local web page (Stage 7), driven headlessly."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from risk_engine.config import PROJECT_ROOT

APP = str(PROJECT_ROOT / "risk_engine" / "webapp.py")
DEMO = PROJECT_ROOT / "samples" / "demo_tender"


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_page_loads(no_key):
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "Tender risk review"
    assert any("API key" in m.value for m in at.sidebar.markdown)


def test_estimate_from_folder_path_and_run_blocked_without_key(no_key):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input(key="folder_path").input(str(DEMO))
    at.text_input(key="value").input("2.5m")
    at.button[0].click().run()
    assert not at.exception
    assert [m.label for m in at.metric][:3] == ["Pieces of text to send", "Estimated cost", "Budget remaining"]
    assert at.metric[0].value == "4"
    assert any("No API key found" in e.value for e in at.error)
    run_button = [b for b in at.button if b.label.startswith("Run the review")][0]
    assert run_button.disabled


def test_bad_value_is_reported(no_key):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_input(key="value").input("about two million").run()
    assert any("not a" in e.value and "value" in e.value for e in at.error)


def test_full_run_through_the_page(monkeypatch, tmp_path):
    import risk_engine.config as config
    import risk_engine.pipeline as pipeline
    from tests.fake_claude import FakeClaude
    from tests.test_report_stage56 import all_answers

    real = config.load_settings

    def settings_for_test(path=None):
        s = real(path)
        s["budget"]["ledger_file"] = str(tmp_path / "ledger.csv")
        s["output_folder"] = str(tmp_path / "outputs")
        s["simulation"]["iterations"] = 2000
        return s

    fake = FakeClaude(all_answers)
    monkeypatch.setattr(config, "load_settings", settings_for_test)
    monkeypatch.setattr(pipeline, "make_client", lambda settings: fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    at = AppTest.from_file(APP, default_timeout=120).run()
    at.text_input(key="folder_path").input(str(DEMO))
    at.text_input(key="value").input("2.5m")
    at.button[0].click().run()
    assert not at.error
    [b for b in at.button if b.label.startswith("Run the review")][0].click().run()
    assert not at.exception and not at.error
    labels = [m.label for m in at.metric]
    assert "Bid / no-bid view" in labels and "P80 contingency" in labels
    assert len(fake.calls) >= 6     # 4 pieces + merging + opportunities + summary
    assert len(list((tmp_path / "outputs").rglob("Risk report - *.docx"))) == 1
