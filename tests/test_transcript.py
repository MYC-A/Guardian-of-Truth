"""Parser tests on fragments copied from real valid rows (Lynx packets in the repository, 07.10)
and from the task page. Tests marked ASSUMED cover shapes not yet seen in a real row."""
import json
import unittest

from guardian_truth.transcript import analyze, analyze_turn, document_stats, parse_document, parse_system
from guardian_truth.transcript.catalog import validate_arguments
from guardian_truth.transcript.values import find_token, parse_dates, parse_numbers, value_kind

PREAMBLE = ("You are a customer service agent that helps the user according to the <policy> provided below.\n"
            "In each turn you can either:\n- Send a message to the user.\n- Make a tool call.\n"
            "You cannot do both at the same time.\n\nTry to be helpful and always follow the policy. "
            "Always make sure you generate valid JSON only.\n\nAlways communicate with the user in Russian. "
            "Keep tool names, tool call arguments, IDs, codes, and other data values exactly as they appear "
            "in the system \u2014 do not translate or transliterate them.\n")

RETAIL_CATALOG = (
    "[AVAILABLE TOOLS]\n"
    "- cancel_pending_order \u2014 Cancel a pending order. If the order is already processed or delivered,\n"
    "    \n"
    "    it cannot be cancelled. The agent needs to explain the cancellation detail\n"
    "    and ask for explicit user confirmation (yes/no) to proceed.\n"
    "    order_id: string! \u2014 The order id, such as '#W0000000'. Be careful there is a '#' symbol.\n"
    "    reason: string! \u2014 The reason for cancellation, which should be either 'no longer needed' or 'ordered by mistake'.\n"
    "- exchange_delivered_order_items \u2014 Exchange items in a delivered order to new items of the same product type.\n"
    "    \n"
    "    The agent needs to explain the exchange detail and ask for explicit user confirmation (yes/no) to proceed.\n"
    "    order_id: string! \u2014 The order id, such as '#W0000000'.\n"
    "    item_ids: array! \u2014 The item ids to be exchanged, each such as '1008292230'.\n"
    "    new_item_ids: array! \u2014 The item ids to be exchanged for.\n"
    "    payment_method_id: string! \u2014 such as 'gift_card_0000000' or 'credit_card_0000000'.\n"
    "- find_user_id_by_name_zip \u2014 Find user id by first name, last name, and zip code. If the user is not found, the function\n"
    "    \n"
    "    will return an error message. By default, find user id by email.\n"
    "    first_name: string! \u2014 The first name of the customer, such as 'John'.\n"
    "    last_name: string! \u2014 The last name of the customer, such as 'Doe'.\n"
    "    zip: string! \u2014 The zip code of the customer, such as '12345'.\n"
    "- find_user_id_by_email \u2014 Find user id by email. If the user is not found, the function will return an error message.\n"
    "    email: string! \u2014 The email of the user, such as 'something@example.com'.\n"
    "- get_order_details \u2014 Get the status and details of an order.\n"
    "    order_id: string! \u2014 The order id, such as '#W0000000'.\n"
    "- list_all_product_types \u2014 List the name and product id of all product types.\n"
    "    \n"
    "    Each product type has a variety of different items with unique item ids and options.\n"
    "- transfer_to_human_agents \u2014 Transfer the user to a human agent, with a summary of the user's issue.\n"
    "    \n"
    "    Only transfer if\n"
    "     -  the user explicitly asks for a human agent\n"
    "    summary: string! \u2014 A summary of the user's issue.\n")

RETAIL_POLICY = ("<policy>\n# Retail agent policy\n\nYou should at most make one tool call at a time, and if you take a tool "
                 "call, you should not respond to the user at the same time.\n\nTo transfer, first make a tool call to "
                 "transfer_to_human_agents, and then send the message 'YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. "
                 "PLEASE HOLD ON.' to the user.\n</policy>\n\n")

