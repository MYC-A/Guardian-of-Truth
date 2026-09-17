"""semantic_pipeline_v1 — Phase 5: compositional typed RuleIR.

A SMALL representation built from deontic/policy primitives (obligation,
prohibition, permission, action, state, condition, temporal relation,
comparison, cardinality, exception) — NO benchmark-specific rule kinds.
"Do not close an account unless identity was verified with at least two
factors" is FORBID(close_account) UNLESS AND(verified_identity,
factor_count >= 2); no CLOSE_ACCOUNT rule type exists.

Phases 8 + 12 also live here:
  - render_rule(): deterministic round-trip renderer (NO LLM);
  - pydantic models = strict structural validity (syntax != semantics).

The RuleIR is intentionally close to the incumbent PolicyFlatStructure so the
Phase-14 adapter stays a thin representation mapper.
"""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator

Modality = Literal["REQUIRE", "FORBID", "ALLOW", "UNKNOWN"]
TemporalRelation = Literal["NONE", "BEFORE", "AFTER", "UNTIL", "WHILE", "UNKNOWN"]
ComparisonOp = Literal["EQ", "NE", "LT", "LE", "GT", "GE"]
CardinalityOp = Literal["NONE", "AT_LEAST", "AT_MOST", "EXACTLY"]
TargetKind = Literal["ACTION", "STATE", "CLAIM", "UNKNOWN"]
AtomKind = Literal["ACTION", "STATE", "VALUE", "CONDITION", "ENTITY", "CLAIM", "EVIDENCE"]


class SourceSpan(BaseModel):
    document: Literal["prompt", "response"]
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    quote: str

    @field_validator("end")
    @classmethod
    def span_ordered(cls, value: int, info) -> int:
        if "start" in info.data and value < info.data["start"]:
            raise ValueError("span end before start")
        return value


class Provenance(BaseModel):
    extractor: Literal["mistral", "nuextract", "gliner2", "deterministic", "annotation"]
    fragment_id: str | None = None
    segment_id: str | None = None
    raw_output: str | None = None


class Ref(BaseModel):
    """A reference to a semantic concept: tool/action name, state field or
    claim predicate.  `text` is the verbatim source wording; `ref` is the
    normalized key when known, else UNKNOWN."""
    kind: TargetKind
    text: str
    ref: str = "UNKNOWN"
    span: SourceSpan | None = None


class Comparison(BaseModel):
    lhs: Ref
    op: ComparisonOp
    rhs_literal: str            # canonical JSON literal ("70", "\"economy\"")


class Cardinality(BaseModel):
    subject: Ref
    op: CardinalityOp
    count: int | None = None


class Atom(BaseModel):
    """Semantic atom used inside conditions/exceptions."""
    atom_id: str | None = None
    kind: AtomKind
    text: str
    ref: str = "UNKNOWN"
    comparison: Comparison | None = None
    cardinality: Cardinality | None = None
    span: SourceSpan | None = None

    def atom_key(self) -> str:
        if self.comparison:
            return f"cmp:{self.ref}:{self.comparison.op}:{self.comparison.rhs_literal}"
        if self.cardinality and self.cardinality.op != "NONE":
            return f"card:{self.ref}:{self.cardinality.op}:{self.cardinality.count}"
        return f"atom:{self.kind}:{self.ref}"


class ConditionNode(BaseModel):
    """boolean expression tree over atoms: {all:[...]}, {any:[...]},
    {not: {...}}, {atom: {...}}."""
    model_config = {"populate_by_name": True}
    all_: list["ConditionNode"] | None = Field(default=None, alias="all")
    any_: list["ConditionNode"] | None = Field(default=None, alias="any")
    not_: "ConditionNode | None" = Field(default=None, alias="not")
    atom: Atom | None = None

    def to_expr_dict(self) -> dict:
        if self.all_ is not None:
            return {"all": [node.to_expr_dict() for node in self.all_]}
        if self.any_ is not None:
            return {"any": [node.to_expr_dict() for node in self.any_]}
        if self.not_ is not None:
            return {"not": self.not_.to_expr_dict()}
        if self.atom is not None:
            return {"atom": self.atom.atom_key()}
        return {"empty": True}

    def leaves(self) -> list[Atom]:
        if self.atom is not None:
            return [self.atom]
        out = []
        for child in (self.all_ or []) + (self.any_ or []):
            out.extend(child.leaves())
        if self.not_ is not None:
            out.extend(self.not_.leaves())
        return out

    @field_validator("all_")
    @classmethod
    def nonempty_all(cls, value):
        if value is not None and not value:
            raise ValueError("empty all() node")
        return value

    @field_validator("any_")
    @classmethod
    def nonempty_any(cls, value):
        if value is not None and not value:
            raise ValueError("empty any() node")
        return value


