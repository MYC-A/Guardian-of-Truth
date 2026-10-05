"""Generic research integration: source-declaration checks across the whole move.

No HTTP is performed. Model semantics remain hypotheses. Mechanically supported
positive constraints can establish an error independently of a model failure.
"""
from experiments.whole_move_v1.mechanical import check
from experiments.whole_move_v1.runner import full_packet
from experiments.hybrid_mechanisms.interfaces import admit as baseline_admit
from .reviewer import admit as compact_admit


def evaluate(row, value=None, *, interface='compact'):
    if interface not in ('compact','baseline'):
        raise ValueError('UNKNOWN_REVIEW_INTERFACE')
    # Neither labels, row IDs nor gold explanations enter either checker.
    original={k:row[k] for k in ('prompt','response')}
    packet=full_packet(original)
    mechanical=check(original)
    admitted=None;failure=None;status='NOT_RUN'
    if value is not None:
        try:
            admitted=(compact_admit if interface=='compact' else baseline_admit)(value,packet)
            status='ADMITTED'
        except (ValueError,TypeError,KeyError) as exc:
            status='REJECTED';failure=str(exc)[:240]
    model_decision=admitted['decision'] if admitted else None
    if mechanical['mechanically_established_error']:
        decision='ERROR';basis='ORIGINAL_DECLARATION_CONSTRAINT'
    elif model_decision is not None:
        decision=model_decision;basis='MODEL_HYPOTHESIS'
    else:
        decision='UNKNOWN';basis='INSUFFICIENT_EVIDENCE'
    return dict(decision=decision,binary=int(decision=='ERROR'),basis=basis,
        source_sha256=mechanical['source_sha256'],mechanical=mechanical,
        underlying_model=dict(status=status,decision=model_decision,failure=failure,
                              epistemic_status='MODEL_HYPOTHESIS',admitted=admitted),
        contract='Positive explicit declaration constraints only. Passing them does not certify business-policy correctness. Tool-universe closure is not assumed.')
