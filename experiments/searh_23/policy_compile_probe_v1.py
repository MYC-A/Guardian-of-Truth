"""Source-covered Mistral policy normalization into the narrow micrograph IR.

The model sees one policy, no examples, trace, or labels. Every source bullet
must be accounted for. Unsupported or structurally invalid translations stay
visible and force UNKNOWN in the downstream certificate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build_policy_language_v1 import BASE, OUT, POLICIES, ROOT
from micrograph_certificate_v1 import _bullets, analyze, compile_policy
from tq_questions import Mistral


SYSTEM = """Translate EVERY source policy bullet into this restricted English rule format. Return JSON only:
{"entries":[{"source_id":0,"source_quote":"exact original bullet","canonical_bullets":["complete standalone rule"],"unsupported":false}, ...]}.
Use one entry per source bullet in original order. Do not drop, merge, or invent a source bullet. A source bullet may yield two canonical bullets if it requires both a prerequisite and a latest-result modifier. If ANY restriction or exception in the source bullet cannot be expressed by the allowed forms, set unsupported=true and canonical_bullets=[] for that whole bullet. Do not approximate or weaken a rule.
Only these full bullet forms are allowed:
1. Before <verb-ing> any <object>, check that the <topic> is <positive-state> for the SAME <entity>. A check for a different <entity> does not satisfy this condition.
2. Use the latest <topic>-check result for that <entity>. An earlier <positive-state> result cannot override a later <negative-state> result.
3. After a <object> has been <past-participle> successfully, record a <kind> audit for the SAME <entity>. Do not record the audit before successful <action-noun>.
Replace bracketed slots with words actually supported by the source. Preserve every condition, exception, entity and ordering requirement. If a rule mentions a condition for which none of these forms is exact, mark that whole source bullet unsupported. Return no verdict; do not inspect tool histories or labels."""


CRITICAL = {"supervisor", "manager", "approval", "authorization", "identity",
            "confirmation", "consent", "amount", "fee", "inventory", "stock"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def frozen(suite: str) -> dict:
    source = OUT / suite / "input.json"
    manifest = json.loads((BASE / suite / "manifest.json").read_text(encoding="utf-8"))
    if digest(source) != manifest["input_sha256_lf"]:
        raise ValueError("frozen input changed")
    data = json.loads(source.read_text(encoding="utf-8"))
    policies = {item["policy"] for item in data["inputs"]}
    if len(policies) != 1:
        raise ValueError("expected exactly one policy per suite")
    policy = next(iter(policies))
    bullets = _bullets(policy)
    if not bullets:
        raise ValueError("source policy cannot be segmented")
    return {"data": data, "policy": policy, "bullets": bullets,
            "input_sha256_lf": digest(source), "system_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest()}


def validate_translation(source_bullets: list[str], answer: dict) -> tuple[str, list[str]]:
    entries = answer.get("entries")
    if not isinstance(entries, list) or len(entries) != len(source_bullets):
        return "", ["source_coverage_failed"]
    canonical: list[str] = []
    errors: list[str] = []
    for index, (source, entry) in enumerate(zip(source_bullets, entries)):
        if not isinstance(entry, dict) or entry.get("source_id") != index or entry.get("source_quote") != source:
            errors.append(f"source_anchor_invalid:{index}")
            canonical.append(source)
            continue
        proposed = entry.get("canonical_bullets")
        unsupported = entry.get("unsupported")
        if unsupported is True:
            if proposed != []:
                errors.append(f"unsupported_with_output:{index}")
            canonical.append(source)
            continue
        if unsupported is not False or not isinstance(proposed, list) or not proposed or not all(isinstance(p, str) for p in proposed):
            errors.append(f"proposal_shape_invalid:{index}")
            canonical.append(source)
            continue
        segment = "# Repair desk policy\n" + "\n".join("- " + p for p in proposed)
        _, grammar_errors = compile_policy(segment)
        if grammar_errors:
            errors.append(f"canonical_grammar_invalid:{index}")
            canonical.append(source)
            continue
        source_lower = source.lower()
        canonical_lower = " ".join(proposed).lower()
        dropped = sorted(token for token in CRITICAL
                         if token in source_lower and token not in canonical_lower)
        if dropped:
            errors.append(f"critical_constraint_dropped:{index}:{','.join(dropped)}")
            canonical.append(source)
            continue
        canonical.extend(proposed)
    return "# Repair desk policy\n" + "\n".join("- " + row for row in canonical), errors


def run(suite: str) -> dict:
    source = frozen(suite)
    output = OUT / suite / "translation.json"
    if output.exists():
        raise ValueError("translation already exists; never overwrite a model result")
    model = Mistral()
    result = model.ask(SYSTEM, json.dumps({"policy_bullets": [
        {"source_id": index, "source_quote": quote}
        for index, quote in enumerate(source["bullets"])]}, ensure_ascii=False), max_tokens=1800)
    record = {"suite": suite, "input_sha256_lf": source["input_sha256_lf"],
              "system_sha256": source["system_sha256"], "answer": result["value"],
              "finish_reason": result["finish_reason"], "usage": result["usage"]}
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"suite": suite, "finish_reason": record["finish_reason"], "usage": record["usage"]}


def score(suite: str) -> dict:
    source = frozen(suite)
    output = OUT / suite / "translation.json"
    record = json.loads(output.read_text(encoding="utf-8"))
    if record["input_sha256_lf"] != source["input_sha256_lf"] or record["system_sha256"] != source["system_sha256"]:
        raise ValueError("translation source or prompt mismatch")
    seal = {"input_sha256_lf": source["input_sha256_lf"],
            "translation_sha256_lf": digest(output), "suite": suite}
    seal_path = OUT / suite / "prediction_seal.json"
    payload = json.dumps(seal, indent=2) + "\n"
    if seal_path.exists() and seal_path.read_text(encoding="utf-8") != payload:
        raise ValueError("translation seal differs")
    seal_path.write_text(payload, encoding="utf-8")
    policy, errors = validate_translation(source["bullets"], record["answer"])
    gold = json.loads((BASE / suite / "expected.json").read_text(encoding="utf-8"))
    counts = dict(TP=0, FP=0, FN=0, TN=0, UNKNOWN_POS=0, UNKNOWN_NEG=0)
    per_case = []
    for item in source["data"]["inputs"]:
        modified = {**item, "policy": policy}
        analysis = analyze(modified) if policy and record["finish_reason"] == "stop" else {"verdict": "UNKNOWN", "errors": ["model_result_invalid"]}
        verdict = analysis["verdict"]
        expected = gold[item["id"]]
        bucket = ("UNKNOWN_POS" if expected else "UNKNOWN_NEG") if verdict == "UNKNOWN" else (
            "TP" if expected else "FP") if verdict == "VIOLATION" else ("FN" if expected else "TN")
        counts[bucket] += 1
        per_case.append({"id": item["id"], "gold": expected, "verdict": verdict,
                         "bucket": bucket, "errors": analysis.get("errors", []),
                         "checks": analysis.get("checks", [])})
    report = {"suite": suite, "scope": "authored policy paraphrases; development only",
              "seal": seal, "translation_errors": errors, "canonical_policy": policy,
              "counts": counts, "per_case": per_case}
    (OUT / suite / "score.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"suite": suite, "translation_errors": errors, "counts": counts}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("run", "score"))
    parser.add_argument("suite", choices=tuple(POLICIES))
    args = parser.parse_args()
    print(json.dumps(run(args.suite) if args.phase == "run" else score(args.suite), ensure_ascii=False))


if __name__ == "__main__":
    main()
