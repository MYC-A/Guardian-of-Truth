#!/usr/bin/env python3
"""GENERIC mutation library for counterexample-guided falsification (§15).

Frozen BEFORE any sealed-suite inference. Every mutation is a mechanical
text/trajectory transformation whose expected invariant is known BY
CONSTRUCTION (§16): no LLM decides the expected result.

Two families:
- POLICY text mutations (rename / swap / flip) with constructive invariants
  over the program signature;
- TRAJECTORY evidence mutations (temporal relocation) with constructive
  invariants over the proof verdict.

No domain vocabulary: mutations operate on placeholders supplied by callers
(entity names, IDs, numbers, connectives) — never on hardcoded nouns.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------
# Policy-text mutations. Each returns (mutated_text, invariant_spec) where
# invariant_spec is machine-checkable:
#   {"kind": "invariance", "rename_map": {...}}
#   {"kind": "flip", "expect": "<what must change>"}
# --------------------------------------------------------------------------

def m_entity_rename(text: str, old: str, new: str) -> tuple[str, dict]:
    """Semantics-preserving rename of an entity noun/ID (§15 entity rename).
    Invariant: program signature identical modulo the rename map."""
    mutated = text.replace(old, new)
    return mutated, {"kind": "invariance", "rename_map": {old: new}}


def m_entity_swap(text: str, a: str, b: str) -> tuple[str, dict]:
    """Swap two distinct entity identifiers (§15 entity swap / ID swap).
    Invariant: scope bindings must change (facts about a != facts about b)."""
    mutated = text.replace(a, "\x00").replace(b, a).replace("\x00", b)
    return mutated, {"kind": "flip", "expect": "entity_scope_binding_changes"}


def m_value_swap(text: str, a: str, b: str) -> tuple[str, dict]:
    """Swap two numeric values (§15 value swap, e.g. 50 <-> 70).
    Invariant: any threshold/scope value referencing them changes."""
    mutated = text.replace(a, "\x00").replace(b, a).replace("\x00", b)
    return mutated, {"kind": "flip", "expect": "numeric_scope_changes"}


def m_temporal_flip(text: str) -> tuple[str, dict]:
    """before <-> after (§15 temporal flip).
    Invariant: the temporal direction of the licensed relation flips."""
    mutated = text.replace(" before ", " \x00 ").replace(" after ", " before ").replace(" \x00 ", " after ")
    return mutated, {"kind": "flip", "expect": "temporal_direction_flips"}


def m_modality_flip(text: str) -> tuple[str, dict]:
    """must <-> may (§15 modality flip).
    Invariant: obligation/permission distinction changes the gate."""
    mutated = (text.replace(" must ", " \x00 ").replace(" may ", " must ")
               .replace(" \x00 ", " may "))
    return mutated, {"kind": "flip", "expect": "modality_changes"}


def m_negation_flip(text: str, predicate_word: str) -> tuple[str, dict]:
    """approved <-> not approved on one predicate word (§15 negation flip).
    Invariant: the required atom value flips."""
    negated = "not " + predicate_word
    if negated in text:
        mutated = text.replace(negated, predicate_word)
    else:
        mutated = text.replace(predicate_word, negated, 1)
    return mutated, {"kind": "flip", "expect": "required_value_flips"}


def m_request_completion_flip(text: str, request_word: str,
                              completion_word: str) -> tuple[str, dict]:
    """request submitted <-> operation completed (§15 request/completion flip).
    Invariant: the strength demanded by the gate differs (REQUESTED vs EXECUTED)."""
    if request_word in text:
        mutated = text.replace(request_word, completion_word)
        expect = "required_strength_changes"
    else:
        mutated = text.replace(completion_word, request_word)
        expect = "required_strength_changes"
    return mutated, {"kind": "flip", "expect": expect}


def m_exception_flip(text: str) -> tuple[str, dict]:
    """unless X <-> if X (§15 exception flip).
    Invariant: exception structure becomes a (co-)requirement."""
    if " unless " in text:
        mutated = text.replace(" unless ", " \x00 ").replace(" if ", " unless ").replace(" \x00 ", " if ")
        # 'unless' present: transform to plain conditional reading
        mutated = text.replace(" unless ", " only in the case of emergency if ")  # noqa: F841
        # simple deterministic form: unless -> if not
        mutated = text.replace(" unless ", " if not ")
    elif " except " in text:
        mutated = text.replace(" except ", " \x00 ")
        mutated = mutated.replace(" if ", " except ").replace(" \x00 ", " if ")
    else:
        mutated = text
    return mutated, {"kind": "flip", "expect": "exception_structure_changes"}


def m_read_write_swap(text: str, read_phrase: str, write_phrase: str) -> tuple[str, dict]:
    """check_state <-> perform_action phrasing (§15 read/write swap).
    Invariant: the governed action binding changes."""
    if read_phrase in text:
        mutated = text.replace(read_phrase, write_phrase)
    else:
        mutated = text.replace(write_phrase, read_phrase)
    return mutated, {"kind": "flip", "expect": "governed_action_or_strength_changes"}


def m_action_rename(text: str, old: str, new: str) -> tuple[str, dict]:
    """Action/tool rename preserving contract description (§15 action rename).
    Invariant: program structure identical modulo the action-name mapping."""
    mutated = text.replace(old, new)
    return mutated, {"kind": "invariance", "rename_map": {old: new}}


# --------------------------------------------------------------------------
# Trajectory-level mutation: temporal evidence relocation (§15).
# Caller supplies the call ids; the mutation moves a result observation
# across the action boundary. Expected verdict change is constructive.
# --------------------------------------------------------------------------

def m_temporal_evidence_relocation(history: list[dict], result_call_id: str,
                                    new_index: int) -> tuple[list[dict], dict]:
    """Move one tool result to a different position relative to the action.
    Invariant: evidence after the action cannot justify the action
    (verdict must not improve from VIOLATION to SATISFIED)."""
    mutated = [dict(e) for e in history]
    idx = [i for i, e in enumerate(mutated)
           if e.get("role") == "tool" and e.get("call_id") == result_call_id]
    if len(idx) != 1:
        return history, {"kind": "noop", "expect": "call_not_found"}
    i = idx[0]
    event = mutated.pop(i)
    mutated.insert(new_index, event)
    return mutated, {"kind": "flip", "expect": "late_evidence_does_not_justify"}


MUTATION_REGISTRY = {
    "entity_rename": m_entity_rename,
    "entity_swap": m_entity_swap,
    "value_swap": m_value_swap,
    "temporal_flip": m_temporal_flip,
    "modality_flip": m_modality_flip,
    "negation_flip": m_negation_flip,
    "request_completion_flip": m_request_completion_flip,
    "exception_flip": m_exception_flip,
    "read_write_swap": m_read_write_swap,
    "action_rename": m_action_rename,
    "temporal_evidence_relocation": m_temporal_evidence_relocation,
}


# --------------------------------------------------------------------------
# Constructive invariant checkers over program signatures.
# --------------------------------------------------------------------------

def apply_rename_to_signature(sig, rename_map: dict):
    """Rewrite a program signature under a semantic rename map (order-free)."""
    if isinstance(sig, tuple):
        return tuple(apply_rename_to_signature(x, rename_map) for x in sig)
    if isinstance(sig, list):
        return [apply_rename_to_signature(x, rename_map) for x in sig]
    if isinstance(sig, str):
        out = sig
        for old, new in rename_map.items():
            out = out.replace(old, new)
        return out
    return sig


def check_invariance(sig_before, sig_after, rename_map: dict) -> dict:
    """RENAME invariance: signatures equal after applying the rename map."""
    expected = apply_rename_to_signature(sig_before, rename_map)
    ok = expected == sig_after
    return {"passed": ok,
            "counterexample": None if ok else {
                "expected_after_rename": str(expected)[:400],
                "observed_after_rename": str(sig_after)[:400],
                "violation": "program structure changed under semantic rename"}}


def check_flip(sig_before, sig_after) -> dict:
    """FLIP sensitivity: signatures must differ somewhere."""
    ok = sig_before != sig_after
    return {"passed": ok,
            "counterexample": None if ok else {
                "violation": "program insensitive to a semantic flip "
                             "that must change meaning",
                "before": str(sig_before)[:400],
                "after": str(sig_after)[:400]}}


def signature_diff_paths(sig_before, sig_after, path="root") -> list[str]:
    """Localize where two program signatures differ (for targeted repair)."""
    if sig_before == sig_after:
        return []
    if isinstance(sig_before, tuple) and isinstance(sig_after, tuple):
        if len(sig_before) == len(sig_after):
            out = []
            for i, (a, b) in enumerate(zip(sig_before, sig_after)):
                out += signature_diff_paths(a, b, f"{path}[{i}]")
            return out if out else [f"{path}:reordered"]
        return [f"{path}:length"]
    if isinstance(sig_before, list) and isinstance(sig_after, list):
        if len(sig_before) == len(sig_after):
            out = []
            for i, (a, b) in enumerate(zip(sig_before, sig_after)):
                out += signature_diff_paths(a, b, f"{path}[{i}]")
            return out if out else [f"{path}:reordered"]
        return [f"{path}:length"]
    return [path]
