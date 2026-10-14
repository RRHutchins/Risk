"""A stand-in for the Claude API, so tests cost nothing and need no key."""

import json
import re
from types import SimpleNamespace


def response(data=None, stop_reason="end_turn", text=None, input_tokens=1200, output_tokens=1500,
             cache_write=0, cache_read=0):
    body = text if text is not None else json.dumps(data or {"records": [], "checklist": []})
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=body)],
        stop_reason=stop_reason, model="claude-sonnet-5-5", _request_id="req_test",
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                              cache_creation_input_tokens=cache_write, cache_read_input_tokens=cache_read))


class _Stream:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class FakeClaude:
    """answers: function(document name, request) -> response object or exception."""

    def __init__(self, answers):
        self.calls = []
        self.messages = SimpleNamespace(stream=self._stream)
        self._answers = answers

    def _stream(self, **request):
        self.calls.append(request)
        found = re.search(r"Document: (.+)", request["messages"][0]["content"])
        return _Stream(self._answers(found.group(1) if found else None, request))


def record(**overrides):
    base = {
        "type": "threat", "category": "LAD", "title": "Uncapped delay damages",
        "description": "Delay damages have no cap.", "source_ref": "Z6 Delay damages (page 2)",
        "quote": "The total of delay damages is not capped.", "likelihood": 3,
        "likelihood_reason": "Tight programme.", "impact_min": 0.5, "impact_likely": 2.0, "impact_max": 8.0,
        "impact_reason": "Several weeks of overrun.", "existing_controls": "None found",
        "suggested_response": "qualify", "correlation_group": "programme", "confidence": "high",
        "confidence_reason": "Explicit wording.", "flags": ["uncapped_delay_damages"],
    }
    base.update(overrides)
    return base


class FakeBatches:
    """Stand-in for client.messages.batches: answers each request with the
    same answer function as FakeClaude, after a set number of status checks."""

    def __init__(self, answers, polls_before_done=1):
        self.answers = answers
        self.submitted = []
        self.polls_left = polls_before_done

    def create(self, requests):
        self.submitted = list(requests)
        return SimpleNamespace(id="msgbatch_test", processing_status="in_progress")

    def retrieve(self, batch_id):
        done = self.polls_left <= 0
        self.polls_left -= 1
        n = len(self.submitted)
        return SimpleNamespace(processing_status="ended" if done else "in_progress",
                               request_counts=SimpleNamespace(succeeded=n if done else 0, errored=0, canceled=0,
                                                              expired=0, processing=0 if done else n))

    def results(self, batch_id):
        for req in self.submitted:
            found = re.search(r"Document: (.+)", req["params"]["messages"][0]["content"])
            yield SimpleNamespace(custom_id=req["custom_id"], result=SimpleNamespace(
                type="succeeded", message=self.answers(found.group(1) if found else None, req["params"])))
