"""Run the frozen real-rule A/B/C typed-formalization shadow benchmark."""

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import re
import time

import pandas as pd

from guardian_truth.language import BudgetExceeded, RunBudget
from guardian_truth.llm_client import ChatClient, ChatClientError, ClientConfig
from guardian_truth.runtime import provider_config
from guardian_truth.settings import load_env_file
from guardian_truth.typed_catalog import extract_typed_catalog, select_rule_catalog
from guardian_truth.typed_formalization import (
    canonical_program, distinguishing_witness, render_controlled_text,
    schema_for_catalog, verify_formalization,
)
from guardian_truth.typed_translation import (
    FREE_SCHEMA, build_free_messages, build_typed_messages, normalize_operator,
    parse_free_formalization,
)
from benchmark_claim_relations import AuditedTransport, Pacer


def _json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False,
                      separators=(",", ":"))


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _load(path, parquet, selected):
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not 10 <= len(cases) <= 20:
        raise ValueError("Benchmark must contain 10..20 cases")
    frame = pd.read_parquet(parquet, columns=["id", "prompt"])
    prompts = {row.id: row.prompt for row in frame.itertuples(index=False)}
    wanted = set(selected or [])
    output = []
    for case in cases:
        if wanted and case["case_id"] not in wanted:
            continue
        prompt = prompts[case["row_id"]]
        source = case["source"]
        if prompt[source["start"]:source["end"]] != case["rule"]:
            raise ValueError("Frozen source mismatch")
        whole = extract_typed_catalog(prompt)
        catalog = select_rule_catalog(whole, prompt, source["start"], source["end"])
        output.append((case, catalog))
    if not output or wanted - {case["case_id"] for case, _ in output}:
        raise ValueError("Unknown/empty case selection")
    return payload, output


def _messages(method, case, catalog):
    return (build_free_messages(case["rule"]) if method == "A"
            else build_typed_messages(case["rule"], catalog))


def _parse(method, raw, case, catalog):
    if method == "A":
        program = parse_free_formalization(raw, case["rule"])
        operators = {value for item in program.operators
                     if (value := normalize_operator(item)) is not None}
        features = dict(program.features)
        canonical = {"status": program.status, "relation": program.relation,
                     "effect": program.effect, "formula": re.sub(r"\s+", " ", program.formula).strip(),
                     "predicates": sorted(x.lower() for x in program.predicates),
                     "arguments": sorted(x.lower() for x in program.arguments),
                     "operators": sorted(operators), "features": features}
        return {"status": "VERIFIED" if program.status == "FORMALIZED" else "UNSUPPORTED",
                "relation": program.relation, "effect": program.effect,
                "operators": sorted(operators), "features": features,
                "canonical": canonical, "program": None,
                "roundtrip": program.formula, "error_category": None,
                "argument_relevance": None, "schema_conformant": None}
    result = verify_formalization(raw, catalog)
    program = result.program
    operators = {node.op for node in program.nodes if node.op not in {"REF", "IS_TRUE"}}
    rule_words = set(re.findall(r"[a-z0-9]+", case["rule"].lower()))
    refs = {ref for node in program.nodes for ref in node.refs}
    items = {item.id: item for item in catalog.items}
    relevance = []
    for ref in refs:
        item_words = set(re.findall(r"[a-z0-9]+", str(items[ref].value).replace("_", " ").lower()))
        relevance.append(bool(item_words & rule_words) or items[ref].source.start >= case["source"]["start"])
    canonical = canonical_program(program)
    roundtrip = (render_controlled_text(program, catalog)
                 if program.status == "FORMALIZED" and program.conclusion_root else "UNSUPPORTED")
    return {"status": result.status, "relation": program.relation,
            "effect": program.effect, "operators": sorted(operators),
            "features": asdict(program.features), "canonical": canonical,
            "program": program, "roundtrip": roundtrip,
            "error_category": result.error_category,
            "schema_conformant": result.error_category not in {
                "invalid_json", "duplicate_json_key", "invalid_shape", "invalid_enum",
                "unknown_reference", "unsupported_condition", "duplicate_node"},
            "argument_relevance": (sum(relevance) / len(relevance) if relevance else None)}