RETAIL_106 = ("\u27e6SYSTEM\u27e7\n" + PREAMBLE + "\n" + RETAIL_POLICY + RETAIL_CATALOG +
              "\n\u27e6ASSISTANT\u27e7\n\u0417\u0434\u0440\u0430\u0432\u0441\u0442\u0432\u0443\u0439\u0442\u0435! \u0427\u0435\u043c \u043c\u043e\u0433\u0443 \u043f\u043e\u043c\u043e\u0447\u044c?\n\n"
              "\u27e6USER\u27e7\n\u0417\u0434\u0440\u0430\u0432\u0441\u0442\u0432\u0443\u0439\u0442\u0435. \u042f \u0445\u043e\u0447\u0443 \u043e\u0431\u043c\u0435\u043d\u044f\u0442\u044c \u0444\u0443\u0442\u0431\u043e\u043b\u043a\u0443.\n\n"
              "\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 1\u27e7\n\u041f\u043e\u0436\u0430\u043b\u0443\u0439\u0441\u0442\u0430, \u0443\u043a\u0430\u0436\u0438\u0442\u0435 email.\n\n"
              "\u27e6USER\u27e7\n\u041c\u0435\u043d\u044f \u0437\u043e\u0432\u0443\u0442 Sofia Thomas. \u041c\u043e\u0439 email \u2014 sofia.thomas3019@example.com.\n\n"
              "\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 2\u27e7\n"
              "\t\u2192 TOOL_CALL find_user_id_by_email: {\"email\": \"sofia.thomas3019@example.com\"}\n"
              "\t\u2190 TOOL_RESPONSE find_user_id_by_email [ERROR]: Error: User not found\n")
RESP_106 = ("\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 3\u27e7\n"
            "\t\u2192 TOOL_CALL find_user_id_by_name_zip: {\"first_name\": \"Sofia\", \"last_name\": \"Thomas\", \"zip\": \"3019\"}\n")

TELECOM_CATALOG = ("[AVAILABLE TOOLS]\n"
                   "- get_customer_by_phone \u2014 Finds a customer by their primary contact or line phone number.\n"
                   "    phone_number: string! \u2014 The phone number to search for.\n"
                   "- get_details_by_id \u2014 Retrieves the details for a given ID.\n"
                   "    \n"
                   "    The ID must be a valid ID for a Customer, Line, Device, Bill, or Plan.\n"
                   "    id: string! \u2014 The ID of the object to retrieve.\n"
                   "- resume_line \u2014 Resumes a suspended line.\n"
                   "    \n"
                   "    Checks: Line status must be Suspended or Pending Activation.\n"
                   "    Logic: Sets line status to Active, clears suspension_start_date.\n"
                   "    customer_id: string! \u2014 ID of the customer who owns the line.\n"
                   "    line_id: string! \u2014 ID of the line to resume.\n"
                   "- refuel_data \u2014 Refuels data for a specific line.\n"
                   "    customer_id: string! \u2014 ID of the customer who owns the line.\n"
                   "    line_id: string! \u2014 ID of the line to refuel data for.\n"
                   "    gb_amount: number! \u2014 Amount of data to add in gigabytes.\n"
                   "- transfer_to_human_agents \u2014 Transfer the user to a human agent.\n"
                   "    summary: string! \u2014 A summary of the user's issue.\n")
