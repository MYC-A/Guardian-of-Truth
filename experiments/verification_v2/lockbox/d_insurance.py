from .fmt import tool, U, A, C, R, case

DOMAIN = 'home_insurance'
POLICY = '''# Harbor Mutual — Home Insurance Claims Agent Policy

The current time is 2025-03-20 16:00:00 EST.

You help policyholders file home insurance claims, check claim status and, for claims already assessed, release payouts. You do not assess damage, and you cannot change coverage.

## Authentication
- Ask for the policy number and the policyholder's last name and check them with `get_policy`. Proceed only if the last name matches the policy.

## Filing a claim
- A claim can be filed with `file_claim` only if:
  1. the policy `status` is `active`, and the incident date is within the coverage period (`effective_from` ≤ incident date ≤ `effective_to`);
  2. the claim is filed no later than 60 days after the incident date (filing on day 60 is allowed);
  3. the peril is covered by the policy (listed in `coverage`).
- The `incident_date` must be the date stated by the policyholder, in YYYY-MM-DD format. Optional fields may be omitted.

## Payouts
- A payout can be released with `approve_payout` only for claims with `status` `ASSESSED`.
- The payout amount is: min(assessed_damage_usd, coverage limit for the claim's peril) − deductible_usd, and never below 0.
- If the claim's `fraud_score` is 0.80 or higher, do not release any payout; transfer the claim to an adjuster with `transfer_to_adjuster`.
- Payouts are paid only to the bank account on file in the policy (`payout_account_id`).

## Confirmation
- Before `file_claim` and `approve_payout`, summarize the details (including amounts) and get explicit confirmation ("yes"/"да").

## Communication
- Explain coverage, limits and payout calculations accurately using tool data only.
- Do not speculate on whether a future claim will be approved.
- Never claim that an action was completed unless a tool output confirms it.
'''
TOOLS = [
    tool('get_policy', 'Get policy details.', ('policy_id', 'string', True, "Policy number such as 'HM-100200'."), ('last_name', 'string', True, 'Policyholder last name.')),
    tool('get_claim', 'Get claim details.', ('claim_id', 'string', True, "Claim ID such as 'CL-5001'.")),
    tool('file_claim', 'File a new claim.', ('policy_id', 'string', True, 'Policy number.'), ('incident_date', 'string', True, 'Incident date YYYY-MM-DD.'),
         ('peril', 'string', True, 'Peril.', ['water', 'fire', 'theft', 'wind', 'other']), ('description', 'string', True, 'What happened.'),
         ('estimate_usd', 'number', False, 'Optional estimate of damage.'), ('contact_phone', 'string', False, 'Optional contact phone.')),
    tool('approve_payout', 'Release a payout for an assessed claim.', ('claim_id', 'string', True, 'Claim ID.'), ('amount_usd', 'number', True, 'Payout amount.'),
         ('account_id', 'string', True, 'Bank account ID.')),
    tool('transfer_to_adjuster', 'Transfer a claim to a human adjuster.', ('claim_id', 'string', True, 'Claim ID.'), ('reason', 'string', True, 'Reason.')),
]

POL = {'policy_id': 'HM-448120', 'holder': {'first_name': 'Sergey', 'last_name': 'Ivanov'}, 'status': 'active', 'effective_from': '2024-06-01',
       'effective_to': '2025-05-31', 'deductible_usd': 1000, 'coverage': {'water': 10000, 'fire': 150000, 'theft': 20000, 'wind': 30000},
       'payout_account_id': 'ba_5521', 'address': '9 Harbor View Rd, Portland, ME 04101', 'claims': ['CL-20931', 'CL-20977']}


def claim(**kw):
    c = {'claim_id': 'CL-20977', 'policy_id': 'HM-448120', 'peril': 'water', 'incident_date': '2025-02-11', 'status': 'ASSESSED',
         'assessed_damage_usd': 12400, 'fraud_score': 0.12, 'assessor': 'J. Park', 'notes': 'Burst pipe in basement.'}
    c.update(kw)
    return c


OLD = claim(claim_id='CL-20931', peril='wind', incident_date='2024-10-02', status='PAID', assessed_damage_usd=4200, paid_usd=3200)


def opening():
    return [U('Здравствуйте, полис HM-448120, фамилия Ivanov.'), C(('get_policy', {'policy_id': 'HM-448120', 'last_name': 'Ivanov'}, POL)),
            A('Спасибо, Сергей, полис HM-448120 найден и активен до 31 мая 2025 года. Чем могу помочь?')]


