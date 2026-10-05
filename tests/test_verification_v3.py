import datetime as dt

from guardian_truth.verification import confirm, derived as D, df
from guardian_truth.verification.common import quote_q2
from guardian_truth.verification.v3 import CLOSED, decide_v3

NOW = dt.date(2025, 2, 10)


def test_numbers():
    assert D.numbers('1 020.00 € и 1 050,00 руб, 1,050.00, €540') == [1020.0, 1050.0, 1050.0, 540.0]
    assert D.parse_number('€ 1 020,50') == 1020.5


def test_dates():
    got = [d.isoformat() for d, _ in D.dates('с 10 по 15 октября; 18 февраля 2025; 2025-03-01; 19.02 и 7 мая; February 21, 2025; 3 May', NOW)]
    assert got == ['2025-10-10', '2025-10-15', '2025-02-18', '2025-03-01', '2025-02-19', '2025-05-07', '2025-02-21', '2025-05-03']
    assert D.parse_date('14 апреля', NOW) == dt.date(2025, 4, 14)
    assert D.parse_date('12.50 €', NOW) is None


def test_weekdays_and_business_days():
    assert D.parse_weekday('в среду') == 2 and D.parse_weekday('Friday') == 4 and D.parse_weekday('вторник и пятница') is None
    assert D.next_business_day(dt.date(2025, 2, 14)) == dt.date(2025, 2, 17)      # Fri -> Mon
    assert D.add_business_days(dt.date(2025, 2, 13), 3) == dt.date(2025, 2, 18)


def test_arithmetic():
    assert D.arithmetic('rate * nights + fee', dict(rate=180, nights=5, fee=20)) == 920
    assert D.arithmetic('__import__("os")', {}) is None and D.arithmetic('a*b', dict(a=1)) is None


def test_affirmation():
    assert confirm.is_affirmation('Да, отменяйте.') and confirm.is_affirmation('Yes, please')
    assert not confirm.is_affirmation('Да... ой, нет, лучше Роман') and not confirm.is_affirmation('Спасибо.')


def test_compare():
    c = confirm.compare
    assert c('T-09', 'T-04') == 'MISMATCH' and c('T-04', 'T-04') == 'MATCH'
    assert c('Roman Belov', 'Maxim Belov') == 'MISMATCH' and c('economy', 'Economy class') == 'MATCH'
    assert c('Part of the roof torn off by wind', 'ветром сорвало часть крыши') == 'UNCOMPARABLE'
    assert c('2025-04-11T19:00', '2025-04-11T07:00') == 'MISMATCH' and c('2025-03-13', '3 марта 2025') == 'MISMATCH'
    assert c(540, '€540') == 'MATCH' and c(540, '€720') == 'MISMATCH'


def test_quote_q2():
    assert quote_q2('Спасибо.', ['Спасибо.']) and not quote_q2('Да', ['Да, но позже'])
    assert quote_q2('**when telling** the customer the date', ['x when telling the customer the date y'])


def test_closure_regex():
    assert CLOSED.search('The list of available tools is complete; never call a tool that is not on it.')
    assert CLOSED.search('Список инструментов является полным.')
    assert not CLOSED.search('Use the tools to help the user.')


def _packet(text, hist):
    return dict(current_targets=[dict(source_id='t0', kind='text', text=text)], history=hist, declarations=[],
                normative_sources=[dict(source_id='q1', text='The current time is 2025-02-18 09:00:00 EET.')])


def test_df_evaluate():
    p = _packet('Посылка дойдёт в пятницу, 21 февраля.', [])
    now = df.now_of(p)
    c = dict(target_id='t0', claim_quote='дойдёт в пятницу, 21 февраля', claimed_value='21 февраля', operation='NEXT_BUSINESS_DAY',
             expression='', operands=[dict(name='date', value='2025-02-18', source_id='q1', quote='The current time is 2025-02-18')])
    r = df.evaluate(c, p, now)
    assert r['status'] == 'MISMATCH' and r['computed'] == '2025-02-19'
    c2 = dict(c, claimed_value='пятницу', operation='WEEKDAY_OF', operands=[dict(name='date', value='21 февраля', source_id='t0', quote='21 февраля')])
    assert df.evaluate(c2, p, now)['status'] == 'MATCH'
    h = [dict(source_id='h3', role='user', kind='text', event=3, text='заезд 10 октября, выезд 15 октября')]
    p = _packet('Итого €720 (4 ночи, 10–15 октября).', h)
    c3 = dict(target_id='t0', claim_quote='4 ночи', claimed_value='4', operation='NIGHTS_BETWEEN', expression='',
              operands=[dict(name='start', value='2025-10-10', source_id='t0', quote='10'), dict(name='end', value='15 октября', source_id='t0', quote='15 октября')])
    assert df.evaluate(c3, p, now)['status'] == 'MISMATCH'          # move dates rebound to h3
    c4 = dict(c3, claim_quote='€720', claimed_value='720', operation='ARITHMETIC', expression='rate*n',
              operands=[dict(name='rate', value='180', source_id='h3', quote='10 октября'), dict(name='n', value='4', source_id='t0', quote='4 ночи')])
    assert df.evaluate(c4, p, now)['status'] == 'UNVERIFIED'


def test_decide_v3_projection():
    rec = dict(A=dict(guard_error=False, reasons=[]), A_adm2=dict(decision='NO_ERROR'), G_closed=dict(error=False),
               DF=dict(candidate=dict(target_id='t0', requirement='r', reason='x', code_proven=True), verify=dict(verdict='UNRESOLVED')))
    d = decide_v3(rec)
    assert d['V3'][0] == 0 and d['V3m'][0] == 1 and d['+DF_raw'][0] == 1 and d['A_adm2'][0] == 0