TELECOM = ("\u27e6SYSTEM\u27e7\n" + PREAMBLE + "\n<policy>\n# Telecom Agent Policy\n\nThe current time is 2025-02-25 12:08:00 EST.\n\n"
           "You should only make one tool call at a time.\n</policy>\n\n" + TELECOM_CATALOG +
           "\n\u27e6USER\u27e7\n\u041c\u0435\u043d\u044f \u0437\u043e\u0432\u0443\u0442 \u0414\u0436\u043e\u043d \u0421\u043c\u0438\u0442, \u043c\u043e\u0439 \u043d\u043e\u043c\u0435\u0440 \u2014 555-123-2002.\n\n"
           "\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 1\u27e7\n"
           "\t\u2192 TOOL_CALL get_customer_by_phone: {\"phone_number\": \"555-123-2002\"}\n"
           "\t\u2190 TOOL_RESPONSE get_customer_by_phone: {\"customer_id\": \"C1001\", \"full_name\": \"John Smith\", \"line_ids\": [\"L1001\", \"L1002\"], \"goodwill_credit_used_this_year\": 25.0}\n\n"
           "\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 2\u27e7\n"
           "\t\u2192 TOOL_CALL get_details_by_id: {\"id\": \"L1001\"}\n"
           "\t\u2192 TOOL_CALL run_speed_test: {}\n"
           "\t\u2190 TOOL_RESPONSE get_details_by_id: {\"line_id\": \"L1001\", \"status\": \"Active\", \"data_used_gb\": 3.2, \"contract_end_date\": \"2026-12-31\"}\n"
           "\t\u2190 TOOL_RESPONSE run_speed_test [ERROR]: Error: Tool 'run_speed_test' not found.\n\n"
           "\u27e6USER\u27e7\n"
           "\t\u2192 TOOL_CALL toggle_airplane_mode: {}\n"
           "\t\u2190 TOOL_RESPONSE toggle_airplane_mode: Airplane mode is now OFF.\n"
           "\u0413\u043e\u0442\u043e\u0432\u043e, \u0432\u044b\u043a\u043b\u044e\u0447\u0438\u043b.\n")

BANK = ("\u27e6SYSTEM\u27e7\n" + PREAMBLE + "\n<policy>\n# Rho-Bank Customer Service Policy\n</policy>\n\n"
        "[AVAILABLE TOOLS]\n"
        "- KB_search_dense \u2014 Search the knowledge base using dense embedding retrieval.\n"
        "    query: string! \u2014 The search query to find relevant documents.\n"
        "    k: integer \u2014 Maximum number of documents to return (default 10).\n"
        "- grep \u2014 Search for a regex pattern in all knowledge base documents.\n"
        "    \n"
        "    Returns documents ranked by number of matches, with full content.\n"
        "    pattern: string! \u2014 The regex pattern to search for (e.g., 'credit.*card', 'fee|charge')\n"
        "- transfer_to_human_agents \u2014 Transfer the user to a human agent.\n"
        "    summary: string! \u2014 A summary of the user's issue and what was attempted before transfer.\n"
        "    reason: string [enum: fraud_or_security_concern|customer_requests_human_no_specific_reason|other] \u2014 The specific reason code for the transfer.\n"
        "- get_current_time \u2014 Get the current time.\n"
        "- get_user_information_by_name \u2014 Get the information for a user by their name. Case Sensitive.\n"
        "    customer_name: string! \u2014 The name of the user\n"
        "- unlock_discoverable_agent_tool \u2014 Unlock an agent discoverable tool that was found in the knowledge base.\n"
        "    agent_tool_name: string! \u2014 The name of the agent discoverable tool to unlock (e.g., \"calculate_apr_adjustment_7842\")\n"
        "- call_discoverable_agent_tool \u2014 Call an agent discoverable tool that you have previously unlocked.\n"
        "    agent_tool_name: string! \u2014 The name of the agent discoverable tool to call\n"
        "    arguments: string \u2014 JSON string of arguments for the tool (e.g., '{\"user_id\": \"abc123\"}')\n"
        "\n\u27e6USER\u27e7\nHi, I'm looking to open a new checking account.\n\n"
        "\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 1\u27e7\n"
        "\t\u2192 TOOL_CALL KB_search_dense: {\"query\": \"open checking account\"}\n"
        "\t\u2190 TOOL_RESPONSE KB_search_dense: 1. \u0412\u043d\u0443\u0442\u0440\u0435\u043d\u043d\u0438\u0439 \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\n"
        "\t     ID: doc_bank_accounts_001\n"
        "\t     Score: 0.6682\n"
        "\t  \n"
        "\t  - \u0418\u043d\u0441\u0442\u0440\u0443\u043c\u0435\u043d\u0442: open_bank_account_4821(user_id, account_type, account_class)\n"
        "\t  - get_bank_account_transactions_9173(account_id)\n"
        "\t  \n"
        "\t  [Timing: retrieval=2ms, reranking=0ms, total=2ms]\n\n"
        "\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 2\u27e7\n"
        "\t\u2192 TOOL_CALL get_user_information_by_name: {\"customer_name\": \"Kenji Tanaka\"}\n"
        "\t\u2190 TOOL_RESPONSE get_user_information_by_name: Found 1 record(s) in 'users':\n"
        "\t  \n"
        "\t  1. Record ID: 6680a37184\n"
        "\t     name: Kenji Tanaka\n"
        "\t     phone_number: 206-555-0293\n"
        "\t  \n\n"
        "\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 3\u27e7\n"
        "\t\u2192 TOOL_CALL unlock_discoverable_agent_tool: {\"agent_tool_name\": \"open_bank_account_4821\"}\n"
        "\t\u2190 TOOL_RESPONSE unlock_discoverable_agent_tool: Tool 'open_bank_account_4821' unlocked.\n\n"
        "\u27e6USER\u27e7\n\u0414\u0430, \u043e\u0442\u043a\u0440\u044b\u0432\u0430\u0439\u0442\u0435.\n")


