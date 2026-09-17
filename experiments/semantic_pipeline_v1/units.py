"""semantic_pipeline_v1 — extraction unit selection.

Which fragments are OFFERED to the semantic extractors (Phase 6):

  1. policy paragraphs (consecutive policy fragments joined across single
     newlines — rules span bullet lists);
  2. instruction fragments carrying deontic cues (generic lexicon);
  3. KB-candidate result fragments (normative rules inside tool-result
     documents — candidates only, never auto-promoted);
  4. retrieved USER/ASSISTANT/TOOL_RESULT/TOOL_CALL fragments carrying
     deontic cues (the user may state binding conditions).

Unit identity is (segment_id, span) so every extracted rule is traceable to
exact source + time.  Cue filtering is a high-recall lexical pre-filter, NOT
a semantic judge.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from source_segments import Fragment, SourceTimeline
from rule_ir import is_normative_candidate, is_policy_normative_candidate


@dataclass(frozen=True)
class Unit:
    unit_id: str
    segment_id: str
    document: str
    source_type: str
    span: tuple[int, int]
    text: str
    kind: str                      # policy_paragraph | instructions | kb_doc | retrieved_cue
    tool: str | None = None
    fragment_ids: tuple[str, ...] = ()

    def unit_dict(self) -> dict:
        return {"unit_id": self.unit_id, "segment_id": self.segment_id,
                "document": self.document, "source_type": self.source_type,
                "kind": self.kind, "tool": self.tool,
                "span": list(self.span), "text": self.text}


def _paragraphs(fragments: list[Fragment], max_chars: int = 1400) -> list[tuple[int, int, str, tuple[str, ...]]]:
    """Join consecutive fragments whose spans are adjacent (gap <= one newline)
    into paragraph units. Deterministic; spans preserved exactly."""
    units = []
    current: list[Fragment] = []
    for fragment in fragments:
        if current:
            prev = current[-1]
            gap = fragment.span[0] - prev.span[1]
            joined = sum(len(f.text) for f in current) + len(fragment.text)
            if gap > 1 or joined > max_chars:
                units.append(current)
                current = []
        current.append(fragment)
    if current:
        units.append(current)
    out = []
    for group in units:
        start, end = group[0].span[0], group[-1].span[1]
        parts = []
        for i, f in enumerate(group):
            parts.append(f.text)
            if i + 1 < len(group) and f.span[1] != group[i + 1].span[0]:
                parts.append(" ")   # fragments separated by trimmed whitespace
        text = "".join(parts).strip()
        out.append((start, end, text, tuple(f.fragment_id for f in group)))
    return out


def extraction_units(timeline: SourceTimeline, retrieved_ids: set[str] | None = None) -> list[Unit]:
    units: list[Unit] = []
    seq = 0

    def add(span, text, kind, segment_id, source_type, tool=None, fragment_ids=()):
        nonlocal seq
        unit = Unit(unit_id=f"unit:{seq:04d}", segment_id=segment_id,
                    document="prompt" if source_type in {"SYSTEM", "TOOL_DESCRIPTION", "TOOL_SCHEMA"}
                    or kind in {"kb_doc", "retrieved_cue"} and segment_id.startswith("seg:")
                    else "prompt",
                    source_type=source_type, span=(span[0], span[1]), text=text,
                    kind=kind, tool=tool, fragment_ids=fragment_ids)
        seq += 1
        units.append(unit)
        return unit

    # 1. policy paragraphs (document is prompt, source SYSTEM); only those
    #    carrying a generic deontic cue are offered to extractors
    policy_fragments = [f for f in timeline.fragments
                        if f.source_type == "SYSTEM" and f.kind.startswith("policy")]
    for start, end, text, frag_ids in _paragraphs(policy_fragments):
        if text.strip() and is_policy_normative_candidate(text):
            add((start, end), text, "policy_paragraph",
                policy_fragments[0].segment_id, "SYSTEM", None, frag_ids)

    # 2. instruction fragments with deontic cues
    for fragment in timeline.fragments:
        if fragment.source_type == "SYSTEM" and fragment.kind.startswith("instructions") \
                and is_normative_candidate(fragment.text):
            add(fragment.span, fragment.text, "instructions",
                fragment.segment_id, "SYSTEM", None, (fragment.fragment_id,))

    # 3. KB-candidate result fragments (as paragraph groups)
    kb_fragments = [f for f in timeline.fragments if f.kb_candidate]
    for start, end, text, frag_ids in _paragraphs(kb_fragments):
        if text.strip() and is_policy_normative_candidate(text):
            add((start, end), text, "kb_doc",
                kb_fragments[0].segment_id if kb_fragments else "", "TOOL_RESULT",
                kb_fragments[0].tool if kb_fragments else None, frag_ids)

    # 4. retrieved trajectory fragments with deontic cues (users can state
    #    binding conditions; results can carry normative text)
    for fragment in timeline.fragments:
        if fragment.document == "response":
            continue
        if fragment.source_type in {"USER", "ASSISTANT", "TOOL_RESULT", "TOOL_CALL"} \
                and not fragment.kb_candidate \
                and is_normative_candidate(fragment.text):
            if retrieved_ids is None or fragment.fragment_id in retrieved_ids:
                add(fragment.span, fragment.text, "retrieved_cue",
                    fragment.segment_id, fragment.source_type, fragment.tool,
                    (fragment.fragment_id,))
    return units


def units_for_required_fragments(timeline: SourceTimeline, fragment_ids: set[str]) -> list[Unit]:
    """A2/A3/A4 ablation mode: extraction units built ONLY around the
    human-annotated required fragments ('correct fragment' conditions)."""
    units: list[Unit] = []
    seq = 0
    for fragment in timeline.fragments:
        if fragment.fragment_id in fragment_ids:
            units.append(Unit(unit_id=f"unit:req:{seq:03d}", segment_id=fragment.segment_id,
                              document=fragment.document, source_type=fragment.source_type,
                              span=fragment.span, text=fragment.text,
                              kind="required_fragment", tool=fragment.tool,
                              fragment_ids=(fragment.fragment_id,)))
            seq += 1
    return units
