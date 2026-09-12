"""Controlled long-policy document assembly experiment.

This evaluates whether required policy spans survive each assembly strategy. It
does not substitute span inclusion for semantic understanding by an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class DocumentCase:
    id: str
    policy: str
    query: str
    required_markers: tuple[str, ...]
    definition_markers: tuple[str, ...] = ()
    exception_markers: tuple[str, ...] = ()
    reference_markers: tuple[str, ...] = ()


def controlled_cases() -> tuple[DocumentCase, ...]:
    base = (
        "# Definitions\nDEF-OWNER: owner means the account holder.\n\n"
        "# General rules\nRULE-AUTH: Before closing an account, verify the owner.\n\n"
        "# Exceptions\nEXC-DECEASED: Except when a verified estate executor presents probate.\n\n"
        "# References\nREF-CLOSE: Account closure follows RULE-AUTH and EXC-DECEASED."
    )
    distractor = "General information about statements, cards, rewards, and notifications."
    cases = []
    for length in (0, 20, 80):
        pads = [f"## Note {index}\n{distractor} Item {index}." for index in range(length)]
        for position in ("start", "middle", "end"):
            if position == "start":
                sections = [base, *pads]
            elif position == "middle":
                pivot = len(pads) // 2
                sections = [*pads[:pivot], base, *pads[pivot:]]
            else:
                sections = [*pads, base]
            cases.append(DocumentCase(
                id=f"length_{length}_{position}",
                policy="\n\n".join(sections),
                query="May an estate executor close the owner's account?",
                required_markers=("RULE-AUTH", "EXC-DECEASED", "DEF-OWNER", "REF-CLOSE"),
                definition_markers=("DEF-OWNER",),
                exception_markers=("EXC-DECEASED",),
                reference_markers=("REF-CLOSE",),
            ))
    reordered = base.replace(
        "# Definitions\nDEF-OWNER: owner means the account holder.\n\n", ""
    ) + "\n\n# Definitions\nDEF-OWNER: owner means the account holder."
    cases.append(DocumentCase(
        id="section_reorder", policy=reordered,
        query="May an estate executor close the owner's account?",
        required_markers=("RULE-AUTH", "EXC-DECEASED", "DEF-OWNER", "REF-CLOSE"),
        definition_markers=("DEF-OWNER",), exception_markers=("EXC-DECEASED",),
        reference_markers=("REF-CLOSE",),
    ))
    return tuple(cases)


def _sections(document: str) -> list[str]:
    return [item.strip() for item in re.split(r"\n\s*\n", document) if item.strip()]


def _tokens(value: str) -> set[str]:
    return {item.casefold() for item in re.findall(r"[A-Za-zА-Яа-я0-9_-]+", value)
            if len(item) > 2}


def assemble(case: DocumentCase, arm: str, *, top_k: int = 3) -> str:
    if arm in {"L0_FULL_POLICY", "L2_EXHAUSTIVE_COMPILE_ONCE"}:
        return case.policy
    if arm != "L1_RUNTIME_TOP_K":
        raise ValueError("unknown long-context arm")
    query = _tokens(case.query)
    ranked = sorted(enumerate(_sections(case.policy)),
                    key=lambda item: (-len(query & _tokens(item[1])), item[0]))
    return "\n\n".join(section for _, section in ranked[:top_k])


def _recall(markers: tuple[str, ...], text: str) -> float | None:
    if not markers:
        return None
    return sum(marker in text for marker in markers) / len(markers)


def evaluate_long_context(cases: tuple[DocumentCase, ...] | None = None) -> dict:
    cases = cases or controlled_cases()
    arms = {}
    for arm in ("L0_FULL_POLICY", "L1_RUNTIME_TOP_K", "L2_EXHAUSTIVE_COMPILE_ONCE"):
        rows = []
        for case in cases:
            assembled = assemble(case, arm)
            rows.append({
                "id": case.id,
                "input_chars": len(assembled),
                "normative_span_recall": _recall(case.required_markers, assembled),
                "definition_edge_recall": _recall(case.definition_markers, assembled),
                "exception_edge_recall": _recall(case.exception_markers, assembled),
                "reference_edge_recall": _recall(case.reference_markers, assembled),
                "all_required_evidence": all(marker in assembled for marker in case.required_markers),
            })
        recalls = [row["normative_span_recall"] for row in rows]
        arms[arm] = {
            "cases": len(rows),
            "normative_span_recall": sum(recalls) / len(recalls),
            "definition_edge_recall": sum(row["definition_edge_recall"] for row in rows) / len(rows),
            "exception_edge_recall": sum(row["exception_edge_recall"] for row in rows) / len(rows),
            "reference_edge_recall": sum(row["reference_edge_recall"] for row in rows) / len(rows),
            "all_required_evidence_recall": sum(row["all_required_evidence"] for row in rows) / len(rows),
            "silent_omission_rate": sum(not row["all_required_evidence"] for row in rows) / len(rows),
            "position_invariance": len({row["normative_span_recall"] for row in rows
                                        if row["id"].startswith("length_80_")}) == 1,
            "mean_input_chars": sum(row["input_chars"] for row in rows) / len(rows),
            "semantic_accuracy": None,
            "semantic_accuracy_reason": "document assembly only; no semantic model invoked",
            "rows": rows,
        }
    return {"benchmark": "controlled-long-policy-v1", "arms": arms}