class Parser(unittest.TestCase):
    def test_error_status_before_colon_is_a_result(self):
        d = parse_document(RETAIL_106, 'prompt')
        res = d.results()
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].status, 'ERROR')
        self.assertEqual(res[0].body, 'Error: User not found')
        call = d.calls()[0]
        self.assertTrue(call.is_json)
        self.assertEqual(call.pair, res[0].index)
        self.assertEqual(res[0].owner, 'assistant')

    def test_messages_and_turn_numbers(self):
        d = parse_document(RETAIL_106, 'prompt')
        self.assertEqual([m.role for m in d.messages], ['system', 'assistant', 'user', 'assistant', 'user', 'assistant'])
        self.assertEqual([m.number for m in d.messages if m.role == 'assistant'], [None, 1, 2])
        self.assertEqual(d.diagnostics, [])

    def test_response(self):
        r = parse_document(RESP_106, 'response')
        self.assertEqual(r.messages[0].number, 3)
        self.assertEqual(r.calls()[0].value, {'first_name': 'Sofia', 'last_name': 'Thomas', 'zip': '3019'})
        self.assertEqual(r.diagnostics, [])

    def test_parallel_calls_pair_fifo_by_name(self):
        d = parse_document(TELECOM, 'prompt')
        calls = {c.tool: c for c in d.calls()}
        self.assertEqual(d.events[calls['get_details_by_id'].pair].value['line_id'], 'L1001')
        self.assertTrue(d.events[calls['run_speed_test'].pair].is_error)

    def test_user_device_tool_is_owned_by_user(self):  # ASSUMED layout of user tool calls
        d = parse_document(TELECOM, 'prompt')
        c = [c for c in d.calls() if c.tool == 'toggle_airplane_mode'][0]
        self.assertEqual(c.owner, 'user')
        self.assertEqual(d.events[c.pair].owner, 'user')
        text = d.texts(role='user')[-1]
        self.assertIn('TEXT_AFTER_RESULT_WITHOUT_HEADER', text.diagnostics)

    def test_multiline_plain_text_result_is_dedented(self):
        d = parse_document(BANK, 'prompt')
        res = [e for e in d.results() if e.tool == 'get_user_information_by_name'][0]
        self.assertIn('1. Record ID: 6680a37184', res.body)
        self.assertIn('   name: Kenji Tanaka', res.body)
        self.assertFalse(res.is_json)
        kb = [e for e in d.results() if e.tool == 'KB_search_dense'][0]
        self.assertIn('[Timing: retrieval=2ms', kb.body)
        self.assertEqual(kb.status, 'OK')

    def test_text_and_call_in_one_response(self):
        r = parse_document('\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 5\u27e7\n\u0421\u0435\u0439\u0447\u0430\u0441 \u043f\u0440\u043e\u0432\u0435\u0440\u044e.\n\t\u2192 TOOL_CALL get_order_details: {\"order_id\": \"#W1\"}\n', 'response')
        self.assertEqual([e.kind for e in r.events], ['text', 'call'])
        r = parse_document('\u27e6ASSISTANT\u27e7\n\t\u2192 TOOL_CALL x: {\"a\": 1} \u0438 \u0435\u0449\u0451 \u0442\u0435\u043a\u0441\u0442\n', 'response')
        self.assertEqual([e.kind for e in r.events], ['call', 'text'])
        self.assertIn('TEXT_AFTER_CALL_SAME_LINE', r.events[1].diagnostics)

    def test_multiline_json_arguments(self):
        r = parse_document('\u27e6ASSISTANT\u27e7\n\t\u2192 TOOL_CALL x: {\"a\": [1,\n2], \"b\": \"c\"}\n', 'response')
        self.assertEqual(r.calls()[0].value, {'a': [1, 2], 'b': 'c'})
        self.assertIn('MULTILINE_ARGUMENTS', r.calls()[0].diagnostics)

    def test_official_header_dialect(self):
        p = ('\u27e6SYSTEM\u27e7\npolicy\n\u27e6USER\u27e7\nhi\n\u27e6ASSISTANT_TOOL_CALL name=\"get_x\"\u27e7\n{\"id\": \"A1\"}\n'
             '\u27e6TOOL_RESULT name=\"get_x\" requestor=\"assistant\"\u27e7\n{\"ok\": true}\n')
        d = parse_document(p, 'prompt')
        call, res = d.calls()[0], d.results()[0]
        self.assertEqual((call.tool, call.dialect, call.value), ('get_x', 'header', {'id': 'A1'}))
        self.assertEqual((res.pair, res.owner, res.value), (call.index, 'assistant', {'ok': True}))

    def test_crlf_and_ascii_arrows(self):
        p = '\u27e6SYSTEM\u27e7\r\nx\r\n\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 1\u27e7\r\n\t-> TOOL_CALL f: {\"a\": 1}\r\n\t<- TOOL_RESPONSE f: {\"b\": 2}\r\n'
        d = parse_document(p, 'prompt')
        self.assertEqual(d.calls()[0].value, {'a': 1})
        self.assertEqual(d.results()[0].value, {'b': 2})

    def test_never_raises(self):
        for text in (None, '', '\u27e6', '\u2192 TOOL_CALL x: {', '\u27e6UNKNOWN\u27e7\nz', '\t\u2190 TOOL_RESPONSE y [ERR'):
            parse_document(text, 'prompt')
            analyze(text, text)

    def test_stats(self):
        s = document_stats(parse_document(TELECOM, 'prompt'))
        self.assertEqual(s['result_error'], 1)
        self.assertEqual(s['call_user'], 1)


