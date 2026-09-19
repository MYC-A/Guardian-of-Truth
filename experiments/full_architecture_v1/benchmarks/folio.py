"""full_architecture_v1 — external benchmark #4: FOLIO (directive §28).

Yale-LILY/FOLIO (tasksource mirror, validation split): NL premises + GOLD
FOL premises + NL conclusion + GOLD FOL conclusion + label
(True/False/Uncertain).

Mode A ORACLE-FORMAL (directive's primary mode): the gold FOL is the source
of formal meaning — this tests the SOLVER/COMPILER only:

  premises-FOL   ->  ASP program (universal rules; ground facts; strong
                     negation for classical ¬; existentials skolemized;
                     conjunction consequents split into rules;
                     disjunction-in-premises and compound heads = out of
                     the supported fragment -> ABSTAIN, counted)
  conclusion-FOL ->  per-model Kleene 3-valued evaluation over the stable
                     models: v(P)=true if derived, false if -P derived,
                     unknown otherwise
  verdict:  TRUE   iff formula true in ALL models
            FALSE  iff formula false in ALL models
            UNCERTAIN otherwise (Guardian's most important distinction —
            UNKNOWN must not collapse to FALSE; measured explicitly)

Mode B NATURAL (NL -> semantic frontend -> solver) is DEFERRED to the
full-model rerun: the reduced RuleIR frontend has no quantifier machinery
(honest gap per §28, not silently approximated).
"""

from __future__ import annotations

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

def _resolve_folio() -> Path:
    try:
        from huggingface_hub import hf_hub_download
        return Path(hf_hub_download("tasksource/folio",
                                    "folio_v2_validation.jsonl",
                                    repo_type="dataset"))
    except Exception:
        return Path("/home/z/.cache/huggingface/hub/"
                    "datasets--tasksource--folio/snapshots/"
                    "295b95fb4fe9be4ff3f933b73142d142cf6b2c97/"
                    "folio_v2_validation.jsonl")


FOLIO = _resolve_folio()
OUT = _REPO / "outputs" / "full_architecture_v1" / "folio"
_LABELS = {"True": "TRUE", "False": "FALSE", "Uncertain": "UNCERTAIN"}


class FolParseError(Exception):
    pass


_TOKEN = re.compile(r"\s*(∀|∃|¬|∧|∨|⊕|→|↔|\(|\)|,|\.|[A-Za-z0-9_]+)")


def _tokenize(text: str) -> list[str]:
    tokens, pos = [], 0
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match or not match.group(1):
            raise FolParseError(f"lex: {text[pos:pos+20]!r}")
        tokens.append(match.group(1))
        pos = match.end()
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.index = 0

    def peek(self):
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def pop(self):
        token = self.peek()
        self.index += 1
        return token

    def formula(self):
        token = self.peek()
        if token in ("∀", "∃"):
            self.pop()
            var = self.pop()
            if not re.fullmatch(r"[a-z]", var or ""):
                raise FolParseError("bad quantifier variable")
            if self.peek() == ".":
                self.pop()
            return ("quant", token, var, self.formula())
        return self._iff()

    def _iff(self):
        left = self._imp()
        while self.peek() == "↔":
            self.pop()
            left = ("iff", left, self._imp())
        return left

    def _imp(self):
        left = self._or()
        while self.peek() == "→":
            self.pop()
            left = ("imp", left, self._or())
        return left

    def _or(self):
        left = self._and()
        while self.peek() in ("∨", "⊕"):
            operator = self.pop()
            left = (("xor", left, self._and()) if operator == "⊕"
                    else ("or", left, self._and()))
        return left

    def _and(self):
        left = self._not()
        while self.peek() == "∧":
            self.pop()
            left = ("and", left, self._not())
        return left

    def _not(self):
        if self.peek() in ("∀", "∃"):
            return self.formula()
        if self.peek() == "¬":
            self.pop()
            return ("not", self._not())
        return self._atom()

    def _atom(self):
        token = self.peek()
        if token == "(":
            self.pop()
            inner = self.formula()
            if self.pop() != ")":
                raise FolParseError("unbalanced")
            return inner
        if token is None or not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*", token or ""):
            raise FolParseError(f"unexpected {token!r}")
        self.pop()
        if self.peek() == "(":
            self.pop()
            args = []
            if self.peek() != ")":
                while True:
                    term = self.pop()
                    if not term or not re.fullmatch(
                            r"[A-Za-z_][A-Za-z0-9_]*", term):
                        raise FolParseError(f"bad term {term!r}")
                    args.append(term)
                    if self.peek() == ",":
                        self.pop()
                    else:
                        break
            if self.pop() != ")":
                raise FolParseError("unbalanced args")
            return ("pred", token, args)
        return ("pred", token, [])