def _score(parsed, gold):
    accepted = parsed["status"] == "VERIFIED"
    expected = set(gold["operators"])
    actual = set(parsed["operators"])
    known_expected = {item for item in expected if item in {
        "REF", "IS_TRUE", "FIELD_EQUALS", "VALUE_OF", "IS_PAST", "COUNT",
        "EXISTS", "SAME_ENTITY", "EQ", "NE", "LT", "LE", "GT", "GE",
        "BEFORE", "AFTER", "AND", "OR", "NOT"}}
    lost = sorted(known_expected - actual)
    invented = sorted(actual - expected)
    direction = parsed["relation"] in gold["relations"]
    effect = parsed["effect"] in gold["effects"]
    modality = parsed["features"]["modality"] == gold["features"]["modality"]
    quantifier = parsed["features"]["quantifier"] == gold["features"]["quantifier"]
    causality = parsed["features"]["causality"] == gold["features"]["causality"]
    strength = parsed["features"]["strength"] == gold["features"]["strength"]
    condition = parsed["features"]["condition"] == gold["features"]["condition"]
    predicted_negation = "NOT" in actual or parsed["effect"] == "PROHIBITED"
    negation = predicted_negation == gold["features"]["negation"]
    if gold["supported_by_fragment"]:
        semantic = accepted and direction and effect and not lost and modality and negation
    else:
        semantic = not accepted
    overlap = len(actual & known_expected)
    return {"accepted": accepted, "semantic_correct": semantic,
            "false_verified": accepted and not gold["supported_by_fragment"],
            "direction_correct": direction, "effect_correct": effect,
            "modality_correct": modality, "quantifier_correct": quantifier,
            "causality_correct": causality, "strength_correct": strength,
            "condition_feature_correct": condition,
            "negation_correct": negation, "lost_operators": lost,
            "invented_operators": invented,
            "operator_precision": overlap / len(actual) if actual else (1.0 if not known_expected else 0.0),
            "operator_recall": overlap / len(known_expected) if known_expected else 1.0}


def _mean(rows, name):
    values = [row[name] for row in rows if row.get(name) is not None]
    return sum(values) / len(values) if values else None