class System(unittest.TestCase):
    def test_policy_catalog_time(self):
        d = parse_document(TELECOM, 'prompt')
        s = parse_system(d)
        self.assertTrue(s.policy_tagged)
        self.assertIn('Telecom Agent Policy', s.policy_text(TELECOM))
        self.assertNotIn('according to the', s.policy_text(TELECOM))
        self.assertEqual(s.current_time['date'], '2025-02-25')
        self.assertTrue(s.one_call_rule and s.exclusive_rule)
        self.assertEqual(s.language, 'russian')
        self.assertTrue(s.catalog.complete, s.catalog.issues)
        self.assertEqual(sorted(s.catalog.tools), ['get_customer_by_phone', 'get_details_by_id', 'refuel_data',
                                                   'resume_line', 'transfer_to_human_agents'])
        resume = s.catalog.tools['resume_line']
        self.assertEqual([p.name for p in resume.params], ['customer_id', 'line_id'])
        self.assertIn('Checks: Line status', resume.description)

    def test_enum_required_confirmation(self):
        s = parse_system(parse_document(BANK, 'prompt'))
        reason = s.catalog.tools['transfer_to_human_agents'].param('reason')
        self.assertEqual(reason.enum[0], 'fraud_or_security_concern')
        self.assertFalse(reason.required)
        self.assertEqual(s.catalog.tools['get_current_time'].params, [])
        grep = s.catalog.tools['grep']
        self.assertEqual([p.name for p in grep.params], ['pattern'])
        r = parse_system(parse_document(RETAIL_106, 'prompt'))
        self.assertTrue(r.catalog.tools['cancel_pending_order'].requires_confirmation)
        self.assertEqual(r.transfer_phrase, 'YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON.')

    def test_validation(self):
        s = parse_system(parse_document(TELECOM, 'prompt'))
        spec = s.catalog.tools['refuel_data']
        self.assertEqual(validate_arguments(spec, {'customer_id': 'C1', 'line_id': 'L1', 'gb_amount': 2}), [])
        issues = validate_arguments(spec, {'customer_id': 'C1', 'gb_amount': '2', 'extra': 1})
        self.assertIn('MISSING $.line_id', issues)
        self.assertTrue(any(i.startswith('TYPE $.gb_amount') for i in issues))
        self.assertIn('UNEXPECTED $.extra', issues)


