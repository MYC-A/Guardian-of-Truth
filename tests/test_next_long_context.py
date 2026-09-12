import unittest

from guardian_truth.next.long_context import (
    DocumentCase, assemble, controlled_cases, evaluate_long_context,
)


class LongContextTests(unittest.TestCase):
    def test_full_and_compiled_arms_preserve_every_required_span(self):
        result = evaluate_long_context()
        for arm in ("L0_FULL_POLICY", "L2_EXHAUSTIVE_COMPILE_ONCE"):
            self.assertEqual(1.0, result["arms"][arm]["all_required_evidence_recall"])
            self.assertTrue(result["arms"][arm]["position_invariance"])

    def test_top_k_can_silently_drop_distant_exception(self):
        case = DocumentCase("x", "RULE key\n\nnoise\n\nEXCEPTION marker",
                            "key", ("RULE", "EXCEPTION"), exception_markers=("EXCEPTION",))
        selected = assemble(case, "L1_RUNTIME_TOP_K", top_k=1)
        self.assertIn("RULE", selected)
        self.assertNotIn("EXCEPTION", selected)

    def test_controlled_grid_varies_length_and_position(self):
        ids = {case.id for case in controlled_cases()}
        self.assertIn("length_80_start", ids)
        self.assertIn("length_80_end", ids)
        self.assertIn("section_reorder", ids)


if __name__ == "__main__":
    unittest.main()
