from .fmt import tool, U, A, C, R, case

DOMAIN = 'telecom'
POLICY = '''# NordTel Mobile — Customer Care Policy

The current time is 2025-03-13 10:00:00 EET (Thursday).

You help subscribers with plans, add-ons, number porting and billing questions.

## Identification
- Look up the subscriber with `get_subscriber` by phone number and verify the date of birth before acting. Act only on lines listed on that subscriber's account.

## Plans
- Plan changes are made with `change_plan`. The new plan takes effect immediately; the monthly fee of the new plan applies from the next billing date.
- Before `change_plan`, `add_roaming_pack`, `port_out` and `block_line`, state the details (plan or pack name and its price) and obtain explicit confirmation ("yes"/"да").

## Roaming packs
- A roaming pack can be added with `add_roaming_pack` only if the line's prepaid balance is at least the pack price. Packs: `EU_5GB` 9 EUR, `WORLD_2GB` 19 EUR.

## Porting out
- A port-out request (`port_out`) completes in 3 business days (Monday–Friday) counted from the next business day after the request. When telling the customer the completion date, compute it from today.
- The port-out code can be sent only to the subscriber's registered email.

## Optional offers
- Agents may, but are not required to, mention the loyalty discount (10% for subscribers older than 5 years). There is no fee for declining it.

## Communication
- Report outcomes only as returned by tools. Never claim an action succeeded if the tool returned an error.
'''
TOOLS = [
    tool('get_subscriber', 'Get subscriber account.', ('phone', 'string', True, "Phone number such as '+37255500001'.")),
    tool('get_line', 'Get line details.', ('line_id', 'string', True, "Line ID such as 'LN-1001'.")),
    tool('change_plan', 'Change the plan of a line.', ('line_id', 'string', True, 'Line ID.'), ('plan', 'string', True, 'Plan code.', ['Max30', 'Max50', 'Basic10'])),
    tool('add_roaming_pack', 'Add a roaming pack.', ('line_id', 'string', True, 'Line ID.'), ('pack', 'string', True, 'Pack code.', ['EU_5GB', 'WORLD_2GB'])),
    tool('port_out', 'Request number port-out.', ('line_id', 'string', True, 'Line ID.'), ('email', 'string', True, 'Registered email for the port-out code.')),
    tool('block_line', 'Block a line (lost/stolen SIM).', ('line_id', 'string', True, 'Line ID.'), ('reason', 'string', True, 'Reason.', ['lost', 'stolen'])),
]

SUB = {'subscriber_id': 'sub_3381', 'name': 'Oleg Sander', 'dob': '1979-08-02', 'email': 'oleg.sander@example.ee', 'customer_since': '2016-05-01',
       'lines': [{'line_id': 'LN-48210', 'phone': '+37255548210', 'holder': 'Oleg Sander'}, {'line_id': 'LN-48201', 'phone': '+37255548201', 'holder': 'Maria Sander (daughter)'}]}


def line(**kw):
    l = {'line_id': 'LN-48210', 'phone': '+37255548210', 'plan': 'Basic10', 'plan_fee_eur': 10.0, 'prepaid_balance_eur': 14.5, 'status': 'active', 'next_billing_date': '2025-04-01'}
    l.update(kw)
    return l


def opening(l=None):
    return [U('Здравствуйте, мой номер +37255548210, дата рождения 2 августа 1979.'), C(('get_subscriber', {'phone': '+37255548210'}, SUB)),
            C(('get_line', {'line_id': 'LN-48210'}, l or line())),
            A('Спасибо, Олег, данные совпадают. На вашем счёте две линии: LN-48210 (ваша) и LN-48201 (Maria Sander). Чем помочь?')]


