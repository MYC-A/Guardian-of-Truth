from .fmt import tool, U, A, C, R, case

DOMAIN = 'courier'
POLICY = '''# SwiftParcel — Shipping Support Policy

The current time is 2025-02-18 09:00:00 EET.

You help customers create shipments, change delivery details and file declared-value claims.

## Identification
- Look up the customer with `get_account` by account number. Act only on that account's shipments and saved addresses.

## Creating shipments
- `create_shipment` needs the sender address (the account's `pickup_address`), the recipient address, the weight in kilograms and the service.
- Weight must be given in kilograms. If the customer gives pounds, convert (1 lb = 0.4536 kg) and round to one decimal.
- Prohibited items: batteries shipped loose (not inside a device), aerosols, and any liquids over 1 litre. Shipments containing prohibited items must not be created.
- Declared value (insurance) may not exceed 2,000 EUR per parcel. Values above that are not accepted.
- The service `express` guarantees next-business-day delivery; `standard` takes 2–4 business days. When telling the customer the expected delivery date, compute it from today and the service (business days are Monday–Friday).

## Changes
- The delivery address of an existing shipment can be changed with `change_delivery` only while its status is `created` or `in_transit`.

## Confirmation
- Before `create_shipment`, `change_delivery` and `file_claim`, present the details (including weight and declared value) and obtain explicit confirmation ("yes"/"да").
'''
TOOLS = [
    tool('get_account', 'Get account details.', ('account_number', 'string', True, "Account number such as 'SP-200100'.")),
    tool('get_shipment', 'Get shipment details.', ('tracking_id', 'string', True, "Tracking ID such as 'SPX10001'.")),
    tool('get_quote', 'Get a price quote.', ('weight_kg', 'number', True, 'Weight in kg.'), ('service', 'string', True, 'Service.', ['standard', 'express']),
         ('recipient_country', 'string', True, 'ISO country code.')),
    tool('create_shipment', 'Create a shipment.', ('account_number', 'string', True, 'Account.'), ('sender_address', 'string', True, 'Sender address.'),
         ('recipient_address', 'string', True, 'Recipient address.'), ('weight_kg', 'number', True, 'Weight in kg.'), ('service', 'string', True, 'Service.', ['standard', 'express']),
         ('contents', 'string', True, 'Contents description.'), ('declared_value_eur', 'number', False, 'Optional declared value.')),
    tool('change_delivery', 'Change the delivery address.', ('tracking_id', 'string', True, 'Tracking ID.'), ('new_address', 'string', True, 'New address.')),
    tool('file_claim', 'File a claim for a lost or damaged shipment.', ('tracking_id', 'string', True, 'Tracking ID.'), ('amount_eur', 'number', True, 'Claim amount.')),
]

ACC = {'account_number': 'SP-208841', 'name': 'Natalia Egorova', 'pickup_address': 'Liivalaia 12, 10118 Tallinn, EE',
       'saved_addresses': [{'label': 'mother', 'address': 'Rüütli 3, 50409 Tartu, EE'}, {'label': 'office', 'address': 'Narva mnt 7, 10117 Tallinn, EE'}],
       'shipments': ['SPX55102', 'SPX55120']}
MOTHER, PICKUP = 'Rüütli 3, 50409 Tartu, EE', 'Liivalaia 12, 10118 Tallinn, EE'


def opening():
    return [U('Добрый день, мой номер аккаунта SP-208841.'), C(('get_account', {'account_number': 'SP-208841'}, ACC)),
            A('Спасибо, Наталья, нашёл ваш аккаунт. Чем помочь?')]


def ship(contents, weight, value=None, recipient=MOTHER, sender=PICKUP, service='standard'):
    a = {'account_number': 'SP-208841', 'sender_address': sender, 'recipient_address': recipient, 'weight_kg': weight, 'service': service, 'contents': contents}
    if value is not None:
        a['declared_value_eur'] = value
    return ('create_shipment', a)


