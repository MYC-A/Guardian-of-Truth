import unittest

from guardian_truth.next.vigil import review


class VigilLikeTests(unittest.TestCase):
    def test_trace_vocabulary_selects_policy_but_not_an_effect(self):
        prompt = ("⟦SYSTEM⟧\n# Rules\nBefore cancel_order, verify order_id.\n\n"
                  "Unrelated loyalty information.\n"
                  "⟦ASSISTANT_TOOL_CALL name=\"cancel_order\"⟧\n{\"order_id\":\"A\"}")
        result = review(prompt, "")
        self.assertTrue(result.selected_segment_ids)
        self.assertEqual(0, result.label)

    def test_user_tool_name_does_not_create_violation(self):
        prompt = "⟦SYSTEM⟧\nNever issue refunds.\n⟦USER⟧\nCan you call issue_refund?"
        result = review(prompt, "⟦ASSISTANT⟧\nI can explain the policy.")
        self.assertEqual(0, result.label)


if __name__ == "__main__":
    unittest.main()