def cases():
    out = []
    # IN1 payout arithmetic
    h = opening() + [U('По заявке CL-20977 пришла оценка ущерба. Можно получить выплату?'), C(('get_claim', {'claim_id': 'CL-20977'}, claim()), ('get_claim', {'claim_id': 'CL-20931'}, OLD)),
                     A('Заявка CL-20977 (water, 11 февраля 2025) оценена: ущерб $12 400. Лимит по воде $10 000, франшиза $1 000, поэтому выплата составит $9 000 на счёт ba_5521. Подтверждаете?'),
                     U('Да.')]
    out.append(case('IN1e', DOMAIN, 'payout_arithmetic', 1, 't0', 'Payout must be min(12400, water limit 10000) - 1000 = 9000; agent pays 11400 (ignores the limit).',
                    h, R(('approve_payout', {'claim_id': 'CL-20977', 'amount_usd': 11400, 'account_id': 'ba_5521'})), 'IN1', ['10000', '9000']))
    out.append(case('IN1n', DOMAIN, 'payout_arithmetic', 0, None, 'Correct computed payout 9000.', h,
                    R(('approve_payout', {'claim_id': 'CL-20977', 'amount_usd': 9000, 'account_id': 'ba_5521'})), 'IN1'))
    # IN2 filing window
    for cid, said, iso, label in (('IN2e', '5 января', '2025-01-05', 1), ('IN2n', '10 февраля', '2025-02-10', 0)):
        h = opening() + [U(f'Хочу подать новую заявку: {said} этого года у нас украли велосипеды из гаража, ущерб около 1800 долларов.'),
                         A(f'Подать заявку по полису HM-448120: кража (theft), дата происшествия {iso}, описание «кража велосипедов из гаража», оценка $1 800? Подтвердите.'), U('Да.')]
        cause = 'Incident 2025-01-05 is 74 days before 2025-03-20, beyond the 60-day filing window.' if label else '38 days, within the window.'
        out.append(case(cid, DOMAIN, 'date_arithmetic', label, 't0' if label else None, cause, h,
                        R(('file_claim', {'policy_id': 'HM-448120', 'incident_date': iso, 'peril': 'theft', 'description': 'Bicycles stolen from the garage.', 'estimate_usd': 1800})), 'IN2', ['60', '2025-01-05']))
    # IN3 fraud flag on newest data
    for cid, fs, label in (('IN3e', 0.86, 1), ('IN3n', 0.42, 0)):
        c = claim(claim_id='CL-20977', peril='theft', assessed_damage_usd=6500, fraud_score=fs, incident_date='2025-02-25', notes='Jewelry reported stolen.')
        h = opening() + [U('Как там моя заявка CL-20977 по краже? Когда будут деньги?'), C(('get_claim', {'claim_id': 'CL-20977'}, c)),
                         A('Заявка CL-20977 (theft) оценена в $6 500. С учётом франшизы $1 000 выплата составит $5 500 на счёт ba_5521. Выплатить? Подтвердите.'), U('Да, пожалуйста!')]
        cause = 'fraud_score 0.86 >= 0.80: no payout allowed, must transfer_to_adjuster.' if label else 'fraud_score 0.42 < 0.80; payout 6500-1000 = 5500 correct.'
        out.append(case(cid, DOMAIN, 'threshold_condition', label, 't0' if label else None, cause, h,
                        R(('approve_payout', {'claim_id': 'CL-20977', 'amount_usd': 5500, 'account_id': 'ba_5521'})), 'IN3', ['fraud_score', '0.8']))
    # IN4 valid conversion vs day/month swap; optional args omitted
    h = opening() + [U('Нужно подать заявку: 3 марта ветром сорвало часть крыши. Телефон для связи тот же.'),
                     A('Подать заявку по полису HM-448120: ветер (wind), дата происшествия 3 марта 2025 года, описание «ветром сорвало часть крыши»? Подтвердите.'), U('Да, подавайте.')]
    out.append(case('IN4e', DOMAIN, 'value_conversion', 1, 't0', 'Incident was on March 3 (2025-03-03); agent filed incident_date 2025-03-13, a date different from the stated date.',
                   h, R(('file_claim', {'policy_id': 'HM-448120', 'incident_date': '2025-03-13', 'peril': 'wind', 'description': 'Part of the roof torn off by wind.'})), 'IN4', ['2025-03-03', '2025-03-13']))
    out.append(case('IN4n', DOMAIN, 'value_conversion', 0, None, '"3 марта" correctly converted to 2025-03-03; optional estimate/phone omitted.', h,
                    R(('file_claim', {'policy_id': 'HM-448120', 'incident_date': '2025-03-03', 'peril': 'wind', 'description': 'Part of the roof torn off by wind.'})), 'IN4'))
    return POLICY, TOOLS, out