class Temporal(BaseModel):
    relation: TemporalRelation = "NONE"
    anchor: Ref | None = None


class RuleIR(BaseModel):
    """One candidate rule interpretation. Composition only; no case-specific
    kinds. `unresolved` carries interpretation-blocking ambiguity."""
    rule_id: str
    modality: Modality
    target: Ref
    conditions: ConditionNode | None = None
    exceptions: list[ConditionNode] = Field(default_factory=list)
    temporal: Temporal = Field(default_factory=Temporal)
    actor: str = "UNKNOWN"
    source_spans: list[SourceSpan] = Field(default_factory=list)
    provenance: Provenance
    unresolved: list[str] = Field(default_factory=list)

    def semantic_key(self) -> str:
        """Canonical key for deduplication of SEMANTICALLY EQUIVALENT rules
        (representation variance collapses; disagreement never does)."""
        def expr_key(node: ConditionNode | None) -> str:
            if node is None:
                return "None"
            return str(node.to_expr_dict())
        return "|".join([
            self.modality,
            self.target.kind, self.target.ref,
            expr_key(self.conditions),
            "+".join(expr_key(node) for node in self.exceptions),
            self.temporal.relation, self.temporal.anchor.ref if self.temporal.anchor else "-",
        ])


ConditionNode.model_rebuild()


# ---------------------------------------------------------------- renderer
# Phase 8: deterministic round-trip text. NO LLM anywhere in this section.

_OP_TEXT = {"EQ": "equals", "NE": "does not equal", "LT": "is less than",
            "LE": "is at most", "GT": "is greater than", "GE": "is at least"}
_CARD_TEXT = {"AT_LEAST": "at least", "AT_MOST": "at most", "EXACTLY": "exactly"}
_MODALITY_TEXT = {"REQUIRE": "required", "FORBID": "forbidden", "ALLOW": "allowed"}


def _ref_text(ref: Ref) -> str:
    return ref.text if ref.text else (ref.ref if ref.ref != "UNKNOWN" else "the referenced concept")


def render_atom(atom: Atom) -> str:
    if atom.comparison:
        return f"{_ref_text(atom.comparison.lhs)} {_OP_TEXT[atom.comparison.op]} {atom.comparison.rhs_literal.strip(chr(34))}"
    if atom.cardinality and atom.cardinality.op != "NONE":
        count = atom.cardinality.count if atom.cardinality.count is not None else "N"
        return f"{count} {_ref_text(atom.cardinality.subject)} ({_CARD_TEXT[atom.cardinality.op]})"
    return _ref_text(atom)


def render_condition(node: ConditionNode) -> str:
    if node.atom is not None:
        return render_atom(node.atom)
    if node.all_ is not None:
        return " and ".join(render_condition(child) for child in node.all_)
    if node.any_ is not None:
        return " or ".join(render_condition(child) for child in node.any_)
    if node.not_ is not None:
        return f"not ({render_condition(node.not_)})"
    return "unknown condition"


