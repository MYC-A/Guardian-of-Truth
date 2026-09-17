"""Recall-oriented fragment union: guarantees + exact links + BGE + neighbors."""

from __future__ import annotations

import re

from .types import RetrievedFragment, RetrievalResult, SourceTimeline


_TOKEN = re.compile(r"[\w.-]+", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {value.casefold() for value in _TOKEN.findall(text) if len(value) > 1}


def retrieve_fragments(timeline: SourceTimeline, *, query: str, top_k: int,
                       neighbor_window: int, max_fragment_chars: int,
                       embedder=None) -> RetrievalResult:
    segments = [segment for segment in timeline.segments
                if segment.source_type not in {"RAW_PROMPT"}]
    query_tokens = _tokens(query)
    scored = []
    for segment in segments:
        segment_tokens = _tokens(segment.exact_text)
        lexical = len(query_tokens & segment_tokens) / max(1, len(query_tokens))
        scored.append([segment, lexical, None, set()])
    if embedder is not None and scored:
        semantic_scores = embedder.similarity(query, [item[0].exact_text for item in scored])
        for item, score in zip(scored, semantic_scores, strict=True):
            item[2] = float(score)

    selected = set()
    # Source-class guarantees are independent of similarity.
    for index, item in enumerate(scored):
        segment = item[0]
        if segment.source_type in {"SYSTEM", "USER", "TARGET_RESPONSE"}:
            selected.add(index); item[3].add("source-class-guarantee")
        if segment.source_type == "TOOL_SCHEMA" and segment.tool_name \
                and segment.tool_name.casefold() in query.casefold():
            selected.add(index); item[3].add("target-tool-schema")
        if segment.source_type == "TOOL_RESULT" and any(
                word in segment.exact_text.casefold() for word in
                ("policy", "rule", "knowledge", "document", "must", "forbid", "allowed")):
            selected.add(index); item[3].add("knowledge-result-guarantee")
        if item[1] > 0:
            item[3].add("exact-or-lexical-link")

    rank = sorted(range(len(scored)), key=lambda index: (
        scored[index][2] if scored[index][2] is not None else -1.0,
        scored[index][1], -scored[index][0].event_index), reverse=True)
    for index in rank[:top_k]:
        selected.add(index)
        scored[index][3].add("bge-top-k" if embedder is not None else "lexical-top-k")
    chronological = sorted(range(len(scored)), key=lambda i: scored[i][0].event_index)
    position = {index: pos for pos, index in enumerate(chronological)}
    anchors = tuple(selected)
    for index in anchors:
        pos = position[index]
        for neighbor_pos in range(max(0, pos - neighbor_window),
                                  min(len(chronological), pos + neighbor_window + 1)):
            neighbor = chronological[neighbor_pos]
            selected.add(neighbor)
            if neighbor != index:
                scored[neighbor][3].add(f"neighbor-of:{scored[index][0].segment_id}")

    used, fragments = 0, []
    for index in sorted(selected, key=lambda i: scored[i][0].event_index):
        segment, lexical, semantic, reasons = scored[index]
        if used and used + len(segment.exact_text) > max_fragment_chars \
                and "source-class-guarantee" not in reasons:
            reasons.add("deferred-by-character-budget")
            continue
        used += len(segment.exact_text)
        fragments.append(RetrievedFragment(segment.segment_id, segment.exact_text,
                                             tuple(sorted(reasons)), lexical, semantic))
    routed = tuple(fragment.segment_id for fragment in fragments)
    unrouted = tuple(item[0].segment_id for item in scored if item[0].segment_id not in routed)
    coverage = tuple({"segment_id": item[0].segment_id,
                      "status": "ROUTED" if item[0].segment_id in routed else "PRESENT_NOT_ROUTED",
                      "reasons": sorted(item[3])} for item in scored)
    return RetrievalResult(tuple(fragments), routed, unrouted, coverage)
