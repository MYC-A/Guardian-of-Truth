"""full_architecture_v1 — external benchmark #1: SafePyramid (directive §25).

bytedance/safepyramid — in-context policy guardrailing: NL rule + multi-turn
conversation -> violated / not violated (PER-RULE protocol, the directive's
preferred mapping to Guardian).

Protocol discipline (directive §24):
  1. ADAPTATION FIXED BEFORE LABELS: this module defines the per-rule
     adapter (rule -> Mistral RuleIR extraction with the SAME semantic
     frontend; conversation -> utterance-observation facts; binding of rule
     refs to utterance anchors via the binder; cautious Clingo core) BEFORE
     any ground-truth set is read.
  2. Sampling is label-blind: deterministic sha256-rank selection of case
     ids per level; rule subsets chosen by hash too.
  3. Inference runs with the N5 arm (full new architecture); predictions
     persist; only then labels load and metrics compute.
  4. Task mismatch reported honestly: SafePyramid conversations are TEXT
     interactions; Guardian's evidence semantics trusts transcript
     utterances as OBSERVED CONVERSATION EVENTS (the fact that something
     was said is transcript-observable; world claims stay CLAIM facts).

Conversation -> facts (structural normalization only):
  * each Chatbot turn  -> ACTION_ATTEMPTED(predicate="utter", entity="conv",
    region=target, value=turn text)  [the speech act happened — observed]
  * each User turn     -> ACTION_ATTEMPTED(predicate="utter", actor="user",
    region=history, value=turn text)
  * both also carry a STATE_OBSERVATION row (predicate=utterance topic is
    NOT inferred; the row value IS the utterance text so condition atoms
    can bind to it)
  Utterance anchors for binding: "utterance_0.." with description = text.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

_FULLARCH = Path(__file__).resolve().parents[1]
_BAKEOFF = _FULLARCH.parent / "core_engine_bakeoff_v1"
_SEMANTIC = _FULLARCH.parent / "semantic_pipeline_v1"
_REPO = _FULLARCH.parents[1]
for p in (str(_BAKEOFF), str(_BAKEOFF / "backends"), str(_FULLARCH),
          str(_REPO / "src"), str(_SEMANTIC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from neutral_types import (  # noqa: E402
    NeutralAtom, NeutralCoreInput, NeutralFact, NeutralInterpretation,
)
from rule_ir import RuleIR  # noqa: E402
from policy.compiler import (  # noqa: E402
    BindingResolution, compile_rule_set,
)
from evidence.clingo_backend import evaluate as clingo_evaluate  # noqa: E402
from certificate.builder import build_certificate  # noqa: E402
from certificate.checker import check_certificate  # noqa: E402

OUT = _REPO / "outputs" / "full_architecture_v1" / "safepyramid"
BENCHMARK = Path("/home/z/.cache/huggingface/hub/"
                 "datasets--ByteDance--SafePyramid/snapshots/"
                 "4baf426ee941ff18e48825addc052cf6453357c6/benchmark.json")
_RULE_LINE = re.compile(r"^\s*(\d+)\.\s+(.+)$", re.DOTALL)
_TURN = re.compile(r"Turn\s+(\d+)\s+-\s+(User|Chatbot)\s*:\s*", re.IGNORECASE)


# ------------------------------------------------------------------ parsing

def parse_rules(policy_text: str) -> dict[int, str]:
    rules: dict[int, str] = {}
    blocks = re.split(r"\n\s*\n", policy_text)
    for block in blocks:
        match = _RULE_LINE.match(block)
        if match:
            rules[int(match.group(1))] = " ".join(
                match.group(2).split())
    return rules


def parse_turns(conversation: str) -> list[dict]:
    marks = list(_TURN.finditer(conversation))
    turns = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) \
            else len(conversation)
        text = conversation[mark.end():end].strip()
        turns.append({"turn": int(mark.group(1)),
                      "role": "user" if mark.group(2).lower() == "user"
                      else "assistant", "text": text})
    return turns


def utterance_facts(turns: list[dict]) -> tuple[tuple[NeutralFact, ...], dict]:
    facts: list[NeutralFact] = []
    anchors: list[dict] = []
    for index, turn in enumerate(turns):
        name = f"utterance_{index}"
        region = "history" if turn["role"] == "user" else "target"
        actor = "user" if turn["role"] == "user" else "assistant"
        facts.append(NeutralFact(
            f"u{index}", "ACTION_ATTEMPTED", actor, "conversation", "utter",
            value=turn["text"][:512], event_index=len(facts) + 1,
            call_id=name, region=region))
        facts.append(NeutralFact(
            f"s{index}", "STATE_OBSERVATION", "system", "conversation",
            name, value=turn["text"][:512], event_index=len(facts) + 1,
            region=region))
        anchors.append({"name": name, "description": turn["text"][:256]})
    return tuple(facts), {"anchors": anchors}


# ---------------------------------------------------------------- sampling

def deterministic_sample(cases: list[dict], per_level: int,
                         seed_namespace: str) -> list[dict]:
    """Label-blind: rank by sha256(id + namespace), take per level."""
    by_level: dict[str, list[dict]] = {}
    for case in cases:
        by_level.setdefault(case["level"], []).append(case)
    out = []
    for level in sorted(by_level):
        ranked = sorted(
            by_level[level],
            key=lambda c: hashlib.sha256(
                (seed_namespace + c["id"]).encode()).hexdigest())
        out.extend(ranked[:per_level])
    return out


# ------------------------------------------------------- frontend (Mistral)

_MISTRAL_CACHE: Path | None = None


def _mistral_extract(rule_text: str, rule_id: str) -> list[RuleIR]:
    """The SAME semantic frontend (semantic_pipeline_v1 Mistral RuleIR
    extraction), payload-keyed cache under this benchmark's output dir."""
    from extractors_mistral import MistralExtractor
    from units import Unit
    cache_path = OUT / "mistral_rule_cache.json"
    extractor = MistralExtractor(cache_path=str(cache_path))
    unit = Unit(unit_id=rule_id, segment_id=rule_id,
                document="prompt", source_type="policy",
                span=(0, len(rule_text)), text=rule_text,
                kind="policy_paragraph")
    rules, _failures = extractor.extract(unit, [])
    return rules


