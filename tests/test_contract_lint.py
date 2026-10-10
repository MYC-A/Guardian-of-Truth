from experiments.contract_lint_20261010.lint import lint, parse_catalog

CAT = """[AVAILABLE TOOLS]
- get_order — Read an order.
    order_id: string! — The order id.
- cancel_order — Cancel an order.
    order_id: string! — The order id.
    reason: string [enum: no longer needed|ordered by mistake] — Why.
    count: integer — How many.
⟦USER⟧
hi
"""


def hist(*lines):
    return CAT + '\n'.join(lines) + '\n'


def turn(*calls):
    return '⟦ASSISTANT · ход 9⟧\n' + '\n'.join(f'\t→ TOOL_CALL {c}' for c in calls)


def checks(prompt, response):
    return sorted(f['check'] for f in lint(prompt, response))


def test_catalog_parse_stops_at_section():
    cat = parse_catalog(CAT)
    assert set(cat) == {'get_order', 'cancel_order'}
    assert cat['cancel_order']['params']['reason']['enum'] == ['no longer needed', 'ordered by mistake']
    assert cat['cancel_order']['params']['order_id']['required'] is True


def test_valid_call_has_no_findings():
    assert checks(hist(), turn('get_order: {"order_id": "#W1"}')) == []
    assert checks(hist(), turn('cancel_order: {"order_id": "#W1", "reason": "ordered by mistake", "count": 2}')) == []


def test_unknown_tool():
    assert checks(hist(), turn('check_network_status: {}')) == ['UNKNOWN_TOOL']


def test_schema_violations():
    assert checks(hist(), turn('cancel_order: {"reason": "ordered by mistake"}')) == ['SCHEMA']
    assert checks(hist(), turn('cancel_order: {"order_id": "#W1", "reason": "other"}')) == ['SCHEMA']
    assert checks(hist(), turn('cancel_order: {"order_id": "#W1", "count": "2"}')) == ['SCHEMA']
    assert checks(hist(), turn('cancel_order: {"order_id": "#W1", "extra": 1}')) == ['SCHEMA']
    assert checks(hist(), turn('cancel_order: {"order_id": "#W1", "count": true}')) == ['SCHEMA']


def test_optional_null_is_allowed():
    assert checks(hist(), turn('cancel_order: {"order_id": "#W1", "count": null}')) == []


def test_invalid_json():
    assert checks(hist(), turn('get_order: {order_id: W1}')) == ['INVALID_ARGS_JSON']


def test_repeat_failed_identical_after_user_message():
    p = hist('\t→ TOOL_CALL get_order: {"order_id": "#W1"}', '\t← TOOL_RESPONSE get_order [ERROR]: not found',
             '⟦USER⟧', 'try again')
    assert checks(p, turn('get_order: {"order_id": "#W1"}')) == ['REPEAT_FAILED']
    assert checks(p, turn('get_order: {"order_id": "#W2"}')) == []


def test_repeat_not_flagged_after_success_or_intervening_call():
    ok = hist('\t→ TOOL_CALL get_order: {"order_id": "#W1"}', '\t← TOOL_RESPONSE get_order: {"status": "x"}')
    assert checks(ok, turn('get_order: {"order_id": "#W1"}')) == []
    mid = hist('\t→ TOOL_CALL get_order: {"order_id": "#W1"}', '\t← TOOL_RESPONSE get_order [ERROR]: not found',
               '\t→ TOOL_CALL get_order: {"order_id": "#W2"}', '\t← TOOL_RESPONSE get_order: {"status": "x"}')
    assert checks(mid, turn('get_order: {"order_id": "#W1"}')) == []


def test_abstain_without_catalog():
    assert lint('no catalog here', turn('anything: {}')) == []


def test_inline_mention_of_header_is_not_the_catalog():
    p = 'Use only tools listed in [AVAILABLE TOOLS]. Never call others.\n' + CAT
    assert set(parse_catalog(p)) == {'get_order', 'cancel_order'}
    assert checks(p, turn('reset_vpn: {}')) == ['UNKNOWN_TOOL']
