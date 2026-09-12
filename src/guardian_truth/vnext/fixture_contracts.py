"""Trusted executable benchmark fixture contract; not a real provider contract.

Authority: the independent frozen benchmarks/vnext/tool_reference_v1.py fixture.
This module is excluded from automatic real-tool contract discovery.
"""

from .integrity import canonical
from .normalize import tool_identity
from .tools import ConditionalGuarantee, EffectSpec, FieldCondition, TrustedContract


FIXTURE_SCHEMA = {"record_id": "string"}


def archive_fixture_contract() -> TrustedContract:
    def condition(source, key, value):
        return FieldCondition(source, (key,), canonical(value).decode("utf-8"))

    identity = tool_identity("fixture.archive", FIXTURE_SCHEMA, provider="vnext-fixture", version="v1")
    state = EffectSpec("record_id", "archived", "true", False)
    completed = EffectSpec("record_id", "archived", "true", True)
    return TrustedContract(identity, (), ("record_id",), ("archived",),
        (ConditionalGuarantee((condition("result", "status", "completed"),), (completed,)),
         ConditionalGuarantee((condition("result", "status", "noop"),
                               condition("prior_state", "archived", True)), (state,))),
        (), (condition("result", "status", "noop"), condition("prior_state", "archived", True)),
        "failed/timeout unknown effect; accepted not completed", "at result event only",
        "state idempotent; mutation/action count not idempotent", "benchmarks/vnext/tool_reference_v1.py",
        (ConditionalGuarantee((condition("result", "status", "accepted"),), (state,)),
         ConditionalGuarantee((condition("result", "status", "partial"),), (state,))))
