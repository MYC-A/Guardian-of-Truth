from guardian_truth.semantic_pipeline_v1.binding import bind_candidate, rerank_candidate
from guardian_truth.semantic_pipeline_v1.retrieval import retrieve_fragments
from guardian_truth.semantic_pipeline_v1.source_timeline import build_source_timeline, verify_timeline
from guardian_truth.semantic_pipeline_v1.types import RuleCandidate, RuleIR, RuleTerm


PROMPT = """⟦SYSTEM⟧
<policy>Do A before B.</policy>
[AVAILABLE TOOLS]
- perform_alpha — Executes the semantic action.
    object_id: string! — Object identifier.
- perform_beta — Also executes the semantic action.
    object_id: string! — Object identifier.
⟦USER⟧
Please handle OBJ-7.
⟦ASSISTANT_TOOL_CALL name="search_docs" call_id="c1"⟧
{"query":"rules"}
⟦TOOL_RESULT name="search_docs" requestor="assistant" call_id="c1"⟧
{"document":"Knowledge rule: value must be below 70."}
⟦USER⟧
Proceed now."""
RESPONSE = """⟦ASSISTANT_TOOL_CALL name="perform_alpha" call_id="t1"⟧
{"object_id":"OBJ-7"}"""


class FakeEmbedder:
    def similarity(self, query, documents):
        return [0.9 if "semantic action" in item else 0.1 for item in documents]


class FlatReranker:
    def score(self, phrase, candidates):
        return [0.8 for _ in candidates]


def candidate(name="handle object", field=None):
    rule = RuleIR("REQUIRE", "assistant", RuleTerm("ACTION", name=name, field=field),
                  entity_references=("OBJ-7",))
    return RuleCandidate("c", rule, (), ("s",), ("test",))


def test_timeline_is_lossless_and_history_order_is_monotonic():
    timeline = build_source_timeline(PROMPT, RESPONSE)
    verify_timeline(timeline, PROMPT, RESPONSE)
    chronological = sorted(timeline.segments, key=lambda item: item.event_index)
    assert chronological[-1].source_type == "TARGET_RESPONSE"
    calls = [item for item in chronological if item.source_type == "TOOL_CALL"]
    results = [item for item in chronological if item.source_type == "TOOL_RESULT"]
    assert calls[0].event_index < results[0].event_index


def test_rule_inside_returned_knowledge_document_is_routed():
    timeline = build_source_timeline(PROMPT, RESPONSE)
    result = retrieve_fragments(timeline, query=RESPONSE, top_k=1, neighbor_window=0,
                                max_fragment_chars=10000)
    kb = [item for item in result.fragments if "Knowledge rule" in item.exact_text]
    assert kb
    assert "knowledge-result-guarantee" in kb[0].reasons


def test_semantic_tool_binding_can_differ_from_phrase_and_remains_ambiguous():
    tools = ({"name": "perform_alpha", "description": "Executes the semantic action.",
              "parameters": {"type": "object", "properties": {"object_id": {"type": "string"}}}},
             {"name": "perform_beta", "description": "Also executes the semantic action.",
              "parameters": {"type": "object", "properties": {"object_id": {"type": "string"}}}})
    bound = bind_candidate(candidate(field="object identifier"), tools,
                           entity_candidates=("OBJ-7", "OBJ-8"),
                           embedder=FakeEmbedder(), top_k=2)
    assert {item.candidate for item in bound.binding_alternatives if item.kind == "TOOL"} == {
        "perform_alpha", "perform_beta"}
    assert len([item for item in bound.binding_alternatives if item.kind == "FIELD"]) == 2
    assert any(value.startswith("ambiguous-tool-binding") for value in bound.unresolved_components)
    reranked = rerank_candidate(bound, tools, reranker=FlatReranker())
    assert len([item for item in reranked.binding_alternatives if item.kind == "TOOL"]) == 2
