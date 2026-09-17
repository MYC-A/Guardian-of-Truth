"""semantic_pipeline_v1 — Phase 3: high-recall relevant-fragment retrieval.

Union of independent candidate channels (recall target, precision NOT the goal):

  A. deterministic inclusion — every policy fragment, tool declarations of
     target-call tools (plus all catalog descriptions), the target response
     fragments, the last USER request fragments;
  B. lexical/source links — fragments containing target-call tool names,
     argument field names, exact argument values (entity ids), or policy
     predicates quoted in the target response;
  C. local embedding retrieval — top-k semantically related fragments
     (multilingual MiniLM), query = user request + target call summary;
  D. KB/document-like tool results — all kb_candidate fragments are included
     as candidates (never auto-promoted to policy);
  E. LangExtract channel — optional, evaluated separately (see langextract_eval.py).

Hard rule: embeddings may only ADD candidates; deterministic/lexical/KB
candidates are never removed. Retrieval output carries per-fragment
provenance flags so later stages can trace WHY a fragment is present.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import sys
from pathlib import Path

_REPO_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _REPO_SRC not in sys.path:
    sys.path.insert(0, _REPO_SRC)

from source_segments import Fragment, SourceTimeline

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{2,}")
_VALUE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-/]{3,}")


@dataclass
class RetrievalConfig:
    embedding_top_k: int = 20
    embedding_top_k_per_type: int = 12
    embedding_min_cosine: float = 0.15
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    include_all_tool_descriptions: bool = True
    lexical_argument_values: bool = True
    locality_window: int = 1


@dataclass
class RetrievedFragment:
    fragment: Fragment
    channels: dict = field(default_factory=dict)   # channel -> evidence dict

    @property
    def score(self) -> float:
        cos = self.channels.get("embedding", {}).get("cosine")
        return cos if isinstance(cos, float) else 1.0


@dataclass
class RetrievalResult:
    case_id: str
    retrieved: tuple[RetrievedFragment, ...]
    query_text: str
    config: RetrievalConfig


# ---------------------------------------------------------------- channels A/B

def _target_tools(timeline: SourceTimeline) -> set[str]:
    return {seg.tool for seg in timeline.segments
            if seg.source_type == "TOOL_CALL" and seg.document == "response" and seg.tool}


def _argument_values(timeline: SourceTimeline) -> set[str]:
    """Exact scalar values in target-call payloads (entity ids, codes)."""
    values: set[str] = set()
    for seg in timeline.segments:
        if seg.source_type == "TOOL_CALL" and seg.document == "response":
            for match in _VALUE_TOKEN.finditer(seg.text):
                token = match.group(0)
                if any(ch.isdigit() for ch in token) or "_" in token:
                    values.add(token)
    return values


def _argument_field_names(timeline: SourceTimeline) -> set[str]:
    fields: set[str] = set()
    for seg in timeline.segments:
        if seg.source_type == "TOOL_CALL" and seg.document == "response":
            for match in _WORD.finditer(seg.text):
                fields.add(match.group(0))
    return fields


def deterministic_channel(timeline: SourceTimeline, config: RetrievalConfig) -> dict[str, dict]:
    """Channel A: fragments that are ALWAYS candidates."""
    target_tools = _target_tools(timeline)
    out: dict[str, dict] = {}
    for fragment in timeline.fragments:
        reasons = []
        if fragment.source_type == "SYSTEM" and fragment.kind.startswith("policy"):
            reasons.append("policy_full")
        if fragment.source_type == "SYSTEM" and fragment.kind.startswith("instructions"):
            reasons.append("system_instructions")
        if fragment.source_type == "SYSTEM" and fragment.kind.startswith("catalog_region"):
            reasons.append("catalog_block")
        if fragment.source_type in {"TOOL_DESCRIPTION", "TOOL_SCHEMA"} and (
                config.include_all_tool_descriptions or fragment.tool in target_tools):
            reasons.append("tool_declaration")
        if fragment.document == "response":
            reasons.append("target_response")
        if fragment.source_type == "USER" and fragment.segment_id == _last_user_segment(timeline):
            reasons.append("user_request")
        if reasons:
            out[fragment.fragment_id] = {"channel": "deterministic", "reasons": reasons}
    return out


def _last_user_segment(timeline: SourceTimeline) -> str | None:
    user_segments = [s for s in timeline.segments if s.source_type == "USER"]
    return user_segments[-1].segment_id if user_segments else None


def lexical_channel(timeline: SourceTimeline, config: RetrievalConfig) -> dict[str, dict]:
    """Channel B: exact lexical links between the target action (calls AND
    response text) and fragments, plus one-event locality around each hit
    (a failed lookup sits next to the user turn that motivated it)."""
    target_tools = _target_tools(timeline)
    values = _argument_values(timeline) if config.lexical_argument_values else set()
    values |= _response_text_values(timeline)
    field_names = {name for name in _argument_field_names(timeline) if len(name) >= 4}
    field_names |= _response_text_values(timeline)
    out: dict[str, dict] = {}
    for fragment in timeline.fragments:
        if fragment.document == "response":
            continue  # target response is already deterministic
        evidence = []
        for tool in target_tools:
            if tool and re.search(r"(?<![\w.-])" + re.escape(tool) + r"(?![\w.-])", fragment.text):
                evidence.append(f"tool_name:{tool}")
        for value in sorted(values):
            if len(value) >= 4 and value in fragment.text:
                evidence.append(f"value:{value}")
        if fragment.source_type in {"TOOL_RESULT", "USER", "ASSISTANT"}:
            # field-name links matter only for evidence fragments, not schemas
            for name in sorted(field_names):
                if re.search(r"(?<![\w.-])" + re.escape(name) + r"(?![\w.-])", fragment.text):
                    evidence.append(f"field:{name}")
                    break
        if evidence:
            out[fragment.fragment_id] = {"channel": "lexical", "evidence": evidence[:8]}
    # one-event locality: fragments sharing a segment or neighboring events of
    # a lexical hit become candidates too (recall-oriented widening)
    if config.locality_window:
        local_hits = {f.fragment_id for f in timeline.fragments if f.fragment_id in out}
        hit_segments = {f.segment_id for f in timeline.fragments if f.fragment_id in local_hits}
        seg_order = {s.segment_id: i for i, s in enumerate(timeline.segments)}
        neighbor_segments = set()
        for seg_id in hit_segments:
            index = seg_order.get(seg_id)
            if index is None:
                continue
            for delta in range(-config.locality_window, config.locality_window + 1):
                j = index + delta
                if 0 <= j < len(timeline.segments):
                    neighbor_segments.add(timeline.segments[j].segment_id)
        for fragment in timeline.fragments:
            if fragment.fragment_id not in out and fragment.segment_id in neighbor_segments \
                    and fragment.source_type in {"USER", "ASSISTANT", "TOOL_RESULT", "TOOL_CALL"}:
                out[fragment.fragment_id] = {"channel": "lexical", "evidence": ["locality"]}
    return out


def _response_text_values(timeline: SourceTimeline) -> set[str]:
    """Distinctive value tokens from the target response TEXT (names, ids,
    codes the assistant talks about) - claims-style value anchoring."""
    values: set[str] = set()
    for segment in timeline.segments:
        if segment.source_type == "ASSISTANT" and segment.document == "response":
            for match in _VALUE_TOKEN.finditer(segment.text):
                token = match.group(0)
                if len(token) >= 5 and (any(ch.isdigit() for ch in token) or "_" in token):
                    values.add(token)
            # capitalized Latin name tokens the assistant mentions
            for match in re.finditer(r"\b[A-Z][a-z]{3,}\b", segment.text):
                values.add(match.group(0))
    return values


def kb_channel(timeline: SourceTimeline) -> dict[str, dict]:
    """Channel D: KB/document-like tool results — always candidates."""
    return {f.fragment_id: {"channel": "kb_document"}
            for f in timeline.fragments if f.kb_candidate}


# ---------------------------------------------------------------- channel C

def _query_text(timeline: SourceTimeline) -> str:
    user_segments = [s for s in timeline.segments if s.source_type == "USER"]
    request = user_segments[-1].text if user_segments else ""
    tools = " ".join(sorted(_target_tools(timeline)))
    response_calls = [s for s in timeline.segments
                      if s.source_type == "TOOL_CALL" and s.document == "response"]
    call_summary = " ".join(f"{s.tool} {s.text[:200]}" for s in response_calls)
    response_text = " ".join(s.text[:1500] for s in timeline.segments
                              if s.source_type == "ASSISTANT" and s.document == "response")
    return " ".join(part for part in (request, tools, call_summary, response_text) if part)[:6000]


def embedding_channel(timeline: SourceTimeline, config: RetrievalConfig,
                      model=None) -> tuple[dict[str, dict], dict]:
    """Channel C: local multilingual MiniLM cosine retrieval. ADD-ONLY."""
    query = _query_text(timeline)
    # candidate pool: every non-guaranteed fragment type (history calls are
    # included: their arguments carry the evidence of what was tried)
    pool = [f for f in timeline.fragments
            if f.source_type in {"USER", "ASSISTANT", "TOOL_RESULT", "TOOL_CALL"}]
    if not pool or model is None:
        return {}, {"query": query, "pool": 0, "note": "empty pool or model not loaded"}
    texts = [query] + [f.text[:1200] for f in pool]
    vectors = model.encode(texts, normalize_embeddings=True,
                           batch_size=32, show_progress_bar=False)
    query_vec, pool_vecs = vectors[0], vectors[1:]
    import numpy as np
    cosines = pool_vecs @ query_vec
    order = np.argsort(-cosines)
    out: dict[str, dict] = {}
    # overall top-k ...
    for rank, index in enumerate(order[:config.embedding_top_k]):
        cosine = float(cosines[index])
        if cosine < config.embedding_min_cosine:
            break
        fragment = pool[int(index)]
        out[fragment.fragment_id] = {"channel": "embedding", "cosine": round(cosine, 4),
                                     "rank": rank + 1, "quota": "overall"}
    # ... PLUS a per-source-type quota: JSON result blobs, colloquial user
    # turns and history calls should not compete in one global ranking
    per_type: dict[str, list[int]] = {}
    for index in order:
        fragment = pool[int(index)]
        per_type.setdefault(fragment.source_type, []).append(int(index))
    for source_type, indices in per_type.items():
        for rank, index in enumerate(indices[:config.embedding_top_k_per_type]):
            cosine = float(cosines[index])
            if cosine < config.embedding_min_cosine:
                break
            fragment = pool[index]
            if fragment.fragment_id not in out:
                out[fragment.fragment_id] = {"channel": "embedding", "cosine": round(cosine, 4),
                                             "rank": rank + 1, "quota": f"type:{source_type}"}
    return out, {"query": query[:600], "pool": len(pool), "queried": len(out)}


# ---------------------------------------------------------------- union

def retrieve(timeline: SourceTimeline, config: RetrievalConfig,
             embedding_model=None) -> RetrievalResult:
    channels = [
        deterministic_channel(timeline, config),
        lexical_channel(timeline, config),
        kb_channel(timeline),
    ]
    embed_map, embed_info = embedding_channel(timeline, config, embedding_model)
    channels.append(embed_map)
    by_id = {f.fragment_id: f for f in timeline.fragments}
    merged: dict[str, RetrievedFragment] = {}
    for channel_map in channels:
        for fragment_id, info in channel_map.items():
            fragment = by_id[fragment_id]
            if fragment_id not in merged:
                merged[fragment_id] = RetrievedFragment(fragment, {})
            merged[fragment_id].channels[info["channel"]] = {
                key: value for key, value in info.items() if key != "channel"}
    retrieved = tuple(merged.values())
    return RetrievalResult(timeline.case_id, retrieved, _query_text(timeline), config)


def load_embedding_model(config: RetrievalConfig | None = None):
    config = config or RetrievalConfig()
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(config.embedding_model, device="cpu")


if __name__ == "__main__":  # pragma: no cover - manual smoke
    import json
    import pandas as pd
    from source_segments import build_timeline
    rows = pd.read_parquet("/home/z/my-project/Guardian-of-Truth/valid.parquet").to_dict(orient="records")
    row = next(r for r in rows if r["id"] == "airline__21::t7")
    timeline = build_timeline(row["id"], row["prompt"], row["response"])
    result = retrieve(timeline, RetrievalConfig())  # no embeddings in smoke
    counts: dict[str, int] = {}
    for item in result.retrieved:
        for channel in item.channels:
            counts[channel] = counts.get(channel, 0) + 1
    print("retrieved fragments:", len(result.retrieved), "| channels:", counts)
    print("query:", result.query_text[:120])
