"""Separate corrective diagnostic: never judge a failed exploration as evidence.

The frozen v1 runner is deliberately unchanged. This small future orchestration
guard demonstrates fail-fast behavior, not measured semantic accuracy.
"""


def execute_or_stop(controller, plan, reviewer):
    try:
        trace=controller.step(plan)
    except ValueError as exc:
        return dict(status='PLAN_ADMISSION_FAILED', failure=str(exc), decision=None,
                    review_called=False, controller_state=controller.result())
    state=controller.result()
    if not state['read_sources']:
        return dict(status='NO_COMPLETE_SOURCE_EVIDENCE', failure=None, decision=None,
                    review_called=False, controller_state=state)
    # Valid IDs/full reads allow a review, not a semantic conclusion. Its scope
    # and policy sufficiency still need the original evidence contract.
    return dict(status='REVIEW_REQUESTED', failure=None, review_called=True,
                review=reviewer(controller.context()), controller_state=state,
                trace=trace, code_proof=False)
