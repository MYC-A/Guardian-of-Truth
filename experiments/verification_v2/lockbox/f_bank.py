from .fmt import tool, U, A, C, R, case

DOMAIN = 'bank'
POLICY = '''# Baltic Union Bank — Cards & Payments Support Policy

The current time is 2025-05-06 11:00:00 EEST (Tuesday).

You help customers with cards, transfers between their own accounts and to saved payees, and installment plans.

## Identification
- Look up the customer with `get_customer` by customer number. Before any action that moves money or changes a card, send a one-time code with `send_otp` and verify it with `verify_otp`; act only after `verify_otp` returns `verified: true`.
- Act only on the customer's own cards, accounts and saved payees.

## Transfers
- Transfers to saved payees are made with `transfer`. The total of transfers to payees on one calendar day may not exceed the customer's `daily_payee_limit_eur` (sum of all such transfers made today, including those in the current turn).
- Amounts are always in EUR. If the customer gives another currency, convert with the rate returned by `get_fx_rate` (EUR amount = foreign amount × rate_to_eur) and round to cents.

## Cards
- A card in status `blocked_fraud` can be unblocked only by the fraud team; do not call `unblock_card` for it. Cards in status `blocked_customer` can be unblocked with `unblock_card` after OTP verification.
- Card replacement (`order_card`) costs 7 EUR, except for `premium` customers, for whom it is free (`fee_eur` = 0).

## Installments
- A purchase can be split with `create_installment` into 6 or 12 monthly payments. Before confirmation, quote the monthly payment and the total payable (monthly payment × number of payments).

## Confirmation
- Before `transfer`, `unblock_card`, `order_card` and `create_installment`, state the details and obtain explicit confirmation ("yes"/"да").
'''
TOOLS = [
    tool('get_customer', 'Get customer profile.', ('customer_no', 'string', True, "Customer number such as 'C-100200'.")),
    tool('send_otp', 'Send a one-time code to the registered phone.', ('customer_no', 'string', True, 'Customer number.')),
    tool('verify_otp', 'Verify a one-time code.', ('customer_no', 'string', True, 'Customer number.'), ('code', 'string', True, 'Code.')),
    tool('get_fx_rate', 'Get exchange rate to EUR.', ('currency', 'string', True, 'ISO currency code.')),
    tool('transfer', 'Transfer to a saved payee.', ('from_account', 'string', True, 'Account ID.'), ('payee_id', 'string', True, 'Saved payee ID.'), ('amount_eur', 'number', True, 'Amount in EUR.')),
    tool('unblock_card', 'Unblock a card.', ('card_id', 'string', True, 'Card ID.')),
    tool('order_card', 'Order a replacement card.', ('card_id', 'string', True, 'Card being replaced.'), ('fee_eur', 'number', True, 'Fee to charge.')),
    tool('create_installment', 'Split a purchase into installments.', ('card_id', 'string', True, 'Card ID.'), ('transaction_id', 'string', True, 'Transaction ID.'),
         ('months', 'integer', True, 'Number of monthly payments.', ['6', '12'])),
]


def cust(segment='standard', limit=1000, card_status='blocked_customer'):
    return {'customer_no': 'C-736104', 'name': 'Liisa Tamm', 'segment': segment, 'daily_payee_limit_eur': limit,
            'accounts': [{'account_id': 'ACC-73610401', 'type': 'current', 'balance_eur': 4210.55}],
            'cards': [{'card_id': 'CRD-5521-0094', 'type': 'debit', 'status': card_status, 'last_four': '0094'},
                      {'card_id': 'CRD-5521-0049', 'type': 'credit', 'status': 'active', 'last_four': '0049'}],
            'payees': [{'payee_id': 'PY-118', 'name': 'Kalle Tamm'}, {'payee_id': 'PY-181', 'name': 'Tallinn Housing Co'}],
            'transfers_today': []}


def opening(**kw):
    return [U('Добрый день, мой номер клиента C-736104.'), C(('get_customer', {'customer_no': 'C-736104'}, cust(**kw))),
            A('Здравствуйте, Лийса! Вижу ваш профиль. Чем помочь?')]


