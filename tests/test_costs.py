"""Tests for token counting, pricing, the spending cap and the ledger."""

import pytest

from risk_engine.costs import (CostGuard, Ledger, SpendCapExceeded, Usage, count_tokens_local,
                               estimate_run, price_usage)

PRICING = {
    "model-a": {"input": 2.00, "output": 10.00, "cache_read": 0.20},
    "model-b": {"input": 4.00, "output": 20.00, "cache_read": 0.20},
    "cache_write_multiplier": 1.25,
    "batch_discount": 0.50,
}


def test_token_count_rounds_up():
    assert count_tokens_local("", 3.5) == 0
    assert count_tokens_local("abcdefg", 3.5) == 2      # 7 / 3.5 = 2
    assert count_tokens_local("abcdefgh", 3.5) == 3     # 8 / 3.5 = 2.29 -> 3


def test_price_hand_checked():
    # 1,000,000 input at $2 = $2.00; 100,000 output at $10/M = $1.00
    # 200,000 cache write at $2 x 1.25 = $2.50/M -> $0.50
    # 500,000 cache read at $0.20/M -> $0.10        Total $3.60
    usage = Usage(input=1_000_000, cache_write=200_000, cache_read=500_000, output=100_000)
    assert price_usage("model-a", usage, PRICING) == pytest.approx(3.60)
    assert price_usage("model-a", usage, PRICING, batch=True) == pytest.approx(1.80)


def test_unknown_model_is_an_error():
    with pytest.raises(KeyError):
        price_usage("no-such-model", Usage(input=1), PRICING)


def test_estimate_hand_checked():
    settings = {
        "pricing": PRICING,
        "models": {"extraction": "model-a", "classification": "model-a", "synthesis": "model-b"},
        "estimate": {
            "safety_margin": 0.25, "extraction_output_tokens_per_chunk": 1000,
            "records_per_chunk": 2, "classification_input_tokens_per_record": 100,
            "classification_output_tokens_per_record": 50,
            "synthesis_input_tokens": 10_000, "synthesis_output_tokens": 2_000,
        },
    }
    est = estimate_run([3000, 5000], pack_context_tokens=2000, synth_prompt_tokens=500, settings=settings)
    ext, cls, syn = est.lines
    # Extraction: input 8,000 x $2 = 0.016; cache write 2,000 x $2.50 = 0.005;
    # cache read 2,000 x $0.20 = 0.0004; output 2,000 x $10 = 0.020 -> 0.0414
    assert ext.cost_usd == pytest.approx(0.0414)
    # Classification: 4 records: input 400 x $2 = 0.0008; output 200 x $10 = 0.002 -> 0.0028
    assert cls.cost_usd == pytest.approx(0.0028)
    # Synthesis: input 10,500 x $4 = 0.042; output 2,000 x $20 = 0.040 -> 0.082
    assert syn.cost_usd == pytest.approx(0.082)
    assert est.subtotal_usd == pytest.approx(0.1262)
    assert est.total_usd == pytest.approx(0.1262 * 1.25)


def test_estimate_with_no_documents_is_zero():
    settings = {"pricing": PRICING, "models": {}, "estimate": {"safety_margin": 0.25}}
    assert estimate_run([], 1000, 100, settings).total_usd == 0


def test_cost_guard_stops_before_cap():
    guard = CostGuard(cap_usd=1.00, pricing=PRICING)
    guard.check_before(0.90)  # fine
    guard.record("model-a", Usage(output=80_000))  # $0.80
    assert guard.spent_usd == pytest.approx(0.80)
    with pytest.raises(SpendCapExceeded):
        guard.check_before(0.30)


def test_cost_guard_stops_when_over_cap():
    guard = CostGuard(cap_usd=0.50, pricing=PRICING)
    with pytest.raises(SpendCapExceeded):
        guard.record("model-a", Usage(output=60_000))  # $0.60


def test_ledger_records_and_totals(tmp_path):
    ledger = Ledger(tmp_path / "ledger.csv")
    assert ledger.total_spent_usd() == 0
    ledger.append("run1", "dry-run", "Extraction", "model-a", Usage(input=10), estimated_usd=0.5)
    ledger.append("run2", "live", "Extraction", "model-a", Usage(input=10), actual_usd=0.25)
    ledger.append("run2", "live", "Synthesis", "model-b", Usage(output=10), actual_usd=0.10)
    assert ledger.total_spent_usd() == pytest.approx(0.35)
    assert ledger.run_count() == 2
    assert len(ledger.rows()) == 3


def test_ledger_upgrades_stage1_headings(tmp_path):
    path = tmp_path / "ledger.csv"
    path.write_text(
        "timestamp_utc,run_id,mode,step,model,input_tokens,cache_write_tokens,cache_read_tokens,"
        "output_tokens,estimated_usd,actual_usd,note\n"
        "2026-10-10 10:00:00,old,live,Extraction,m,1,0,0,1,0.1,0.20,\n")
    ledger = Ledger(path)
    ledger.append("new", "live", "Synthesis", "m", actual_usd=0.05)
    assert path.read_text().splitlines()[0].startswith("Time (UTC),Run ID")
    assert ledger.total_spent_usd() == pytest.approx(0.25)
    assert ledger.run_count() == 2


def test_ledger_times_shown_in_local_time():
    from risk_engine.cli import _local_time
    assert _local_time("2026-10-10 10:00:00")[:11] in {"10 Oct 2026", "09 Oct 2026", "11 Oct 2026"}
    assert _local_time("garbled") == "garbled UTC"