def parse_fol(text: str):
    parser = _Parser(_tokenize(text))
    node = parser.formula()
    if parser.peek() is not None:
        raise FolParseError("trailing tokens")
    return node


# --------------------------------------------------------------- ASP naming

def _pred(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not cleaned or not re.match(r"[a-z]", cleaned):
        cleaned = "x_" + cleaned
    return "p_" + cleaned


def _term(name: str, variable: bool) -> str:
    if variable:
        return name.upper()
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not cleaned or not re.match(r"[a-z]", cleaned):
        cleaned = "c_" + cleaned
    return cleaned


def _atom_text(node, variables) -> str:
    _, name, args = node
    parts = [_term(t, t in variables) for t in args]
    return _pred(name) + ("(" + ", ".join(parts) + ")" if parts else "")


# ------------------------------------------------------- premise compilation

def compile_premises(node, variables=frozenset(), skolem=0):
    """FOL premise -> list of ASP statements.  Raises FolParseError for the
    unsupported fragment (honest abstention)."""
    kind = node[0]
    if kind == "quant":
        _, which, var, body = node
        if which == "∀":
            return compile_premises(body, variables | {var}, skolem)
        # ∃ in premises: skolemize
        skolem_name = f"sk{skolem}_{var}"
        substituted = _substitute(body, var, skolem_name)
        return compile_premises(substituted, variables - {var}, skolem + 1)
    if kind == "and":
        return compile_premises(node[1], variables, skolem) + \
            compile_premises(node[2], variables, skolem)
    if kind == "iff":
        return (compile_premises(("imp", node[1], node[2]), variables, skolem)
                + compile_premises(("imp", node[2], node[1]), variables, skolem))
    if kind == "imp":
        _, left, right = node
        heads = _consequent_heads(right, variables)
        body = _antecedent_body(left, variables)
        return [f"{head} :- {', '.join(body)}." if body else f"{head}."
                for head in heads]
    if kind == "pred":
        return [_atom_text(node, variables) + "."]
    if kind == "not":
        inner = node[1]
        if inner[0] == "pred":
            return ["-" + _atom_text(inner, variables) + "."]
        raise FolParseError("negation of compound premise unsupported")
    if kind == "or":
        raise FolParseError("disjunctive premise unsupported")
    if kind == "xor":
        raise FolParseError("xor premise unsupported")
    raise FolParseError(f"premise node {kind} unsupported")


def _substitute(node, var, replacement):
    kind = node[0]
    if kind == "pred":
        return ("pred", node[1],
                [replacement if t == var else t for t in node[2]])
    if kind == "quant":
        if node[2] == var:
            return node
        return ("quant", node[1], node[2],
                _substitute(node[3], var, replacement))
    if kind in ("iff", "imp", "or", "and"):
        return (kind, _substitute(node[1], var, replacement),
                _substitute(node[2], var, replacement))
    if kind == "not":
        return ("not", _substitute(node[1], var, replacement))
    return node


def _consequent_heads(node, variables) -> list[str]:
    kind = node[0]
    if kind == "pred":
        return [_atom_text(node, variables)]
    if kind == "not":
        inner = node[1]
        if inner[0] == "pred":
            return ["-" + _atom_text(inner, variables)]
        raise FolParseError("negated compound consequent unsupported")
    if kind == "and":
        return _consequent_heads(node[1], variables) + \
            _consequent_heads(node[2], variables)
    raise FolParseError("compound consequent unsupported")


def _antecedent_body(node, variables) -> list[str]:
    kind = node[0]
    if kind == "pred":
        return [_atom_text(node, variables)]
    if kind == "and":
        return _antecedent_body(node[1], variables) + \
            _antecedent_body(node[2], variables)
    if kind == "not":
        inner = node[1]
        if inner[0] == "pred":
            return ["-" + _atom_text(inner, variables)]
        if inner[0] == "not":
            return _antecedent_body(inner[1], variables)
        raise FolParseError("negated compound antecedent unsupported")
    raise FolParseError("disjunctive/conditional antecedent unsupported")


# ------------------------------------------------------ conclusion evaluation

def _free_vars(node, bound=frozenset()) -> set[str]:
    kind = node[0]
    if kind == "pred":
        return {t for t in node[2] if re.fullmatch(r"[a-z]", t)
                and t not in bound}
    if kind == "quant":
        return _free_vars(node[3], bound | {node[2]})
    if kind in ("iff", "imp", "or", "and"):
        return _free_vars(node[1], bound) | _free_vars(node[2], bound)
    if kind == "not":
        return _free_vars(node[1], bound)
    return set()


def _ground_atoms(node, variables=frozenset()):
    """Collect the ground/variable atom strings of a (mostly) flat formula."""
    kind = node[0]
    if kind == "pred":
        return [_atom_text(node, variables)]
    if kind in ("and", "or", "iff", "imp", "xor"):
        return _ground_atoms(node[1], variables) + \
            _ground_atoms(node[2], variables)
    if kind == "not":
        return _ground_atoms(node[1], variables)
    if kind == "quant":
        return _ground_atoms(node[3], variables | {node[2]})
    return []


def _evaluate(node, model_atoms: set[str], variables=frozenset(),
               constants=frozenset()) -> str:
    """Kleene 3-valued evaluation of the conclusion in ONE model.
    Returns 'TRUE'/'FALSE'/'UNKNOWN'.  Quantifiers ground over the
    Herbrand constants of the row."""
    kind = node[0]
    if kind == "pred":
        atom = _atom_text(node, variables)
        if atom in model_atoms:
            return "TRUE"
        negated = "-" + atom
        if negated in model_atoms:
            return "FALSE"
        return "UNKNOWN"
    if kind == "not":
        value = _evaluate(node[1], model_atoms, variables, constants)
        return {"TRUE": "FALSE", "FALSE": "TRUE",
                "UNKNOWN": "UNKNOWN"}[value]
    if kind == "and":
        left = _evaluate(node[1], model_atoms, variables, constants)
        right = _evaluate(node[2], model_atoms, variables, constants)
        if "FALSE" in (left, right):
            return "FALSE"
        if "UNKNOWN" in (left, right):
            return "UNKNOWN"
        return "TRUE"
    if kind == "or":
        left = _evaluate(node[1], model_atoms, variables, constants)
        right = _evaluate(node[2], model_atoms, variables, constants)
        if "TRUE" in (left, right):
            return "TRUE"
        if "UNKNOWN" in (left, right):
            return "UNKNOWN"
        return "FALSE"
    if kind == "imp":
        left = _evaluate(node[1], model_atoms, variables, constants)
        right = _evaluate(node[2], model_atoms, variables, constants)
        if left == "FALSE" or right == "TRUE":
            return "TRUE"
        if left == "TRUE" and right == "FALSE":
            return "FALSE"
        return "UNKNOWN"
    if kind == "xor":
        left = _evaluate(node[1], model_atoms, variables, constants)
        right = _evaluate(node[2], model_atoms, variables, constants)
        if left == "UNKNOWN" or right == "UNKNOWN":
            return "UNKNOWN"
        return "TRUE" if left != right else "FALSE"
    if kind == "iff":
        left = _evaluate(node[1], model_atoms, variables, constants)
        right = _evaluate(node[2], model_atoms, variables, constants)
        if left == "UNKNOWN" or right == "UNKNOWN":
            return "UNKNOWN"
        return "TRUE" if left == right else "FALSE"
    if kind == "quant":
        _, which, var, body = node
        if not constants:
            # no known individuals: universal is vacuously TRUE, existential
            # has no witness (UNKNOWN under open world)
            return "TRUE" if which == "∀" else "UNKNOWN"
        values = []
        for constant in sorted(constants):
            grounded = _substitute(body, var, constant)
            values.append(_evaluate(grounded, model_atoms, variables - {var},
                                    constants))
        if which == "∀":
            if "FALSE" in values:
                return "FALSE"
            if "UNKNOWN" in values:
                return "UNKNOWN"
            return "TRUE"
        if "TRUE" in values:
            return "TRUE"
        if "UNKNOWN" in values:
            return "UNKNOWN"
        return "FALSE"
    return "UNKNOWN"


def _collect_constants(node, bound=frozenset(), out=None) -> set[str]:
    if out is None:
        out = set()
    kind = node[0]
    if kind == "pred":
        for term in node[2]:
            if term not in bound and re.fullmatch(r"[A-Za-z0-9_]+", term):
                out.add(term)
    elif kind == "quant":
        _collect_constants(node[3], bound | {node[2]}, out)
    elif kind in ("iff", "imp", "or", "and", "xor"):
        _collect_constants(node[1], bound, out)
        _collect_constants(node[2], bound, out)
    elif kind == "not":
        _collect_constants(node[1], bound, out)
    return out


def solve_row(premise_statements: list[str], conclusion_node,
              herbrand_terms: set[str]):
    program = "\n".join(premise_statements)
    control = clingo.Control(["-t", "2"])
    control.add("base", [], program)
    control.ground([("base", [])])
    models = []
    control.solve(on_model=lambda m: models.append(
        {str(a) for a in m.symbols(atoms=True)}))
    if not models:
        return "INCONSISTENT"
    values = [_evaluate(conclusion_node, atoms, constants=herbrand_terms)
              for atoms in models]
    if all(v == "TRUE" for v in values):
        return "TRUE"
    if all(v == "FALSE" for v in values):
        return "FALSE"
    return "UNCERTAIN"


def main(limit: int | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line
            in FOLIO.read_text(encoding="utf-8").splitlines() if line.strip()]
    if limit:
        rows = rows[:limit]
    results = []
    started = time.time()
    for row in rows:
        expected = _LABELS.get(row["label"], "?")
        record = {"example_id": row["example_id"], "expected": expected}
        try:
            premises = [parse_fol(line) for line in
                        row["premises-FOL"].split("\n") if line.strip()]
            conclusion = parse_fol(row["conclusion-FOL"])
        except FolParseError as error:
            record.update({"got": "ABSTAIN", "reason": f"PARSE:{error}"})
            results.append(record)
            continue
        try:
            statements = []
            for premise in premises:
                statements.extend(compile_premises(premise))
            constants = set()
            for premise in premises:
                constants |= _collect_constants(premise)
            constants |= _collect_constants(conclusion)
            # single lowercase letters are quantifier variables, not constants
            constants = {c for c in constants
                         if not re.fullmatch(r"[a-z]", c)}
        except FolParseError as error:
            record.update({"got": "ABSTAIN", "reason": f"FRAGMENT:{error}"})
            results.append(record)
            continue
        try:
            got = solve_row(statements, conclusion, constants)
        except Exception as error:
            record.update({"got": "ABSTAIN",
                           "reason": f"SOLVER:{type(error).__name__}:"
                                      f"{str(error)[:100]}"})
            results.append(record)
            continue
        record.update({"got": got, "reason": "ok"})
        results.append(record)
    correct = sum(1 for r in results if r["got"] == r["expected"])
    abstain = sum(1 for r in results if r["got"] == "ABSTAIN")
    inconsistent = sum(1 for r in results if r["got"] == "INCONSISTENT")
    evaluated = sum(1 for r in results
                    if r["got"] in ("TRUE", "FALSE", "UNCERTAIN"))
    wrong = evaluated - correct
    unknown_collapse = sum(1 for r in results if r["expected"] == "UNCERTAIN"
                           and r["got"] == "FALSE")
    by_label = {}
    for label in ("TRUE", "FALSE", "UNCERTAIN"):
        rows_label = [r for r in results if r["expected"] == label]
        by_label[label] = {
            "total": len(rows_label),
            "correct": sum(1 for r in rows_label if r["got"] == label),
            "got_false": sum(1 for r in rows_label if r["got"] == "FALSE"),
        }
    payload = {
        "mode": "ORACLE-FORMAL (gold FOL -> ASP rules + Kleene 3-valued "
                "conclusion evaluation over stable models)",
        "rows": len(results), "evaluated": evaluated, "correct": correct,
        "wrong": wrong, "abstain": abstain, "inconsistent": inconsistent,
        "accuracy_on_representable": round(
            correct / evaluated if evaluated else 0.0, 4),
        "representability_coverage": round(evaluated / len(results), 4),
        "unknown_collapsed_to_false": unknown_collapse,
        "by_expected_label": by_label,
        "mode_b_natural": "DEFERRED to full-model rerun (no quantifier "
                          "machinery in the reduced RuleIR frontend — "
                          "documented, not approximated)",
        "wall_time_s": round(time.time() - started, 1),
        "results": results,
    }
    (OUT / "oracle_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k != "results"},
                     indent=1))
    from collections import Counter
    print("abstain reasons:",
          Counter(r["reason"].split(":")[0] for r in results
                  if r["reason"] != "ok").most_common(8))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    main(args.limit)