class Values(unittest.TestCase):
    def test_numbers(self):
        got = {n.raw: n.values for n in parse_numbers('\u0418\u0442\u043e\u0433\u043e $1,234.56, \u0430 \u0442\u0430\u043a\u0436\u0435 1\u00a0234,56 \u0440\u0443\u0431 \u0438 299,99 \u0438 12.5%')}
        self.assertIn(1234.56, got['1,234.56'])
        self.assertIn(1234.56, got['1 234,56'])
        self.assertIn(299.99, got['299,99'])
        self.assertIn(12.5, got['12.5%'])
        masked = parse_numbers('2025-11-14 03:40:00, 206-555-0293, L1001, #W0000000, 07/22/1985')
        self.assertEqual(masked, [])

    def test_dates(self):
        ds = [d for d, *_ in parse_dates('14 \u043d\u043e\u044f\u0431\u0440\u044f 2025, 2025-02-25, 07/22/1985, May 15, 2024')]
        self.assertEqual([str(d) for d in ds], ['2025-11-14', '2025-02-25', '1985-07-22', '2024-05-15'])

    def test_bounded_search(self):
        hits = find_token('email sofia.thomas3019@example.com', '3019')
        self.assertEqual(hits, [(18, False)])
        self.assertEqual(find_token('zip 3019.', '3019'), [(4, True)])

    def test_value_kind(self):
        self.assertEqual(value_kind('zip', '3019'), 'id')
        self.assertEqual(value_kind('email', 'a@b.com'), 'email')
        self.assertEqual(value_kind('phone_number', '206-555-0293'), 'phone')
        self.assertEqual(value_kind('order_id', '#W0000000'), 'id')


