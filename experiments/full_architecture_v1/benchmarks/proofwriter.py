"""full_architecture_v1 — external benchmark #5: ProofWriter OWA (§29).

tasksource/proofwriter (OWA variants): NL template theory + question +
answer in {True, False, Unknown} — the OWA labels directly test Guardian's
most important distinction (UNKNOWN != FALSE).

Mode A STRUCTURED/ORACLE: the theory's template sentences are translated
DETERMINISTICALLY to Datalog (facts, rules, strong-negation heads) and
solved with Clingo:
  entailed (single stable model, monotonic)  -> TRUE
  negation entailed                          -> FALSE
  neither                                    -> UNKNOWN

Template patterns (the dataset's own closed template grammar — no
benchmark-domain knowledge, just syntax):
  "<Name> is <adj>."            fact  adj(name)
  "<Name> is not <adj>."        fact  -adj(name)
  "If someone is A [and B] then they are [not] C."   rule
  "[A,] B people are [not] C."                      rule (same shape)
  "Everyone who is A is [not] B."                   rule
  "All A people are [not] B."                       rule
Unmatched lines -> ABSTAIN (representability metric).

Mode B NATURAL (theory text -> semantic frontend) deferred like FOLIO
(the reduced frontend has no quantifier machinery; documented).
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
_REPO = _FULLARCH.parents[1]
for p in (str(_BAKEOFF), str(_REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import clingo  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
from huggingface_hub import hf_hub_download  # noqa: E402

OUT = _REPO / "outputs" / "full_architecture_v1" / "proofwriter"
_LABELS = {"True": "TRUE", "False": "FALSE", "Unknown": "UNKNOWN"}

_NAME = r"[A-Z][a-z]+(?: [a-z]+)*"
_RULE_IF = re.compile(
    rf"if (?:someone|something|({_NAME})) is ([a-z]+) and (?:someone|something|\\1 is )?([a-z]+) then (?:he|she|it|they|\\1) (?:is|are) (not )?([a-z]+)\.",
    re.IGNORECASE)
_RULE_IF1 = re.compile(
    rf"if (?:someone|something|({_NAME})) is (not )?([a-z]+) then (?:he|she|it|they|\\1) (?:is|are) (not )?([a-z]+)\.",
    re.IGNORECASE)
_RULE_ADJ = re.compile(
    rf"([a-z]+)(?:, ([a-z]+))? (?:people|persons|things) are (not )?([a-z]+)\.",
    re.IGNORECASE)
_RULE_ALL = re.compile(
    rf"(?:all|every) ([a-z]+)(?:, ([a-z]+))? (?:people|persons|things) are (not )?([a-z]+)\.",
    re.IGNORECASE)
_RULE_EVERYONE = re.compile(
    rf"everyone who is ([a-z]+) is (not )?([a-z]+)\.", re.IGNORECASE)
_FACT = re.compile(rf"({_NAME}) is (not )?([a-z]+)\.", re.IGNORECASE)
_BINARY_FACT = re.compile(
    r"the ([a-z ]+?) ([a-z]+)s the ([a-z ]+?)\.", re.IGNORECASE)


def _pred(adjective: str) -> str:
    return "q_" + re.sub(r"[^a-z0-9_]", "_", adjective.lower())


def _const(name: str) -> str:
    return "n_" + re.sub(r"[^A-Za-z0-9_]", "_", name.lower())


def translate_theory(theory: str) -> tuple[list[str], list[str]]:
    """Return (asp statements, unmatched lines)."""
    statements: list[str] = []
    unmatched: list[str] = []
    for line in theory.split("."):
        line = line.strip()
        if not line:
            continue
        sentence = line if line.endswith(".") else line + "."
        match = _RULE_IF.match(sentence)
        if match:
            subject, a, b, neg, c = match.group(1), match.group(2), \
                match.group(3), match.group(4), match.group(5)
            var = _const(subject) if subject else "X"
            body = [f"{_pred(a)}({var})", f"{_pred(b)}({var})"]
            head = ("-" if neg else "") + _pred(c) + f"({var})"
            statements.append(f"{head} :- {', '.join(body)}.")
            continue
        match = _RULE_IF1.match(sentence)
        if match:
            subject, neg_a, a, neg_c, c = match.group(1), match.group(2), \
                match.group(3), match.group(4), match.group(5)
            var = _const(subject) if subject else "X"
            body = [("-" if neg_a else "") + _pred(a) + f"({var})"]
            head = ("-" if neg_c else "") + _pred(c) + f"({var})"
            statements.append(f"{head} :- {body[0]}.")
            continue
        match = _RULE_ADJ.match(sentence)
        if match:
            a, b, neg, c = match.group(1), match.group(2), match.group(3), \
                match.group(4)
            body = [_pred(a) + "(X)"]
            if b:
                body.append(_pred(b) + "(X)")
            head = ("-" if neg else "") + _pred(c) + "(X)"
            statements.append(f"{head} :- {', '.join(body)}.")
            continue
        match = _RULE_ALL.match(sentence)
        if match:
            a, b, neg, c = match.group(1), match.group(2), match.group(3), \
                match.group(4)
            body = [_pred(a) + "(X)"]
            if b:
                body.append(_pred(b) + "(X)")
            head = ("-" if neg else "") + _pred(c) + "(X)"
            statements.append(f"{head} :- {', '.join(body)}.")
            continue
        match = _RULE_EVERYONE.match(sentence)
        if match:
            a, neg, c = match.group(1), match.group(2), match.group(3)
            head = ("-" if neg else "") + _pred(c) + "(X)"
            statements.append(f"{head} :- {_pred(a)}(X).")
            continue
        match = _BINARY_FACT.match(sentence)
        if match:
            subject, verb, obj = match.group(1), match.group(2), \
                match.group(3)
            atom = _pred(verb) + f"({_const(subject)}, {_const(obj)})"
            statements.append(atom + ".")
            continue
        match = _FACT.match(sentence)
        if match:
            name, neg, adjective = match.group(1), match.group(2), \
                match.group(3)
            atom = ("-" if neg else "") + _pred(adjective) + \
                f"({_const(name)})"
            statements.append(atom + ".")
            continue
        unmatched.append(sentence)
    return statements, unmatched


def translate_question(question: str) -> tuple[str, str] | None:
    """Return (positive atom, negative atom) for a template question."""
    match = _FACT.match(question.strip())
    if not match:
        return None
    name, neg, adjective = match.group(1), match.group(2), match.group(3)
    atom = _pred(adjective) + f"({_const(name)})"
    return atom, "-" + atom


def solve(statements: list[str], question: str) -> str:
    atom, neg_atom = question
    program = "\n".join(statements) + "\n"
    control = clingo.Control(["-t", "2"])
    control.add("base", [], program)
    control.ground([("base", [])])
    models = []
    control.solve(on_model=lambda m: models.append(
        {str(a) for a in m.symbols(atoms=True)}))
    if not models:
        return "INCONSISTENT"
    positive = all(atom in atoms for atoms in models)
    negative = all(neg_atom in atoms for atoms in models)
    if positive and not negative:
        return "TRUE"
    if negative and not positive:
        return "FALSE"
    if positive and negative:
        return "INCONSISTENT"
    return "UNKNOWN"


def main(count: int = 500) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = hf_hub_download(
        "tasksource/proofwriter",
        "data/validation-00000-of-00001-8f79b25dd5b0f2c3.parquet",
        repo_type="dataset")
    table = pq.read_table(path, columns=["id", "theory", "question", "answer"])
    rows = table.to_pylist()
    # label-blind deterministic sample: rank by sha256(id)
    ranked = sorted(rows, key=lambda row: hashlib.sha256(
        row["id"].encode()).hexdigest())[:count]
    results = []
    started = time.time()
    for row in ranked:
        expected = _LABELS.get(row["answer"], "?")
        statements, unmatched = translate_theory(row["theory"])
        question = translate_question(row["question"])
        if unmatched or question is None:
            results.append({"id": row["id"], "expected": expected,
                            "got": "ABSTAIN",
                            "unmatched": unmatched[:2],
                            "question_ok": question is not None})
            continue
        try:
            got = solve(statements, question)
        except Exception as error:
            got = "ABSTAIN"
            results.append({"id": row["id"], "expected": expected, "got": got,
                            "error": f"{type(error).__name__}: "
                                     f"{str(error)[:100]}"})
            continue
        results.append({"id": row["id"], "expected": expected, "got": got})
    correct = sum(1 for r in results if r["got"] == r["expected"])
    evaluated = sum(1 for r in results if r["got"] != "ABSTAIN")
    abstain = len(results) - evaluated
    unknown_expected = [r for r in results if r["expected"] == "UNKNOWN"]
    unknown_got_false = sum(1 for r in unknown_expected
                            if r["got"] == "FALSE")
    payload = {
        "mode": "STRUCTURED/ORACLE (template theory -> Datalog -> Clingo)",
        "sampled": len(results), "deterministic": "sha256(id) rank, "
        "label-blind", "evaluated": evaluated, "correct": correct,
        "abstain": abstain,
        "accuracy_on_representable": round(
            correct / evaluated if evaluated else 0.0, 4),
        "representability_coverage": round(evaluated / len(results), 4),
        "unknown_expected": len(unknown_expected),
        "unknown_collapsed_to_false": unknown_got_false,
        "by_label": {label: {
            "total": sum(1 for r in results if r["expected"] == label),
            "correct": sum(1 for r in results
                           if r["expected"] == label and r["got"] == label)}
            for label in ("TRUE", "FALSE", "UNKNOWN")},
        "mode_b_natural": "DEFERRED to full-model rerun (documented)",
        "wall_time_s": round(time.time() - started, 1),
        "results": results,
    }
    (OUT / "oracle_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k != "results"},
                     indent=1))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=500)
    args = parser.parse_args()
    main(args.count)
