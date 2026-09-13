"""Original source-format views -> actual native factual v5 + attempted action.

No Goal v3, Policy solver, implicit provider or whole-Core safety verdict.
"""

from dataclasses import dataclass

from .external_source_views_v6 import make_external_source_views_v6, validate_external_source_views_v6
from .factual_envelope_v5 import analyze_envelope_factual_v5
from .source_envelope_v4 import normalize_envelope


@dataclass(frozen=True)
class ExternalFactualAnalysisV6:
    views: object
    action_source: object
    factual: object
    source_projection_valid: bool
    scope: str = "CONDITIONAL_NATIVE_TEXT_AND_ORIGINAL_ATTEMPT_NOT_WHOLE_CORE"


def analyze_external_factual_v6(case, snapshots, registry, methods, backend, *, declared_goal_actor,
        history_complete=False, completeness_basis=None):
    views = make_external_source_views_v6(case, declared_goal_actor=declared_goal_actor,
        history_complete=history_complete, completeness_basis=completeness_basis)
    valid = validate_external_source_views_v6(views, case, declared_goal_actor=declared_goal_actor,
        history_complete=history_complete, completeness_basis=completeness_basis)
    if not valid:
        raise ValueError("original source projection does not replay")
    action_source = normalize_envelope(views.action_envelope)
    # The native factual layer sees only actual target text, never argument
    # strings interpreted as new assistant assertions. Goal/Policy composition
    # must consume action_source independently and retain its unresolved scope.
    factual = analyze_envelope_factual_v5(views.text_envelope, snapshots, registry, methods, backend)
    return ExternalFactualAnalysisV6(views, action_source, factual, valid)
