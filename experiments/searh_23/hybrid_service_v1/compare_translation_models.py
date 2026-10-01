"""Post-completion comparison; input IDs are frozen separately from labels.

Query-sourced-fact counts are syntactic diagnostics, not a faithfulness proof.
Every output is retained for manual denotation/scope audit.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from score_phi_shadow import score

HERE = Path(__file__).resolve().parent


def compare(baseline: Path, candidates: list[Path], output: Path):
    protocol = json.loads((HERE / "dataset/translation_models_v1/protocol.json").read_text(
        encoding="utf-8"))
    ids = protocol["case_ids"]
    report = {"schema": "translation-model-result/1", "protocol": protocol,
              "warning": "Schema and backend derivation do not certify NL meaning.",
              "models": {}}
    for directory in [baseline, *candidates]:
        status = json.loads((directory / "status.json").read_text(encoding="utf-8"))
        if status["state"] != "SUCCEEDED":
            raise ValueError("refusing comparison before all runs complete")
        config = json.loads((directory / "run_config.json").read_text(encoding="utf-8"))
        if config["input_sha256"] != protocol["input_sha256"]:
            raise ValueError("different frozen source inputs")
        records = [json.loads(s) for s in (directory / "results.jsonl").read_text(
            encoding="utf-8").splitlines()]
        if directory == baseline:
            if config["model"] != protocol["baseline"]["model"]:
                raise ValueError("wrong frozen baseline")
            by_id = {r["id"]: r for r in records}
            selected = [by_id[cid] for cid in ids]
        else:
            if config["case_ids"] != ids or [r["id"] for r in records] != ids:
                raise ValueError("candidate did not complete the same IDs in order")
            selected = records
        # Original scorer validates the whole journal before opening gold.
        source_score = score(directory)
        errors = [e for e in source_score["covered_errors"] if e["id"] in ids]
        rows = []
        for r in selected:
            tr = r.get("translation") or {}
            query = tr.get("query")
            facts = tr.get("facts") or []
            suspicious = bool(query and any(f.get("literal") == query and
                any(s.get("source_id") == "target" for s in f.get("sources", []))
                for f in facts))
            atoms = {a["id"]: a for a in tr.get("atoms", [])}
            rows.append({"id": r["id"], "status": r["status"],
                "reason": r["reason"], "relation": r["relation"],
                "query": query, "query_atom": atoms.get((query or {}).get("atom_id")),
                "target_sourced_query_fact": suspicious,
                "transport_failed": r.get("transport_failed", False),
                "cached": r.get("cached", False)})
        report["models"][config["model"]] = {"directory": str(directory),
            "n": len(rows), "schema_valid": sum(r["status"] == "VALID" for r in rows),
            "unsupported": sum(r["reason"] == "unsupported" for r in rows),
            "transport_failed": sum(r["transport_failed"] for r in rows),
            "relations": {rel: sum(r["relation"] == rel for r in rows)
                for rel in ("FOLLOWS", "CONTRADICTS", "INSUFFICIENT")},
            "covered_errors": errors,
            "target_sourced_query_facts": [r["id"] for r in rows if r["target_sourced_query_fact"]],
            "logical_calls": sum(r["usage"]["calls"] for r in selected),
            "logical_tokens": sum(r["usage"]["tokens"] for r in selected),
            "cached_responses": sum(r.get("cached", False) for r in selected),
            "cases": rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--candidates", type=Path, nargs="+", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = compare(args.baseline, args.candidates, args.output)
    print(json.dumps({k: {name: v[name] for name in
        ("n", "schema_valid", "unsupported", "transport_failed", "relations",
         "target_sourced_query_facts", "logical_tokens", "cached_responses")}
        for k, v in result["models"].items()}, ensure_ascii=False, indent=2))
