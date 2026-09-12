import unittest

from guardian_truth.next.normalize import build_evidence_ledger, normalize_trace
from guardian_truth.next.records import FourValue, ToolEffectContract
from guardian_truth.next.trace_records import StateValidityStatus


OPEN = "\u27e6"
CLOSE = "\u27e7"
SYSTEM = f"{OPEN}SYSTEM{CLOSE}\nTrace test.\n"


class LosslessTraceSchemaTests(unittest.TestCase):
    def test_raw_and_parsed_tool_payloads_are_separate(self):
        prompt = SYSTEM + (f'{OPEN}ASSISTANT_TOOL_CALL name="read" call_id="transport-c1" '
                           f'timestamp="2026-01-02T03:04:05Z"{CLOSE}\n'
                           '  {"line_id":"L1"}  \n'
                           f'{OPEN}TOOL_RESULT name="read" requestor="assistant" '
                           f'call_id="transport-c1" result_id="transport-r1"{CLOSE}\n'
                           '{"line_id":"L1","state":"old"}')
        events = normalize_trace(prompt, "")
        call = next(event for event in events if event.kind == "call")
        result = next(event for event in events if event.kind == "result")

        self.assertEqual(prompt[call.source.start:call.source.end], call.raw_text)
        self.assertIn('  {"line_id":"L1"}  ', call.raw_payload)
        self.assertEqual({"line_id": "L1"}, call.parsed_value)
        self.assertEqual("L1", call.value["line_id"])
        self.assertEqual("2026-01-02T03:04:05Z", call.timestamp)
        self.assertEqual("transport-c1", call.transport_call_id)
        self.assertIsNotNone(call.call_id)
        self.assertEqual(call.call_id, result.call_id)
        self.assertIsNotNone(result.result_id)
        self.assertEqual("transport-r1", result.transport_result_id)

    def test_same_named_calls_are_not_linked_across_roles(self):
        prompt = SYSTEM + (f'{OPEN}USER_TOOL_CALL name="read"{CLOSE}\n{{}}\n'
                           f'{OPEN}ASSISTANT_TOOL_CALL name="read"{CLOSE}\n{{}}\n'
                           f'{OPEN}TOOL_RESULT name="read" requestor="assistant"{CLOSE}\n{{}}')
        events = normalize_trace(prompt, "")
        calls = [event for event in events if event.kind == "call"]
        result = next(event for event in events if event.kind == "result")
        self.assertEqual("user", calls[0].role)
        self.assertEqual("assistant", calls[1].role)
        self.assertEqual(calls[1].call_id, result.call_id)

    def test_ids_and_order_are_stable_and_unmatched_result_has_own_id(self):
        response = (f'{OPEN}ASSISTANT{CLOSE}\nHello\n'
                    f'{OPEN}TOOL_RESULT name="orphan" requestor="assistant"{CLOSE}\n{{}}')
        events = normalize_trace(SYSTEM, response)
        self.assertEqual(list(range(len(events))), [event.index for event in events])
        self.assertEqual(len(events), len({event.id for event in events}))
        self.assertEqual(len(events), len({event.turn_id for event in events}))
        orphan = next(event for event in events if event.kind == "result")
        self.assertIsNone(orphan.call_id)
        self.assertIsNotNone(orphan.result_id)

    def test_state_supersession_retains_both_observations(self):
        trace = SYSTEM + (f'{OPEN}ASSISTANT_TOOL_CALL name="read"{CLOSE}\n{{"line_id":"L1"}}\n'
                          f'{OPEN}TOOL_RESULT name="read" requestor="assistant"{CLOSE}\n'
                          '{"line_id":"L1","state":"old"}\n'
                          f'{OPEN}ASSISTANT_TOOL_CALL name="read"{CLOSE}\n{{"line_id":"L1"}}\n'
                          f'{OPEN}TOOL_RESULT name="read" requestor="assistant"{CLOSE}\n'
                          '{"line_id":"L1","state":"new"}')
        ledger = build_evidence_ledger(normalize_trace(trace, ""))
        states = [item for item in ledger.state_validity if item.predicate == "state"]

        self.assertEqual(["old", "new"], [item.object for item in states])
        self.assertEqual(StateValidityStatus.SUPERSEDED_OBSERVATION, states[0].status)
        self.assertEqual(StateValidityStatus.ACTIVE_OBSERVATION, states[1].status)
        self.assertEqual(states[1].evidence_id, states[0].superseded_by)
        self.assertIn(states[0].evidence_id, states[1].supersedes)
        self.assertEqual(states[1].valid_from_index, states[0].valid_to_index)

    def test_completeness_certificate_is_typed_and_scoped(self):
        trace = SYSTEM + (f'{OPEN}ASSISTANT_TOOL_CALL name="update"{CLOSE}\n{{"line_id":"L1"}}\n'
                          f'{OPEN}TOOL_RESULT name="update" requestor="assistant"{CLOSE}\n'
                          '{"success":false}')
        contract = ToolEffectContract(
            "update", guaranteed_effects=("line_updated",),
            failure_no_effect=FourValue.TRUE, provenance="T1_human_contract",
        )
        ledger = build_evidence_ledger(normalize_trace(trace, ""), {"update": contract})

        self.assertEqual(1, len(ledger.completeness_certificates))
        certificate = ledger.completeness_certificates[0]
        self.assertEqual("no_effect", certificate.scope_predicate)
        self.assertEqual("line_updated", certificate.scope_object)
        self.assertEqual((("line_id", "L1"),), certificate.entities)
        self.assertTrue(certificate.exhaustive)


if __name__ == "__main__":
    unittest.main()
