import csv
import json

import pytest

from experiments.offline_guardian.preprocess_granite_function_calls import prepare_record, preprocess_csv


def record(prompt: str, response: str = '⟦ASSISTANT_TOOL_CALL name="lookup"⟧\n{"ticket":"A-1"}'):
    return {"id": "case-1", "prompt": prompt, "response": response}


VALID = '''<prompt>
⟦SYSTEM⟧
[AVAILABLE TOOLS]
- lookup — Retrieve a ticket.
    ticket: string! — Ticket id.
⟦USER⟧
old request
⟦USER⟧
latest request</prompt>'''


def test_valid_catalog_and_target_call_preserve_sources():
    prepared = prepare_record(record(VALID))
    assert prepared.row["adapter_status"] == "ready"
    assert prepared.row["prompt"] == "latest request"
    tools = json.loads(prepared.row["tools"])
    assert tools[0]["name"] == "lookup"
    assert tools[0]["parameters"]["ticket"]["type"] == "string"
    assert tools[0]["parameters"]["ticket"] == {"type": "string"}
    assert prepared.trace["target_calls"][0]["source"]["document"] == "response"
    assert prepared.trace["tool_declarations"][0]["fields"][0]["source"]["document"] == "prompt"
    assert prepared.trace["tool_universe_closed"] is False


def test_missing_catalog_is_explicitly_unavailable():
    prepared = prepare_record(record("<prompt>\n⟦USER⟧\nlatest request</prompt>"))
    assert prepared.row["adapter_status"] == "unavailable"
    assert prepared.row["adapter_reason"] == "missing_or_ambiguous_catalog"
    assert prepared.row["tools"] == ""


@pytest.mark.parametrize(("prompt", "reason"), [
    (VALID.replace("⟦USER⟧", "...\n⟦USER⟧", 1), "incomplete_or_truncated_catalog"),
    (VALID.replace("⟦USER⟧\nold request",
                   "⟦SYSTEM⟧\n[AVAILABLE TOOLS]\n- other — Other.\n⟦USER⟧\nold request"),
     "missing_or_ambiguous_catalog"),
])
def test_truncated_or_ambiguous_catalog_is_explicitly_unavailable(prompt, reason):
    prepared = prepare_record(record(prompt))
    assert prepared.row["adapter_status"] == "unavailable"
    assert prepared.row["adapter_reason"] == reason
    assert prepared.trace["parser_issues"]


def test_last_relevant_user_message_is_selected():
    prepared = prepare_record(record(VALID))
    assert prepared.trace["selected_user"]["quote"] == "latest request"


def test_cli_writes_label_free_csv_and_jsonl_trace(tmp_path):
    source = tmp_path / "input.csv"
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "prompt", "response", "label"])
        writer.writeheader()
        writer.writerow({**record(VALID), "label": "1"})
    output, trace = tmp_path / "prepared.csv", tmp_path / "trace.jsonl"
    assert preprocess_csv(source, output, trace) == 1
    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert set(rows[0]) == {"id", "prompt", "response", "tools", "adapter_status", "adapter_reason"}
    assert "label" not in output.read_text(encoding="utf-8")
    trace_row = json.loads(trace.read_text(encoding="utf-8"))
    assert trace_row["status"] == "ready"


def test_cli_accepts_competition_prompt_larger_than_csv_default(tmp_path):
    source = tmp_path / "large.csv"
    large_prompt = VALID.replace("old request", "x" * 140_000)
    with source.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "prompt", "response"])
        writer.writeheader()
        writer.writerow(record(large_prompt))
    output, trace = tmp_path / "prepared.csv", tmp_path / "trace.jsonl"
    assert preprocess_csv(source, output, trace) == 1
    with output.open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["adapter_status"] == "ready"