def _bind_to_utterances(rule: RuleIR, anchors: list[dict]) \
        -> dict[str, BindingResolution]:
    """Bind rule refs to utterance anchors (exact string containment first,
    else crossencoder top-4 AMBIGUOUS/BOUND by margin — the same binder)."""
    from binding import Binder
    resolutions: dict[str, BindingResolution] = {}
    texts = [rule.target.text] + [leaf.text for leaf
                                  in (rule.conditions.leaves()
                                      if rule.conditions else [])]
    binder = _get_binder()
    for text in texts:
        if not text:
            continue
        exact = [anchor["name"] for anchor in anchors
                 if text.lower() in anchor["description"].lower()]
        if len(exact) == 1:
            status, names = "BOUND", tuple(exact)
        else:
            names_pool = [anchor["name"] for anchor in anchors]
            descriptions = {anchor["name"]: anchor["description"]
                            for anchor in anchors}
            try:
                result = binder.bind(text, names_pool, descriptions)
                names = tuple(candidate.name for candidate
                              in result.candidates[:4])
                status = result.status if names else "UNKNOWN"
                if status == "BOUND":
                    names = (names[0],)
            except Exception:
                names, status = (), "UNKNOWN"
        resolution = BindingResolution(text, "action", status, names)
        key = rule.target.ref if text == rule.target.text \
            and rule.target.ref != "UNKNOWN" else f"text:{text}"
        resolutions[key] = resolution
        resolutions[f"text:{text}"] = resolution
    return resolutions


_BINDER = None


def _get_binder():
    global _BINDER
    if _BINDER is None:
        from binding import Binder
        _BINDER = Binder()
    return _BINDER


# -------------------------------------------------------------------- eval

def evaluate_rule(turns, anchors, facts, rule_text, rule_id, rule_number):
    rules = _mistral_extract(rule_text, rule_id)
    if not rules:
        ci = NeutralCoreInput(
            case_id=rule_id, facts=facts,
            interpretations=(NeutralInterpretation(
                "i0", (), ("frontend:no-rules-extracted",)),),
            source_refs={}, notes="safepyramid")
        return clingo_evaluate(ci), 0
    resolutions = {}
    for rule in rules:
        for key, resolution in _bind_to_utterances(rule, anchors).items():
            resolutions.setdefault(key, resolution)
    interpretations, _stats = compile_rule_set(rules, resolutions,
                                               case_id=rule_id)
    ci = NeutralCoreInput(
        case_id=rule_id, facts=facts, interpretations=interpretations,
        history_complete=True,
        completeness_basis="benchmark conversation is the complete record",
        source_refs={}, notes="safepyramid per-rule")
    return clingo_evaluate(ci), len(rules)