def summarize(records, catalogs):
    by_method = {}
    for method in ("A", "B", "C"):
        rows = [row for row in records if row["method"] == method]
        valid = [row for row in rows if row["transport_status"] == "valid"]
        accepted = [row for row in valid if row["accepted"]]
        by_method[method] = {
            "attempted": len(rows), "valid": len(valid), "accepted": len(accepted),
            "acceptance_coverage": len(accepted) / len(rows) if rows else None,
            "semantic_correct_all": sum(row["semantic_correct"] for row in valid),
            "semantic_accuracy_all": sum(row["semantic_correct"] for row in valid) / len(rows) if rows else None,
            "semantic_accuracy_accepted": _mean(accepted, "semantic_correct"),
            "false_verified": sum(row["false_verified"] for row in valid),
            "false_verified_rate": _mean(accepted, "false_verified"),
            "direction_accuracy": _mean(valid, "direction_correct"),
            "effect_accuracy": _mean(valid, "effect_correct"),
            "operator_precision": _mean(valid, "operator_precision"),
            "operator_recall": _mean(valid, "operator_recall"),
            "negation_accuracy": _mean(valid, "negation_correct"),
            "modality_accuracy": _mean(valid, "modality_correct"),
            "quantifier_accuracy": _mean(valid, "quantifier_correct"),
            "causality_accuracy": _mean(valid, "causality_correct"),
            "strength_accuracy": _mean(valid, "strength_correct"),
            "condition_feature_accuracy": _mean(valid, "condition_feature_correct"),
            "argument_relevance": _mean(valid, "argument_relevance"),
            "schema_conformance": _mean(valid, "schema_conformant"),
            "schema_violations": sum(row.get("schema_conformant") is False for row in valid),
            "status_counts": dict(Counter(row.get("formal_status") or row["transport_status"] for row in rows)),
        }
    groups = defaultdict(list)
    for row in records:
        groups[(row["method"], row["case_id"])].append(row)
    stability = {}
    for (method, case_id), rows in sorted(groups.items()):
        valid = [row for row in rows if row["transport_status"] == "valid"]
        semantic_stable = None
        if method in {"B", "C"} and len(valid) > 1:
            programs = [row.get("_program") for row in valid if row.get("_program") is not None
                        and row["formal_status"] == "VERIFIED"]
            if len(programs) == len(valid):
                catalog = catalogs[case_id]
                semantic_stable = all(not distinguishing_witness(programs[0], item, catalog).ambiguous
                                      for item in programs[1:])
        stability[f"{method}:{case_id}"] = {
            "runs": len(rows), "valid": len(valid),
            "same_status": len({row.get("formal_status") for row in valid}) <= 1 if valid else None,
            "same_raw": len({row.get("raw_sha256") for row in valid}) <= 1 if valid else None,
            "same_canonical": len({row.get("canonical_sha256") for row in valid}) <= 1 if valid else None,
            "same_solver_meaning": semantic_stable,
        }
    return {"by_method": by_method, "stability": stability,
            "interpretation": {
                "VERIFIED": "schema, catalog references, types and source links verified; semantic equivalence is not proven",
                "semantic_correct": "agreement with frozen high-level meaning; operator coverage is limited to the implemented fragment",
                "argument_relevance": "lexical/schema-linking diagnostic, not semantic argument correctness",
            }}


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--input", type=Path, required=True)
    value.add_argument("--parquet", type=Path, required=True)
    value.add_argument("--env-file", type=Path, required=True)
    value.add_argument("--provider", choices=("groq", "openrouter", "gemini"), required=True)
    value.add_argument("--model", required=True)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--method", choices=("A", "B", "C"), action="append")
    value.add_argument("--case-id", action="append")
    value.add_argument("--repetitions", type=int, default=3)
    value.add_argument("--interval-seconds", type=float, default=15)
    value.add_argument("--max-output-tokens", type=int, default=2048)
    value.add_argument("--max-requests", type=int, default=200)
    value.add_argument("--seconds", type=float, default=7200)
    value.add_argument("--max-input-chars", type=int, default=5_000_000)
    value.add_argument("--retries", type=int, default=1)
    return value


