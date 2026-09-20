"""Lexical + embedding + reranker binding while preserving ambiguity."""

from __future__ import annotations

from dataclasses import replace
import json

from .types import BindingAlternative, RuleCandidate


def _description(tool: dict) -> str:
    return " | ".join(filter(None, (tool.get("name"), tool.get("description"),
                                     json.dumps(tool.get("parameters", {}), ensure_ascii=False,
                                                sort_keys=True))))


def _fields(schema: dict, prefix=()):
    out = []
    for name, value in schema.get("properties", {}).items():
        path = ".".join((*prefix, name))
        out.append((path, path + " | " + json.dumps(value, ensure_ascii=False, sort_keys=True)))
        if isinstance(value, dict) and value.get("type") == "object":
            out.extend(_fields(value, (*prefix, name)))
    return out


def _alternatives(kind, phrase, names, descriptions, *, embedder, top_k):
    if not phrase or not names:
        return ()
    words = set(phrase.casefold().replace("_", " ").split())
    lexical = [1.0 if name.casefold() == phrase.casefold() else
               len(words & set(name.casefold().replace("_", " ").split())) / max(1, len(words))
               for name in names]
    semantic = embedder.similarity(phrase, descriptions) if embedder else [None] * len(names)
    ranked = sorted(range(len(names)), key=lambda i: (
        lexical[i], semantic[i] if semantic[i] is not None else -1.0), reverse=True)[:top_k]
    return tuple(BindingAlternative(kind, phrase, names[i], lexical[i], semantic[i], None,
                                    source_grounded_alias=lexical[i] == 1.0) for i in ranked)


def bind_candidate(candidate: RuleCandidate, tool_catalog: tuple[dict, ...], *,
                   entity_candidates: tuple[str, ...] = (), embedder=None,
                   reranker=None, top_k: int = 5) -> RuleCandidate:
    phrase = candidate.rule.target.name
    alternatives = ()
    if candidate.rule.target.kind == "ACTION" and phrase and tool_catalog:
        names = [tool["name"] for tool in tool_catalog]
        alternatives += _alternatives("TOOL", phrase, names, [_description(tool) for tool in tool_catalog],
                                      embedder=embedder, top_k=top_k)
    field_rows = [item for tool in tool_catalog for item in _fields(tool.get("parameters", {}))]
    if candidate.rule.target.field and field_rows:
        alternatives += _alternatives("FIELD", candidate.rule.target.field,
            [row[0] for row in field_rows], [row[1] for row in field_rows],
            embedder=embedder, top_k=top_k)
    for entity in candidate.rule.entity_references:
        alternatives += _alternatives("ENTITY", entity, list(entity_candidates),
                                      list(entity_candidates), embedder=embedder, top_k=top_k)
    unresolved = candidate.unresolved_components
    for kind, semantic in (("TOOL", phrase), ("FIELD", candidate.rule.target.field)):
        subset = [item for item in alternatives if item.kind == kind]
        if semantic and (not subset or (subset[0].lexical_score < 1.0 and len(subset) > 1)):
            unresolved = tuple(dict.fromkeys((*unresolved, f"ambiguous-{kind.lower()}-binding:{semantic}")))
    for entity in candidate.rule.entity_references:
        subset = [item for item in alternatives if item.kind == "ENTITY" and item.semantic_name == entity]
        if not subset or (subset[0].lexical_score < 1.0 and len(subset) > 1):
            unresolved = tuple(dict.fromkeys((*unresolved, f"ambiguous-entity-binding:{entity}")))
    return replace(candidate, binding_alternatives=alternatives,
                   unresolved_components=unresolved)


def rerank_candidate(candidate: RuleCandidate, tool_catalog: tuple[dict, ...], *, reranker):
    """Rerank an already retrieved binding set without retaining the embedder."""
    if not candidate.binding_alternatives:
        return candidate
    descriptions = {tool["name"]: _description(tool) for tool in tool_catalog}
    descriptions.update({name: text for tool in tool_catalog
                         for name, text in _fields(tool.get("parameters", {}))})
    updated = []
    for (kind, phrase) in dict.fromkeys(
            (item.kind, item.semantic_name) for item in candidate.binding_alternatives):
        alternatives = [item for item in candidate.binding_alternatives
                        if item.kind == kind and item.semantic_name == phrase]
        texts = [descriptions.get(item.candidate, item.candidate) for item in alternatives]
        scores = reranker.score(phrase, texts)
        updated.extend(replace(item, reranker_score=score)
                       for item, score in zip(alternatives, scores, strict=True))
    updated = tuple(sorted(updated, key=lambda item: (item.kind, item.semantic_name,
        item.reranker_score if item.reranker_score is not None else float("-inf"),
        item.embedding_score if item.embedding_score is not None else float("-inf"),
        item.lexical_score), reverse=True))
    return replace(candidate, binding_alternatives=updated)