def render_rule(rule: RuleIR) -> str:
    """Deterministic hypothesis text for NLI checking. Structure:
    <target> is <modality>[ before/after <anchor>][ only if <cond>][ unless
    <exception>][ (unresolved: ...)]."""
    target = _ref_text(rule.target)
    modality = _MODALITY_TEXT.get(rule.modality, "of unknown status")
    if rule.modality == "UNKNOWN":
        sentence = f"the status of {target} is unknown"
    else:
        sentence = f"{target} is {modality}"
    if rule.temporal.relation in {"BEFORE", "AFTER", "UNTIL", "WHILE"} and rule.temporal.anchor:
        anchor = _ref_text(rule.temporal.anchor)
        relation = {"BEFORE": "before", "AFTER": "after", "UNTIL": "until", "WHILE": "while"}[rule.temporal.relation]
        if rule.modality == "REQUIRE":
            sentence = f"{target} is required {relation} {anchor}"
        elif rule.modality == "FORBID":
            sentence = f"{target} is forbidden {relation} {anchor}"
        else:
            sentence = f"{target} is allowed only {relation} {anchor}"
    if rule.conditions is not None:
        sentence += f" only if {render_condition(rule.conditions)}"
    for exception in rule.exceptions:
        sentence += f" unless {render_condition(exception)}"
    if rule.unresolved:
        sentence += f" (unresolved: {'; '.join(rule.unresolved[:3])})"
    sentence += "."
    return sentence[0].upper() + sentence[1:]


# ------------------------------------------------------- helpers for adapters

def rule_from_dict(data: dict, *, rule_id: str, extractor: str,
                   fragment_id: str | None = None, segment_id: str | None = None,
                   raw_output: str | None = None) -> RuleIR:
    """Validate-and-build from a plain dict (extractor output).  Raises
    pydantic ValidationError on structural problems (Phase 12 gate)."""
    data = dict(data)
    data["rule_id"] = rule_id
    data.setdefault("provenance", {})
    data["provenance"] = {**data["provenance"], "extractor": extractor,
                          "fragment_id": fragment_id, "segment_id": segment_id,
                          "raw_output": raw_output}
    return RuleIR.model_validate(data)


def rule_to_json(rule: RuleIR) -> str:
    import json
    return json.dumps(rule.model_dump(by_alias=True, exclude_none=True), ensure_ascii=False,
                      sort_keys=True)


# canonical deontic cue lexicon (generic, EN + RU) used by deterministic mappers
DEONTIC_CUES = {
    "forbid": ["must not", "may not", "cannot", "do not", "don't", "not allowed",
               "forbidden", "prohibited", "never", "only after", "no earlier than",
               "нельзя", "не допускается", "запрещен", "запрещается", "не разрешается"],
    "require": ["must", "required", "shall", "need to", "has to", "is to",
                "обязан", "должен", "необходимо", "требуется"],
    "allow": ["may", "allowed", "can", "permitted", "разрешен", "разрешается", "можно"],
    "temporal": ["before", "after", "until", "while", "prior to", "no earlier",
                 "не ранее", "до", "после", "пока"],
    "exception": ["unless", "except", "in the case of", "за исключением", "кроме случая"],
    "condition": ["only if", "if", "when", "in case", "provided that", "только если", "если"],
    "cardinality": ["at least", "at most", "exactly", "no more than", "не менее", "не более", "ровно"],
}


def cue_score(text: str) -> dict[str, int]:
    lowered = text.lower()
    return {name: sum(lowered.count(cue) for cue in cues)
            for name, cues in DEONTIC_CUES.items()}


def is_normative_candidate(text: str) -> bool:
    """Generic deontic cue filter (EN+RU). Not a semantic judge; only a
    high-recall filter that decides which fragments are OFFERED to the
    extractors."""
    scores = cue_score(text)
    return any(scores[name] > 0 for name in ("forbid", "require", "allow", "exception",
                                             "cardinality")) or scores["temporal"] > 0


GATING_CUES = ("only if", "only when", "only after", "only upon", "unless", "if ", "when ",
                "while ", "until ", "before ", "after ", "no ", "may ", "can ", "cannot ")


def is_policy_normative_candidate(text: str) -> bool:
    """Relaxed candidate filter for POLICY-region paragraphs: deontic cues OR
    gating cues (imperative-verb policies like 'Waive the fee if ...' or
    'Offer the upgrade only when ...' carry no must/may words)."""
    if is_normative_candidate(text):
        return True
    lowered = text.lower()
    return any(cue in lowered for cue in GATING_CUES)
