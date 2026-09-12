"""Authoritative executable fixture, NOT an inferred real-world tool contract.

archive v1 guarantees archived state only for completed, or noop when the prior
state was archived. Timeout/failure need not have no effect. Accepted is not
completed. Incompatible version/schema cannot borrow this contract.
"""


def reference_effect(case: dict) -> tuple[str, bool | None]:
    if case["contract_version"] is None:
        return "POSSIBLE_EFFECT", None
    if case["version"] != case["contract_version"] or case["schema_identity"] != "exact":
        return "UNKNOWN_EFFECT", None
    status = case["result"]["status"]
    if status == "completed" or (status == "noop" and case["prior_archived"] is True):
        return "TRUSTED_EFFECT", True
    if status in {"partial", "accepted"}:
        return "POSSIBLE_EFFECT", None
    return "UNKNOWN_EFFECT", None