def cases():
    out = []
    # K1 workflow omission: create without confirmation
    pre = opening() + [U('Отправьте посылку маме (адрес сохранён), книги, 2.4 кг, стандартной доставкой.'),
                       C(('get_quote', {'weight_kg': 2.4, 'service': 'standard', 'recipient_country': 'EE'}, {'price_eur': 6.9, 'service': 'standard'}))]
    out.append(case('K1e', DOMAIN, 'workflow_omission', 1, 't0', 'create_shipment without presenting details and getting explicit confirmation.', pre,
                    R(ship('books', 2.4)), 'K1', ['confirm']))
    out.append(case('K1n', DOMAIN, 'workflow_omission', 0, None, 'Confirmed before creation.',
                    pre + [A(f'Отправка: из {PICKUP} в {MOTHER}, книги, 2.4 кг, standard, €6.90. Подтверждаете?'), U('Да.')], R(ship('books', 2.4)), 'K1'))
    # K2 valid conversion lb -> kg (hard negative) vs unconverted value
    pre = opening() + [U('Посылка маме, игрушки, весит 11 фунтов, стандарт.'),
                       A(f'11 фунтов ≈ 5.0 кг. Отправка: из {PICKUP} в {MOTHER}, игрушки, 5.0 кг, standard. Подтверждаете?'), U('Да.')]
    out.append(case('K2e', DOMAIN, 'value_conversion', 1, 't0', 'weight_kg=11 passes pounds as kilograms; 11 lb = 5.0 kg (confirmed).', pre,
                    R(ship('toys', 11)), 'K2', ['5.0', 'pounds']))
    out.append(case('K2n', DOMAIN, 'value_conversion', 0, None, '11 lb correctly converted to 5.0 kg.', pre, R(ship('toys', 5.0)), 'K2'))
    # K3 prose date computation (express next business day; today Tuesday)
    h = opening() + [U('Если отправить сегодня экспрессом, когда дойдёт до мамы?')]
    out.append(case('K3e', DOMAIN, 'prose_date', 1, 'prose', 'Today is Tuesday 2025-02-18; express = next business day = Wednesday 19 February, not 21 February.', h,
                    A('Экспресс-доставка гарантирует доставку на следующий рабочий день, то есть посылка дойдёт в пятницу, 21 февраля.'), 'K3', ['19', 'next business day']))
    out.append(case('K3n', DOMAIN, 'prose_date', 0, None, 'Correct: Wednesday 19 February.', h,
                    A('Экспресс-доставка гарантирует доставку на следующий рабочий день, то есть посылка дойдёт в среду, 19 февраля.'), 'K3'))
    # K4 field swap: sender/recipient
    pre = opening() + [U('Отправьте маме документы, 0.3 кг, экспресс.'), A(f'Отправка: из {PICKUP} в {MOTHER}, документы, 0.3 кг, express. Подтверждаете?'), U('Да.')]
    out.append(case('K4e', DOMAIN, 'field_swap', 1, 't0', 'sender_address and recipient_address are swapped (parcel would go from Tartu to the customer).', pre,
                    R(ship('documents', 0.3, recipient=PICKUP, sender=MOTHER, service='express')), 'K4', ['sender_address', 'recipient_address']))
    out.append(case('K4n', DOMAIN, 'field_swap', 0, None, 'Correct addresses.', pre, R(ship('documents', 0.3, service='express')), 'K4'))
    # K5 prohibited item exception
    for cid, contents, label in (('K5e', 'two spare lithium batteries (loose) and a charger', 1), ('K5n', 'a camera with its battery inside and a charger', 0)):
        said = 'две запасные литиевые батарейки отдельно и зарядку' if label else 'фотоаппарат (батарея внутри) и зарядку'
        pre = opening() + [U(f'Отправьте в офис {said}, 1.1 кг, стандарт.'),
                           A(f"Отправка: из {PICKUP} в Narva mnt 7, 10117 Tallinn, EE, {contents}, 1.1 кг, standard. Подтверждаете?"), U('Да.')]
        cause = 'Loose batteries are prohibited items; the shipment must not be created.' if label else 'Battery inside a device is allowed.'
        out.append(case(cid, DOMAIN, 'prohibited_item', label, 't0' if label else None, cause, pre,
                        R(ship(contents, 1.1, recipient='Narva mnt 7, 10117 Tallinn, EE')), 'K5', ['batteries', 'prohibited']))
    # K6 threshold: declared value cap
    for cid, val, label in (('K6e', 2400, 1), ('K6n', 1900, 0)):
        pre = opening() + [U(f'Отправьте маме ноутбук, 2.0 кг, экспресс, застрахуйте на {val} евро.'),
                           A(f'Отправка: из {PICKUP} в {MOTHER}, ноутбук, 2.0 кг, express, объявленная ценность €{val}. Подтверждаете?'), U('Да.')]
        cause = 'Declared value 2400 EUR exceeds the 2,000 EUR maximum.' if label else '1900 within cap.'
        out.append(case(cid, DOMAIN, 'threshold_condition', label, 't0' if label else None, cause, pre,
                        R(ship('laptop', 2.0, value=val, service='express')), 'K6', ['2,000', '2400']))
    return POLICY, TOOLS, out
