"""Behavioral policy benchmark records and scoring for Cycle 2."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


STRUCTURAL_FIELDS = (
    "modality",
    "actor",
    "regulated_kind",
    "facet",
    "target_clauses",
    "relation",
    "condition_literals",
    "exception_literals",
    "temporal",
    "identity",
    "provenance",
    "quantification",
)
OUTCOMES = {"VIOLATION", "PERMITTED", "NO_VIOLATION"}


def _strict_json(text: str) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject(_: str):
        raise ValueError("non-finite JSON number")

    return json.loads(text, object_pairs_hook=unique, parse_constant=reject)


def _keys(value: Any, expected: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == expected


def _literal_atom(literal: str) -> str:
    return literal[1:] if literal.startswith("!") else literal


def clause_matches(clause: Iterable[str], facts: frozenset[str]) -> bool:
    for literal in clause:
        if literal.startswith("!"):
            if literal[1:] in facts:
                return False
        elif literal not in facts:
            return False
    return True


def evaluate_program(program: Mapping[str, Any], facts: Iterable[str]) -> str:
    facts = frozenset(facts)
    if any(clause_matches(clause, facts) for clause in program["violation_clauses"]):
        return "VIOLATION"
    if any(clause_matches(clause, facts) for clause in program["permission_clauses"]):
        return "PERMITTED"
    return "NO_VIOLATION"


def _invert(literal: str) -> str:
    return literal[1:] if literal.startswith("!") else "!" + literal


def compile_typed_structure(structure: Mapping[str, Any]) -> dict[str, list[list[str]]]:
    """Compile the typed IR without access to policy text or benchmark ids."""
    _validate_structure(structure)
    modality = structure["modality"]
    relation = structure["relation"]
    targets = [list(clause) for clause in structure["target_clauses"]]
    conditions = list(structure["condition_literals"])
    exceptions = list(structure["exception_literals"])
    violation: list[list[str]] = []
    permission: list[list[str]] = []

    if modality == "PERMISSION":
        permission = [target + conditions for target in targets]
        if relation in {"ONLY_IF", "IF_AND_ONLY_IF"}:
            violation = [target + [_invert(condition)]
                         for target in targets for condition in conditions]
    elif relation in {"ONLY_IF", "IF_AND_ONLY_IF"}:
        violation = [target + [_invert(condition)]
                     for target in targets for condition in conditions]
    elif relation == "UNLESS":
        violation = [target + [_invert(exception)]
                     for target in targets for exception in exceptions]
    elif modality == "REQUIREMENT" and relation in {"IF", "DURING"}:
        if any(len(target) != 1 for target in targets):
            raise ValueError("conditional requirement target must be atomic")
        violation = [conditions + [_invert(target[0])] for target in targets]
    elif modality == "REQUIREMENT" and relation == "UNCONDITIONAL":
        if any(len(target) != 1 for target in targets):
            raise ValueError("unconditional requirement target must be atomic")
        violation = [[_invert(target[0])] for target in targets]
    elif modality == "PROHIBITION" and relation in {
        "UNCONDITIONAL", "IF", "DURING", "AND_NOT_EACH",
    }:
        violation = [target + conditions + [_invert(item) for item in exceptions]
                     for target in targets]
    else:
        raise ValueError("typed structure relation is not compilable")

    def unique(rows):
        result = []
        for row in rows:
            if row not in result:
                result.append(row)
        return result

    return {"violation_clauses": unique(violation), "permission_clauses": unique(permission)}


@dataclass(frozen=True)
class PolicyWorld:
    id: str
    facts: tuple[str, ...]
    expected: str
    distinguishes: str


@dataclass(frozen=True)
class PolicyCase:
    id: str
    family: str
    variant: str
    source_kind: str
    source_ref: str
    policy: str
    atom_catalog: tuple[str, ...]
    structure: dict[str, Any]
    program: dict[str, tuple[tuple[str, ...], ...]]
    worlds: tuple[PolicyWorld, ...]


@dataclass(frozen=True)
class PolicyDataset:
    schema_version: str
    digest: str
    cases_digest: str
    cases: tuple[PolicyCase, ...]


def _validate_structure(value: Any) -> None:
    if not _keys(value, set(STRUCTURAL_FIELDS)):
        raise ValueError("invalid structural gold")
    if any(not isinstance(value[key], str) for key in STRUCTURAL_FIELDS
           if key not in {"target_clauses", "condition_literals", "exception_literals"}):
        raise ValueError("invalid structural scalar")
    for key in ("condition_literals", "exception_literals"):
        if (not isinstance(value[key], list)
                or any(not isinstance(item, str) or not item for item in value[key])):
            raise ValueError("invalid structural literals")
    if (not isinstance(value["target_clauses"], list) or not value["target_clauses"]
            or any(not isinstance(clause, list) or not clause
                   or any(not isinstance(item, str) or not item for item in clause)
                   for clause in value["target_clauses"])):
        raise ValueError("invalid structural target clauses")


def validate_program(value: Any, atoms: frozenset[str]) -> None:
    if not _keys(value, {"violation_clauses", "permission_clauses"}):
        raise ValueError("invalid policy program")
    for key in ("violation_clauses", "permission_clauses"):
        clauses = value[key]
        if not isinstance(clauses, list):
            raise ValueError("invalid clause array")
        for clause in clauses:
            if (not isinstance(clause, list) or not clause
                    or any(not isinstance(literal, str) or _literal_atom(literal) not in atoms
                           for literal in clause)
                    or len(clause) != len(set(clause))):
                raise ValueError("invalid policy clause")
            positives = {literal for literal in clause if not literal.startswith("!")}
            negatives = {literal[1:] for literal in clause if literal.startswith("!")}
            if positives & negatives:
                raise ValueError("self-contradictory policy clause")


def load_policy_dataset(path: Path) -> PolicyDataset:
    raw = path.read_bytes()
    payload = _strict_json(raw.decode("utf-8"))
    if not _keys(payload, {
        "schema_version", "frozen_before_predictions", "selection_seed", "sources",
        "required_families", "cases_sha256", "cases",
    }):
        raise ValueError("invalid policy dataset envelope")
    if payload["schema_version"] != "guardian-cycle2-policy-cases-v1":
        raise ValueError("unsupported policy dataset")
    if payload["frozen_before_predictions"] is not True:
        raise ValueError("policy cases are not frozen")
    rows = payload["cases"]
    if not isinstance(rows, list) or not 80 <= len(rows) <= 150:
        raise ValueError("policy benchmark requires 80-150 cases")
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if digest != payload["cases_sha256"]:
        raise ValueError("policy case hash mismatch")
    cases = []
    for row in rows:
        expected = {
            "id", "family", "variant", "source_kind", "source_ref", "policy",
            "atom_catalog", "gold",
        }
        if (not _keys(row, expected)
                or any(not isinstance(row[key], str) or not row[key]
                       for key in ("id", "family", "variant", "source_kind", "source_ref", "policy"))
                or not isinstance(row["atom_catalog"], list)
                or len(row["atom_catalog"]) != len(set(row["atom_catalog"]))
                or any(not isinstance(atom, str) or not atom for atom in row["atom_catalog"])):
            raise ValueError("invalid policy case")
        gold = row["gold"]
        if not _keys(gold, {"structure", "program", "worlds"}):
            raise ValueError("invalid policy gold")
        _validate_structure(gold["structure"])
        atoms = frozenset(row["atom_catalog"])
        validate_program(gold["program"], atoms)
        worlds = []
        if not isinstance(gold["worlds"], list) or len(gold["worlds"]) < 4:
            raise ValueError("each case requires at least four distinguishing worlds")
        for world in gold["worlds"]:
            if (not _keys(world, {"id", "facts", "expected", "distinguishes"})
                    or not isinstance(world["id"], str) or not world["id"]
                    or not isinstance(world["distinguishes"], str) or not world["distinguishes"]
                    or not isinstance(world["facts"], list)
                    or any(fact not in atoms for fact in world["facts"])
                    or world["expected"] not in OUTCOMES
                    or evaluate_program(gold["program"], world["facts"]) != world["expected"]):
                raise ValueError("invalid distinguishing world")
            worlds.append(PolicyWorld(
                world["id"], tuple(world["facts"]), world["expected"], world["distinguishes"],
            ))
        program = {
            key: tuple(tuple(clause) for clause in gold["program"][key])
            for key in ("violation_clauses", "permission_clauses")
        }
        cases.append(PolicyCase(
            id=row["id"], family=row["family"], variant=row["variant"],
            source_kind=row["source_kind"], source_ref=row["source_ref"], policy=row["policy"],
            atom_catalog=tuple(row["atom_catalog"]), structure=dict(gold["structure"]),
            program=program, worlds=tuple(worlds),
        ))
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("duplicate policy case id")
    required = set(payload["required_families"])
    actual = {case.family for case in cases}
    if not required <= actual or len(required) < 20:
        raise ValueError("required semantic family missing")
    return PolicyDataset(payload["schema_version"], hashlib.sha256(raw).hexdigest(), digest, tuple(cases))


def score_policy_candidate(case: PolicyCase, structure: Mapping[str, Any], program: Mapping[str, Any]) -> dict:
    """Score structure, frozen-world behavior, and exact representation separately."""
    _validate_structure(structure)
    validate_program(program, frozenset(case.atom_catalog))
    structural = {field: structure[field] == case.structure[field] for field in STRUCTURAL_FIELDS}
    world_rows = []
    for world in case.worlds:
        predicted = evaluate_program(program, world.facts)
        world_rows.append({
            "world_id": world.id,
            "expected": world.expected,
            "predicted": predicted,
            "correct": predicted == world.expected,
        })
    behavioral_accuracy = sum(row["correct"] for row in world_rows) / len(world_rows)
    normalized_program = {
        key: [list(clause) for clause in program[key]]
        for key in ("violation_clauses", "permission_clauses")
    }
    gold_program = {
        key: [list(clause) for clause in case.program[key]]
        for key in ("violation_clauses", "permission_clauses")
    }
    return {
        "structural_fields": structural,
        "structural_accuracy": sum(structural.values()) / len(structural),
        "behavioral_accuracy": behavioral_accuracy,
        "behavioral_semantic_correct": behavioral_accuracy == 1.0,
        "exact_representation": structure == case.structure and normalized_program == gold_program,
        "worlds": world_rows,
    }