class Features(unittest.TestCase):
    def test_zip_taken_from_email_is_strong_not_hard(self):
        t = analyze_turn(RETAIL_106, RESP_106)
        self.assertEqual(t.hard, [])
        self.assertTrue(any(s.startswith('arg_inside_token find_user_id_by_name_zip') for s in t.strong), t.strong)

    def test_repeat_of_failed_unknown_tool_is_hard(self):
        t = analyze_turn(TELECOM, '\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 6\u27e7\n\t\u2192 TOOL_CALL run_speed_test: {}\n')
        self.assertTrue(any(h.startswith('unavailable_tool run_speed_test (failed_before)') for h in t.hard), t.hard)
        self.assertTrue(any(s.startswith('repeat_of_failed_call') for s in t.strong))

    def test_agent_calling_user_device_tool_is_hard(self):
        t = analyze_turn(TELECOM, '\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 3\u27e7\n\t\u2192 TOOL_CALL toggle_airplane_mode: {}\n')
        self.assertTrue(any('(user_tool)' in h for h in t.hard), t.hard)

    def test_catalog_call_is_clean(self):
        t = analyze_turn(TELECOM, '\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 3\u27e7\n\t\u2192 TOOL_CALL get_details_by_id: {\"id\": \"L1002\"}\n')
        self.assertEqual(t.hard, [])
        self.assertEqual(t.strong, [], t.strong)

    def test_absent_identifier(self):
        t = analyze_turn(TELECOM, '\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 3\u27e7\n\t\u2192 TOOL_CALL get_details_by_id: {\"id\": \"L7777\"}\n')
        self.assertTrue(any(s.startswith('arg_absent get_details_by_id') for s in t.strong), t.strong)

    def test_discoverable_direct_call_is_hard(self):
        t = analyze_turn(BANK, '\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 4\u27e7\n\t\u2192 TOOL_CALL get_bank_account_transactions_9173: {\"account_id\": \"A1\"}\n')
        self.assertTrue(any('get_bank_account_transactions_9173 (mentioned_not_declared)' in h for h in t.hard), t.hard)
        t = analyze_turn(BANK, '\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 4\u27e7\n\t\u2192 TOOL_CALL open_bank_account_4821: {\"user_id\": \"6680a37184\"}\n')
        self.assertTrue(any('(discoverable_unlocked_direct)' in h for h in t.hard), t.hard)

    def test_discoverable_via_call_tool(self):
        args = json.dumps({'agent_tool_name': 'open_bank_account_4821', 'arguments': json.dumps({'user_id': '6680a37184'})})
        ok = analyze_turn(BANK, '\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 4\u27e7\n\t\u2192 TOOL_CALL call_discoverable_agent_tool: ' + args + '\n')
        self.assertEqual(ok.hard, [], ok.hard)
        self.assertFalse(any(s.startswith('discoverable_not_unlocked') for s in ok.strong), ok.strong)
        self.assertEqual(ok.calls[0].event.nested['arguments'], {'user_id': '6680a37184'})
        bad = analyze_turn(BANK, '\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 4\u27e7\n\t\u2192 TOOL_CALL call_discoverable_agent_tool: {\"agent_tool_name\": \"close_debit_card_4721\", \"arguments\": \"{}\"}\n')
        self.assertTrue(any(s.startswith('discoverable_not_unlocked') for s in bad.strong))

    def test_russian_refusal_and_claims(self):
        t = analyze_turn(RETAIL_106, '\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 3\u27e7\n\u041a \u0441\u043e\u0436\u0430\u043b\u0435\u043d\u0438\u044e, \u043e\u0431\u043c\u0435\u043d \u043d\u0435\u0432\u043e\u0437\u043c\u043e\u0436\u0435\u043d.\n')
        self.assertIn('refusal_wording', t.weak)
        t = analyze_turn(RETAIL_106, '\u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 3\u27e7\n\u0417\u0430\u043a\u0430\u0437 \u0443\u0441\u043f\u0435\u0448\u043d\u043e \u043e\u0442\u043c\u0435\u043d\u0451\u043d.\n')
        self.assertIn('completion_claim_after_error', t.strong)

    def test_reply_numbers(self):
        t = analyze_turn(TELECOM, '\u27e6ASSISTANT\u27e7\n\u0412\u044b \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043b\u0438 3,2 \u0413\u0411, \u0431\u043e\u043d\u0443\u0441 $25.00.\n')
        self.assertFalse(any(w.startswith('reply_numbers') for w in t.weak), t.weak)
        t = analyze_turn(TELECOM, '\u27e6ASSISTANT\u27e7\n\u0421 \u0432\u0430\u0441 \u0441\u043f\u0438\u0448\u0443\u0442 $517.\n')
        self.assertTrue(any(w.startswith('reply_numbers') for w in t.weak), t.weak)

    def test_write_without_confirmation(self):
        t = analyze_turn(TELECOM, '\u27e6ASSISTANT\u27e7\n\t\u2192 TOOL_CALL resume_line: {\"customer_id\": \"C1001\", \"line_id\": \"L1001\"}\n')
        self.assertTrue(any(w.startswith('write_without_explicit_confirmation') for w in t.weak))
        t = analyze_turn(BANK, '\u27e6ASSISTANT\u27e7\n\t\u2192 TOOL_CALL call_discoverable_agent_tool: {\"agent_tool_name\": \"open_bank_account_4821\", \"arguments\": \"{}\"}\n')
        self.assertFalse(any(w.startswith('write_without') for w in t.weak), t.weak)


if __name__ == '__main__':
    unittest.main()