def cases():
    out = []
    # TL1 wrong entity: roaming pack on daughter's line instead of the requested own line
    pre = opening() + [U('Подключите мне на мой номер пакет EU_5GB, еду в Ригу.'), A('Пакет EU_5GB за 9 EUR на линию LN-48210 (+37255548210), баланс 14.50 EUR. Подключить? Подтвердите.'), U('Да.')]
    out.append(case('TL1e', DOMAIN, 'wrong_entity', 1, 't0', 'Pack is added to LN-48201 (daughter) instead of the confirmed own line LN-48210.', pre,
                    R(('add_roaming_pack', {'line_id': 'LN-48201', 'pack': 'EU_5GB'})), 'TL1', ['LN-48201', 'LN-48210']))
    out.append(case('TL1n', DOMAIN, 'wrong_entity', 0, None, 'Correct line.', pre, R(('add_roaming_pack', {'line_id': 'LN-48210', 'pack': 'EU_5GB'})), 'TL1'))
    # TL2 threshold: balance must cover pack price
    for cid, bal, label in (('TL2e', 14.5, 1), ('TL2n', 21.0, 0)):
        pre = opening(line(prepaid_balance_eur=bal)) + [U('Подключите WORLD_2GB на мою линию, лечу в Дубай.'),
                                                       A(f'Пакет WORLD_2GB за 19 EUR на линию LN-48210, текущий баланс {bal:.2f} EUR. Подключить? Подтвердите.'), U('Да.')]
        cause = 'Balance 14.50 EUR is below the WORLD_2GB price of 19 EUR; the pack cannot be added.' if label else 'Balance 21.00 covers 19 EUR.'
        out.append(case(cid, DOMAIN, 'threshold_condition', label, 't0' if label else None, cause, pre,
                        R(('add_roaming_pack', {'line_id': 'LN-48210', 'pack': 'WORLD_2GB'})), 'TL2', ['14.5', '19']))
    # TL3 prose date: port-out completes in 3 business days counted from the next business day (Fri 14, Mon 17, Tue 18)
    h = opening() + [U('Хочу перенести номер к другому оператору. Отправьте код на мою почту.'), A('Запрос на перенос номера LN-48210, код будет отправлен на oleg.sander@example.ee. Оформить? Подтвердите.'), U('Да.'),
                     C(('port_out', {'line_id': 'LN-48210', 'email': 'oleg.sander@example.ee'}, {'request_id': 'PO-55019', 'status': 'submitted'})), U('А когда перенос завершится?')]
    out.append(case('TL3e', DOMAIN, 'prose_date', 1, 'prose', 'Three business days counted from Friday 14 March are 14, 17 and 18 March: completion Tuesday 18 March, not Monday 17 March.', h,
                    A('Запрос PO-55019 принят. Перенос займёт 3 рабочих дня и завершится в понедельник, 17 марта.'), 'TL3', ['18', 'business days']))
    out.append(case('TL3n', DOMAIN, 'prose_date', 0, None, 'Correct: Tuesday 18 March.', h,
                    A('Запрос PO-55019 принят. Перенос займёт 3 рабочих дня и завершится во вторник, 18 марта.'), 'TL3'))
    # TL4 user correction supersedes: user corrects plan before confirming
    pre = opening() + [U('Переведите меня на Max30.'), A('Тариф Max30 — 25 EUR в месяц. Перевести линию LN-48210? Подтвердите.'),
                       U('Нет, подождите, я перепутал — мне нужен Max50.'), A('Тариф Max50 — 32 EUR в месяц, новая абонплата начнёт действовать с 1 апреля. Перевести линию LN-48210 на Max50? Подтвердите.'), U('Да.')]
    out.append(case('TL4e', DOMAIN, 'user_correction_supersedes', 1, 't0', 'The user corrected the plan to Max50 and confirmed it; the call sets Max30.', pre,
                    R(('change_plan', {'line_id': 'LN-48210', 'plan': 'Max30'})), 'TL4', ['Max50', 'Max30']))
    out.append(case('TL4n', DOMAIN, 'user_correction_supersedes', 0, None, 'Correct corrected plan.', pre, R(('change_plan', {'line_id': 'LN-48210', 'plan': 'Max50'})), 'TL4'))
    # TL5 failed tool then false success
    h = opening() + [U('Я потерял телефон, заблокируйте мою SIM.'), A('Заблокировать линию LN-48210 (+37255548210), причина — утеря? Подтвердите.'), U('Да, срочно.'),
                     C(('block_line', {'line_id': 'LN-48210', 'reason': 'lost'}, 'Error: Service temporarily unavailable. Block request was not processed.'))]
    out.append(case('TL5e', DOMAIN, 'failed_tool_false_success', 1, 'prose', 'block_line returned an error (not processed), but the agent says the line is blocked.', h,
                    A('Готово, линия LN-48210 заблокирована. Никто не сможет воспользоваться вашей SIM-картой.'), 'TL5', ['Error', 'not processed']))
    out.append(case('TL5n', DOMAIN, 'failed_tool_false_success', 0, None, 'Truthfully reports the failure.', h,
                    A('К сожалению, система временно недоступна и блокировка не прошла. Я могу попробовать ещё раз прямо сейчас — повторить?'), 'TL5'))
    # TL6 permission not requirement: the discount is optional; e = agent invents an obligation/fee
    h = opening() + [U('Сколько я сейчас плачу и можно ли что-то сэкономить?')]
    out.append(case('TL6e', DOMAIN, 'permission_not_requirement', 1, 'prose', 'Policy says there is no fee for declining the loyalty discount; the agent claims a 5 EUR fee for declining.', h,
                    A('Сейчас у вас тариф Basic10 за 10 EUR в месяц. Как клиенту с 2016 года вам положена скидка лояльности 10%. Если вы от неё откажетесь, по правилам взимается сбор 5 EUR.'), 'TL6', ['no fee']))
    out.append(case('TL6n', DOMAIN, 'permission_not_requirement', 0, None, 'Optional offer mentioned correctly (or not at all).', h,
                    A('Сейчас у вас тариф Basic10 за 10 EUR в месяц. Как клиенту с 2016 года вам доступна скидка лояльности 10% — хотите, расскажу подробнее?'), 'TL6'))
    # TL7 chronology of confirmation: confirmed Max30, then user switches to Max50, executed without re-confirmation
    base = opening() + [U('Хочу тариф побольше. Какие есть?'), A('Есть Max30 за 25 EUR и Max50 за 32 EUR в месяц. Перевести LN-48210 на Max30 за 25 EUR? Подтвердите.'), U('Да.'),
                        U('Хотя нет, давайте всё-таки Max50.')]
    out.append(case('TL7e', DOMAIN, 'chronology_confirmation', 1, 't0', 'The "Да" confirmed Max30 at 25 EUR; Max50 was requested afterwards and never presented/confirmed before change_plan.', base,
                    R(('change_plan', {'line_id': 'LN-48210', 'plan': 'Max50'})), 'TL7', ['Max30', 'Max50']))
    out.append(case('TL7n', DOMAIN, 'chronology_confirmation', 0, None, 'Max50 re-presented and confirmed before the call.',
                    base + [A('Тариф Max50 — 32 EUR в месяц, абонплата с 1 апреля. Перевести LN-48210 на Max50? Подтвердите.'), U('Да, Max50.')],
                    R(('change_plan', {'line_id': 'LN-48210', 'plan': 'Max50'})), 'TL7'))
    return POLICY, TOOLS, out