def main(per_level: int = 4, max_rules_per_case: int = 0,
         run_label: str = "smoke") -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    cases = deterministic_sample(data["data"], per_level,
                                 f"safepyramid-{run_label}-v1")
    predictions_path = OUT / f"predictions__{run_label}.jsonl"
    done: set[tuple[str, int]] = set()
    predictions: list[dict] = []
    if predictions_path.exists():
        for line in predictions_path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            predictions.append(record)
            done.add((record["case_id"], record["rule"]))
    started = time.time()
    with predictions_path.open("a", encoding="utf-8") as handle:
        for case in cases:
            rules = parse_rules(case["policy"])
            if max_rules_per_case:
                ranked = sorted(rules.items(), key=lambda kv: hashlib.sha256(
                    (case["id"] + str(kv[0])).encode()).hexdigest())
                rules = dict(ranked[:max_rules_per_case])
            todo = {number: text for number, text in sorted(rules.items())
                    if (case["id"], number) not in done}
            if not todo:
                continue
            turns = parse_turns(case["conversation"])
            facts, bundle = utterance_facts(turns)
            anchors = bundle["anchors"]
            for number, text in sorted(todo.items()):
                rule_id = f"{case['id']}::r{number}"
                try:
                    result, extracted = evaluate_rule(
                        turns, anchors, facts, text, rule_id, number)
                    status = result.status
                    certificate_digest = None
                    checker_ok = None
                    if status in ("PROVED_ERROR", "PROVED_NO_ERROR"):
                        certificate = build_certificate(case_row_source_refs(
                            case, number), result)
                        checker_ok = check_certificate(
                            certificate, case_row_source_refs(case, number))["ok"]
                        certificate_digest = certificate["certificate_digest"]
                    prediction = 1 if status == "PROVED_ERROR" else 0
                    predictions.append({
                        "case_id": case["id"], "level": case["level"],
                        "domain": case["domain"], "rule": number,
                        "rule_text": text[:160], "status": status,
                        "binary": prediction, "extracted_rules": extracted,
                        "certificate_digest": certificate_digest,
                        "checker_ok": checker_ok,
                        "input_hash": result.input_content_hash})
                    handle.write(json.dumps(predictions[-1], ensure_ascii=False,
                                            sort_keys=True) + "\n")
                    handle.flush()
                except Exception as error:
                    predictions.append({
                        "case_id": case["id"], "level": case["level"],
                        "domain": case["domain"], "rule": number,
                        "status": "ERROR", "binary": 0,
                        "error": f"{type(error).__name__}: {error}"[:200]})
                    handle.write(json.dumps(predictions[-1], ensure_ascii=False,
                                            sort_keys=True) + "\n")
                    handle.flush()
                print(".", end="", flush=True)
    print()
    # ------- labels load ONLY now
    gold = {}
    for case in data["data"]:
        gold[case["id"]] = set(json.loads(case["ground_truth_violations"])
                               if isinstance(case["ground_truth_violations"],
                                             str)
                               else case["ground_truth_violations"])
    metrics = {"per_level": {}, "overall": {}}
    tp = fp = fn = tn = unresolved = 0
    for level in ("L0", "L1", "L2"):
        rows = [p for p in predictions if p["level"] == level]
        ltp = sum(1 for p in rows if p["binary"] == 1
                  and p["rule"] in gold[p["case_id"]])
        lfp = sum(1 for p in rows if p["binary"] == 1
                  and p["rule"] not in gold[p["case_id"]])
        lfn = sum(1 for p in rows if p["binary"] == 0
                  and p["rule"] in gold[p["case_id"]])
        ltn = sum(1 for p in rows if p["binary"] == 0
                  and p["rule"] not in gold[p["case_id"]])
        lunres = sum(1 for p in rows if p["status"] == "UNRESOLVED")
        precision = ltp / (ltp + lfp) if ltp + lfp else 0.0
        recall = ltp / (ltp + lfn) if ltp + lfn else 0.0
        f1 = (2 * precision * recall / (precision + recall)
              if precision + recall else 0.0)
        metrics["per_level"][level] = {
            "pairs": len(rows), "tp": ltp, "fp": lfp, "fn": lfn, "tn": ltn,
            "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4), "unresolved": lunres}
        tp += ltp; fp += lfp; fn += lfn; tn += ltn; unresolved += lunres
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    metrics["overall"] = {
        "pairs": len(predictions), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 4), "recall": round(recall, 4),
        "f1": round(2 * precision * recall / (precision + recall), 4)
        if precision + recall else 0.0,
        "unresolved_rate": round(unresolved / max(len(predictions), 1), 4),
        "extraction_failure_rate": round(
            sum(1 for p in predictions
                if p.get("extracted_rules", 0) == 0)
            / max(len(predictions), 1), 4),
        "run_label": run_label, "per_level_cases": per_level,
        "wall_time_s": round(time.time() - started, 1)}
    (OUT / f"metrics__{run_label}.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(metrics, indent=1))


def case_row_source_refs(case: dict, number: int) -> NeutralCoreInput:
    """Minimal NeutralCoreInput view for certificate checking (source refs
    from the benchmark case: policy text span of the rule)."""
    text = case["policy"]
    start = text.find(f"{number}. ")
    return NeutralCoreInput(
        case_id=f"{case['id']}::r{number}", facts=(),
        interpretations=(),
        source_refs={"r0": {"spans": [{
            "document": "prompt", "start": max(start, 0),
            "end": max(start, 0) + 40, "quote": ""}]}},
        notes="safepyramid certificate view")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-level", type=int, default=4)
    parser.add_argument("--max-rules-per-case", type=int, default=0)
    parser.add_argument("--run-label", default="smoke")
    args = parser.parse_args()
    main(args.per_level, args.max_rules_per_case, args.run_label)