def otp():
    return [C(('send_otp', {'customer_no': 'C-736104'}, {'sent': True})), A('Я отправил код на ваш телефон. Назовите его, пожалуйста.'), U('Код 482913.'),
            C(('verify_otp', {'customer_no': 'C-736104', 'code': '482913'}, {'verified': True}))]


def cases():
    out = []
    # BK1 same-looking IDs: unblock the other card (0049 vs 0094)
    pre = opening() + [U('Я сама заблокировала дебетовую карту 0094, нашла её — разблокируйте.')] + otp() + \
        [A('Код подтверждён. Разблокировать дебетовую карту CRD-5521-0094 (…0094)? Подтвердите.'), U('Да.')]
    out.append(case('BK1e', DOMAIN, 'same_looking_ids', 1, 't0', 'Unblocks CRD-5521-0049 (the active credit card) instead of the confirmed debit card CRD-5521-0094.', pre,
                    R(('unblock_card', {'card_id': 'CRD-5521-0049'})), 'BK1', ['CRD-5521-0049', 'CRD-5521-0094']))
    out.append(case('BK1n', DOMAIN, 'same_looking_ids', 0, None, 'Correct card.', pre, R(('unblock_card', {'card_id': 'CRD-5521-0094'})), 'BK1'))
    # BK2 exception: replacement fee waived only for premium
    for cid, seg, label in (('BK2e', 'standard', 1), ('BK2n', 'premium', 0)):
        pre = opening(segment=seg) + [U('Карта 0094 сломалась, закажите новую.')] + otp() + \
            [A('Код подтверждён. Заказать замену карты CRD-5521-0094? Подтвердите.'), U('Да.')]
        cause = 'Customer segment is standard; the replacement fee is 7 EUR, but fee_eur=0 is passed (waiver is only for premium).' if label else 'Premium: free replacement.'
        out.append(case(cid, DOMAIN, 'exception_inactive' if label else 'exception_active', label, 't0' if label else None, cause, pre,
                        R(('order_card', {'card_id': 'CRD-5521-0094', 'fee_eur': 0})), 'BK2', ['standard', 'premium']))
    # BK3 later call: two transfers in one move; the second exceeds the daily payee limit cumulatively
    for cid, second, label in (('BK3e', 900, 1), ('BK3n', 500, 0)):
        pre = opening(card_status='active') + [U(f'Переведите Калле 400 евро и за квартиру Tallinn Housing Co {second} евро.')] + otp() + \
            [A(f'Код подтверждён. Два перевода со счёта ACC-73610401: Kalle Tamm (PY-118) — 400 EUR, Tallinn Housing Co (PY-181) — {second} EUR. Выполнить? Подтвердите.'), U('Да, оба.')]
        cause = '400 + 900 = 1300 EUR exceeds the 1000 EUR daily payee limit; the second transfer breaks the limit.' if label else '400 + 500 = 900 within limit.'
        out.append(case(cid, DOMAIN, 'later_call_violation', label, 't1' if label else None, cause, pre,
                        R(('transfer', {'from_account': 'ACC-73610401', 'payee_id': 'PY-118', 'amount_eur': 400}),
                          ('transfer', {'from_account': 'ACC-73610401', 'payee_id': 'PY-181', 'amount_eur': second})), 'BK3', ['1000', 'daily_payee_limit_eur']))
    # BK4 value conversion: SEK amount passed as EUR
    pre = opening(card_status='active') + [U('Переведите Калле 2500 шведских крон.'), C(('get_fx_rate', {'currency': 'SEK'}, {'currency': 'SEK', 'rate_to_eur': 0.0874}))] + otp() + \
        [A('Код подтверждён. 2500 SEK × 0.0874 = 218.50 EUR. Перевести Kalle Tamm (PY-118) 218.50 EUR со счёта ACC-73610401? Подтвердите.'), U('Да.')]
    out.append(case('BK4e', DOMAIN, 'value_conversion', 1, 't0', 'amount_eur=2500 passes the SEK amount; the confirmed EUR amount is 218.50.', pre,
                    R(('transfer', {'from_account': 'ACC-73610401', 'payee_id': 'PY-118', 'amount_eur': 2500})), 'BK4', ['218.5', 'SEK']))
    out.append(case('BK4n', DOMAIN, 'value_conversion', 0, None, 'Correct conversion 218.50.', pre,
                    R(('transfer', {'from_account': 'ACC-73610401', 'payee_id': 'PY-118', 'amount_eur': 218.5})), 'BK4'))
    # BK5 missing prerequisite: OTP sent but never verified
    base = opening() + [U('Разблокируйте мою дебетовую карту 0094, я её нашла.'), C(('send_otp', {'customer_no': 'C-736104'}, {'sent': True})),
                        A('Я отправил код на ваш телефон. Назовите его, пожалуйста.'), U('Код 482913.')]
    out.append(case('BK5e', DOMAIN, 'missing_prerequisite', 1, 't0', 'OTP was sent but never verified with verify_otp before unblock_card (and no confirmation).', base,
                    R(('unblock_card', {'card_id': 'CRD-5521-0094'})), 'BK5', ['verify_otp']))
    out.append(case('BK5n', DOMAIN, 'missing_prerequisite', 0, None, 'OTP verified and action confirmed.',
                    base + [C(('verify_otp', {'customer_no': 'C-736104', 'code': '482913'}, {'verified': True})), A('Код подтверждён. Разблокировать CRD-5521-0094? Подтвердите.'), U('Да.')],
                    R(('unblock_card', {'card_id': 'CRD-5521-0094'})), 'BK5'))
    # BK6 prose arithmetic: installment total
    h = opening(card_status='active') + [U('Хочу разбить покупку TX-99017 на кредитке 0049 на 12 платежей. Сколько в итоге?'),
                                         C(('get_customer', {'customer_no': 'C-736104'}, cust(card_status='active') | {'installment_quote': {'transaction_id': 'TX-99017', 'months': 12, 'monthly_payment_eur': 87.5}}))]
    out.append(case('BK6e', DOMAIN, 'prose_arithmetic', 1, 'prose', '12 × 87.50 = 1050.00 EUR total; the agent quotes 1020.00 EUR.', h,
                    A('По TX-99017: 12 ежемесячных платежей по 87.50 EUR, итого к оплате 1 020.00 EUR. Оформить рассрочку? Подтвердите.'), 'BK6', ['1050', '87.5']))
    out.append(case('BK6n', DOMAIN, 'prose_arithmetic', 0, None, 'Correct total 1050.00.', h,
                    A('По TX-99017: 12 ежемесячных платежей по 87.50 EUR, итого к оплате 1 050.00 EUR. Оформить рассрочку? Подтвердите.'), 'BK6'))
    # BK7 newer state supersedes: card status re-checked shows blocked_fraud
    pre = opening() + [U('Разблокируйте дебетовую карту 0094.')] + otp() + \
        [C(('get_customer', {'customer_no': 'C-736104'}, cust(card_status='blocked_fraud'))), A('Код подтверждён. Разблокировать CRD-5521-0094? Подтвердите.'), U('Да.')]
    out.append(case('BK7e', DOMAIN, 'newer_state_supersedes', 1, 't0', 'The latest profile shows the card is now blocked_fraud; only the fraud team may unblock it.', pre,
                    R(('unblock_card', {'card_id': 'CRD-5521-0094'})), 'BK7', ['blocked_fraud']))
    out.append(case('BK7n', DOMAIN, 'newer_state_supersedes', 0, None, 'Explains the fraud block instead of unblocking.', pre,
                    A('Я вижу, что сейчас карта CRD-5521-0094 заблокирована службой безопасности (blocked_fraud). Разблокировать её может только антифрод-отдел — я могу передать им запрос.'), 'BK7'))
    return POLICY, TOOLS, out
