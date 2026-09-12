import unittest

from guardian_truth.next.decision_adapter import to_binary
from guardian_truth.next.records import FourValue
from guardian_truth.next.refusal import (
    FeasibilityCertificate, RefusalVerdict, assess_false_refusal,
)
from guardian_truth.next.routing import SlowPathStep, SlowTrigger, StopReason, validate_step
from guardian_truth.next.solver import (
    InternalVerdict, InterpretationResult, Obligation, ObligationEvaluation,
    ObligationKind, solve,
)


def interpretation(identifier, value, complete=True):
    obligation = Obligation("o1", ObligationKind.CLAIM_SUPPORT, ("c1",))
    return InterpretationResult(identifier, (
        ObligationEvaluation(obligation, value, ("e1",), complete),
    ))


class SolverTests(unittest.TestCase):
    def test_all_interpretations_must_agree_on_error(self):
        result = solve((interpretation("p1", FourValue.FALSE),
                        interpretation("p2", FourValue.FALSE)))
        self.assertEqual(InternalVerdict.PROVED_ERROR, result.verdict)
        self.assertEqual(1, to_binary(result).label)
        self.assertFalse(to_binary(result).used_fallback)

    def test_disagreement_remains_unresolved(self):
        result = solve((interpretation("p1", FourValue.FALSE),
                        interpretation("p2", FourValue.TRUE)))
        self.assertEqual(InternalVerdict.UNRESOLVED, result.verdict)
        self.assertEqual(0, to_binary(result).label)
        self.assertTrue(to_binary(result).used_fallback)

    def test_no_error_requires_completeness(self):
        incomplete = solve((interpretation("p1", FourValue.TRUE, False),))
        complete = solve((interpretation("p1", FourValue.TRUE, True),))
        self.assertEqual(InternalVerdict.UNRESOLVED, incomplete.verdict)
        self.assertEqual(InternalVerdict.PROVED_NO_ERROR, complete.verdict)

    def test_both_is_inconsistent(self):
        self.assertEqual(InternalVerdict.INCONSISTENT,
                         solve((interpretation("p1", FourValue.BOTH),)).verdict)


class RefusalAndRoutingTests(unittest.TestCase):
    def test_tool_name_alone_never_proves_false_refusal(self):
        certificate = FeasibilityCertificate(
            FourValue.TRUE, FourValue.UNKNOWN, FourValue.TRUE, FourValue.UNKNOWN,
            FourValue.UNKNOWN, FourValue.UNKNOWN,
        )
        self.assertEqual(RefusalVerdict.NOT_PROVED, assess_false_refusal(certificate))

    def test_unverified_plan_is_only_possible(self):
        certificate = FeasibilityCertificate(
            FourValue.TRUE, FourValue.TRUE, FourValue.TRUE, FourValue.TRUE,
            FourValue.TRUE, FourValue.TRUE, plan_is_verified=False,
        )
        self.assertEqual(RefusalVerdict.POSSIBLE_FALSE_REFUSAL,
                         assess_false_refusal(certificate))

    def test_slow_path_must_add_evidence_or_stop(self):
        with self.assertRaises(ValueError):
            validate_step(SlowPathStep(SlowTrigger.TOOL_EFFECT_UNKNOWN, "think_again",
                                       ("e1",), ("e1",), 1))
        validate_step(SlowPathStep(SlowTrigger.TOOL_EFFECT_UNKNOWN, "contract_test",
                                   ("e1",), ("e1", "e2"), 1))
        validate_step(SlowPathStep(SlowTrigger.TOOL_EFFECT_UNKNOWN, "human_intent",
                                   ("e1",), ("e1",), 0,
                                   StopReason.HUMAN_INTENT_REQUIRED))


if __name__ == "__main__":
    unittest.main()