def main(argv=None):
    args = parser().parse_args(argv)
    if args.output_dir.exists() or not 3 <= args.repetitions <= 5:
        raise SystemExit("Use a new output directory and 3..5 repetitions")
    methods = tuple(dict.fromkeys(args.method or ("A", "B", "C")))
    benchmark, cases = _load(args.input, args.parquet, args.case_id)
    load_env_file(args.env_file)
    initial = ClientConfig.from_env()
    base_url = initial.base_url if args.provider == "groq" else None
    config = provider_config(initial, args.provider, model=args.model, base_url=base_url)
    config = replace(config, max_output_tokens=args.max_output_tokens,
                     max_retries=args.retries, strict_schema=True)
    ChatClient(config).validate_configuration()
    budget = RunBudget(args.max_requests, args.max_input_chars, args.seconds)
    pacer = Pacer(args.interval_seconds)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    catalogs = {case["case_id"]: catalog for case, catalog in cases}
    config_record = {"provider": args.provider, "model": config.model,
                     "methods": methods, "cases": [case["case_id"] for case, _ in cases],
                     "repetitions": args.repetitions, "interval_seconds": args.interval_seconds,
                     "benchmark_sha256": _hash(benchmark),
                     "response_formats": {"A": "free-content schema, strict=false",
                                          "B": "typed schema, strict=false",
                                          "C": "same typed schema, strict=true"},
                     "scope": "shadow real-rule translation; no row labels changed"}
    (args.output_dir / "configuration.json").write_text(
        json.dumps(config_record, indent=2), encoding="utf-8")
    with (args.output_dir / "catalogs.jsonl").open("x", encoding="utf-8") as stream:
        for case, catalog in cases:
            stream.write(_json({"case_id": case["case_id"], "catalog": catalog.to_dict()}) + "\n")
    records = []
    with (args.output_dir / "attempts.jsonl").open("x", encoding="utf-8") as attempts, \
         (args.output_dir / "calls.jsonl").open("x", encoding="utf-8") as calls:
        audited = AuditedTransport(attempts, pacer, budget)
        loose_client = ChatClient(replace(config, strict_schema=False), transport=audited)
        strict_client = ChatClient(config, transport=audited)
        exhausted = False
        for repetition in range(1, args.repetitions + 1):
            for case, catalog in cases:
                for method in methods:
                    row = {"case_id": case["case_id"], "method": method,
                           "repetition": repetition, "transport_status": "budget_exceeded",
                           "formal_status": None, "error_category": None,
                           "raw_response": None, "usage": {}, "response_model": None}
                    before = budget.requests
                    started = time.monotonic()
                    try:
                        if exhausted:
                            raise BudgetExceeded("Run budget exhausted")
                        audited.case_id = f"{method}:{case['case_id']}::r{repetition}"
                        schema = FREE_SCHEMA if method == "A" else schema_for_catalog(catalog)
                        client = strict_client if method == "C" else loose_client
                        completion = client.complete(_messages(method, case, catalog),
                                                     schema=schema, budget=budget)
                        row["raw_response"] = completion.content
                        row["response_model"] = completion.model
                        row["usage"] = {key: value for key, value in completion.usage.items()
                                        if key in {"prompt_tokens", "completion_tokens", "total_tokens"}}
                        parsed = _parse(method, completion.content, case, catalog)
                        score = _score(parsed, case["gold"])
                        row.update(score, transport_status="valid", formal_status=parsed["status"],
                                   error_category=parsed["error_category"],
                                   raw_sha256=hashlib.sha256(completion.content.encode()).hexdigest(),
                                   canonical_sha256=_hash(parsed["canonical"]),
                                   roundtrip_sha256=hashlib.sha256(parsed["roundtrip"].encode()).hexdigest(),
                                   operators=parsed["operators"], features=parsed["features"],
                                   argument_relevance=parsed["argument_relevance"],
                                   schema_conformant=parsed["schema_conformant"])
                        row["_program"] = parsed["program"]
                    except (ValueError, TypeError, RecursionError) as error:
                        row.update(transport_status="invalid_output",
                                   error_category=str(error)[:80])
                    except BudgetExceeded:
                        exhausted = True
                        row.update(transport_status="budget_exceeded", error_category="budget_exceeded")
                    except ChatClientError as error:
                        row.update(transport_status="api_error", error_category=error.category)
                    row["http_attempts_reserved"] = budget.requests - before
                    row["elapsed_seconds"] = max(0, time.monotonic() - started)
                    persisted = {key: value for key, value in row.items() if key != "_program"}
                    calls.write(_json(persisted) + "\n"); calls.flush()
                    records.append(row)
                    print(_json({"case": case["case_id"], "method": method,
                                 "repetition": repetition, "transport": row["transport_status"],
                                 "formal": row["formal_status"]}), flush=True)
    report = summarize(records, catalogs)
    report["budget"] = budget.summary()
    report["configuration"] = config_record
    (args.output_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(_json({"output_dir": str(args.output_dir), "by_method": report["by_method"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
