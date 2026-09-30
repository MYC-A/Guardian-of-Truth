"""Render frozen full trajectories in the existing detector's public format.

Inference uses only frozen inputs, never gold. The complete catalog including
structured contract declarations is rendered as text so the baseline sees
the same source information as the integrated Step 2 path.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
FROZEN = HERE / "frozen" / "trajectories_v1"
OUT = HERE / "outputs"


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def render(row: dict) -> dict:
    catalog = []
    for tool in row["available_tools"]:
        catalog.append(f"- {tool['name']} — {tool['description']}")
        for name, data_type in tool["parameters"].items():
            catalog.append(f"    {name}: {data_type}")
        catalog.append("    result_schema: " + _json(tool.get("result_schema", {})))
        if "documented_contracts" in tool:
            catalog.append("    documented_contracts: " + _json(
                tool["documented_contracts"]))
    blocks = ["⟦SYSTEM⟧\n<policy>\n" + row["system_policy"] +
              "\n</policy>\n[AVAILABLE TOOLS]\n" + "\n".join(catalog)]
    for event in row["history"]:
        index = event["index"]
        if event["role"] == "user":
            blocks.append(f"⟦USER · ход {index}⟧\n{event['text']}")
        elif event["role"] == "assistant" and "tool" in event:
            blocks.append(f'⟦ASSISTANT_TOOL_CALL name="{event["tool"]}" '
                          f'call_id="{event["call_id"]}"⟧\n'
                          + _json(event["arguments"]))
        elif event["role"] == "tool":
            blocks.append(f'⟦TOOL_RESULT name="{event["tool"]}" '
                          f'requestor="assistant" call_id="{event["call_id"]}"⟧\n'
                          + _json(event["payload"]))
        elif event["role"] == "assistant":
            blocks.append(f"⟦ASSISTANT · ход {index}⟧\n{event['text']}")
        else:
            raise ValueError(f"unsupported history event at {index}")
    target = row["target_response"]
    if target["role"] != "assistant":
        raise ValueError("target must be an assistant response")
    return {"id": row["case_id"], "prompt": "\n\n".join(blocks) + "\n",
            "response": f"⟦ASSISTANT · ход {target['index']}⟧\n{target['text']}\n"}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for split in ("dev", "sealed"):
        source = FROZEN / f"{split}_inputs.json"
        rows = json.loads(source.read_text(encoding="utf-8"))
        raw = "".join(json.dumps(render(row), ensure_ascii=False) + "\n"
                      for row in rows).encode("utf-8")
        target = OUT / f"existing_detector_{split}_inputs.jsonl"
        if target.exists() and target.read_bytes() != raw:
            raise RuntimeError(f"frozen conversion differs: {target}")
        target.write_bytes(raw)
        print(split, len(rows), hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    main()
