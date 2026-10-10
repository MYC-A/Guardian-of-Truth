import guardian_truth.contract_lint as cl
from guardian_truth.submission.cli import apply_contract_lint

PROMPT = ('⟦SYSTEM⟧\n<policy>\nHelp the user.\n</policy>\n[AVAILABLE TOOLS]\n'
          '- get_order — Get order.\n    order_id: string! — id\n⟦USER⟧\nГде мой заказ #W1?\n')
UNKNOWN = '⟦ASSISTANT · ход 1⟧\n\t→ TOOL_CALL check_network_status: {}'
KNOWN = '⟦ASSISTANT · ход 1⟧\n\t→ TOOL_CALL get_order: {"order_id": "#W1"}'


def trace(binary):
    return dict(id='r', binary=binary, owner='review')


def test_unknown_tool_sets_violation():
    out = apply_contract_lint(trace(0), dict(prompt=PROMPT, response=UNKNOWN))
    assert out['binary'] == 1 and out['owner'] == 'contract_lint'
    assert out['contract_lint']['hard'] and out['contract_lint']['binary_before'] == 0


def test_known_tool_keeps_label_and_never_lowers():
    assert apply_contract_lint(trace(0), dict(prompt=PROMPT, response=KNOWN))['binary'] == 0
    assert apply_contract_lint(trace(1), dict(prompt=PROMPT, response=KNOWN))['binary'] == 1
    out = apply_contract_lint(trace(1), dict(prompt=PROMPT, response=UNKNOWN))
    assert out['binary'] == 1 and out['owner'] == 'review'


def test_no_catalog_abstains():
    out = apply_contract_lint(trace(0), dict(prompt='no catalog here', response=UNKNOWN))
    assert out['binary'] == 0 and out['contract_lint']['findings'] == []


def test_input_trace_not_mutated():
    t = trace(0)
    apply_contract_lint(t, dict(prompt=PROMPT, response=UNKNOWN))
    assert t == trace(0)


def test_lint_exception_leaves_label(monkeypatch):
    def boom(*a):
        raise RuntimeError('x')
    monkeypatch.setattr(cl, 'lint', boom)
    out = apply_contract_lint(trace(0), dict(prompt=PROMPT, response=UNKNOWN))
    assert out['binary'] == 0 and out['contract_lint']['status'] == 'EXCEPTION'


def test_reexport_is_same_object():
    from experiments.contract_lint_20261010 import lint as old
    assert old.lint is cl.lint and old.parse_catalog is cl.parse_catalog and old.HEADER is cl.HEADER
