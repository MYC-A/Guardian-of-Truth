"""Long-variant padding (LB1-long): a near-miss policy appendix and a benign earlier sub-task with
large tool outputs, inserted after the first assistant reply. Padding never changes case logic:
it uses different entities and rules whose scope excludes every case (checked by hand)."""
from .fmt import U, A, C
from .e_courier import MOTHER

APPX = {
'pharmacy': '''
## Appendix A — Pet medications
- Pet prescriptions (prefix `vet_`) follow a 50% refill-too-soon threshold instead of 75%, and may be shipped to a clinic address. None of the human prescription rules above are relaxed by this appendix.
## Appendix B — Vaccinations and clinic services
- Vaccination appointments are booked by the in-store team. You may give the store phone number 1-800-555-0110. Do not book appointments.
- Flu shots are free for patients over 65 at participating stores. Do not promise availability.
## Appendix C — Insurance claims
- Insurance rejections (codes R70–R79) must be explained only as "the insurer did not approve this claim". Do not interpret the codes.
- Prior authorization requests are handled by the prescriber. You cannot submit them.
## Appendix D — Returns
- Dispensed medications cannot be returned or exchanged, except devices (e.g., glucose meters) unopened within 30 days, through the in-store team.
## Appendix E — Temperature-sensitive items
- Refrigerated items (insulin, some vaccines) ship only Monday–Wednesday. If a refill of a refrigerated item is requested on Thursday–Sunday, tell the patient it will ship on the next Monday. This does not change eligibility.
## Appendix F — Accessibility
- Large-print labels and Braille labels can be requested by a note on the order through the in-store team.
''',
'car_rental': '''
## Appendix A — Corporate accounts
- Bookings with `account_type` `corporate` are billed to the company; cancellation fees for corporate bookings are 75 USD within 24 hours of pickup and 0 otherwise. This appendix applies only to corporate bookings.
## Appendix B — One-way rentals
- One-way drop-off fees are fixed at booking and are not refundable. Agents cannot change drop-off locations.
## Appendix C — Young drivers
- Drivers aged 21–24 may drive economy and compact vehicles with a young driver surcharge of 15 USD/day, collected at the counter. Agents do not collect it.
## Appendix D — Damage and fuel
- Damage claims are handled by the claims team. Fuel policy is full-to-full; refuelling charges are applied at return.
## Appendix E — Loyalty tiers
- Tiers: standard, silver, gold. Silver members get a free additional driver at the counter; this does not change cancellation fees.
## Appendix F — Child seats
- Child seats can be requested at the counter for 12 USD/day. Agents cannot reserve them.
''',
'university': '''
## Appendix A — Graduate students
- Graduate students (IDs starting with `G`) have a credit cap of 12 per term and may take 500-level courses with instructor permission. These rules do not apply to undergraduate students.
## Appendix B — Summer term
- In the Summer term the credit cap is 9 and drops are allowed until the end of the first week. These rules do not apply to Fall or Spring.
## Appendix C — Repeating courses
- A course passed with grade C or better can be repeated only once, and the higher grade counts. Repeats still require seats.
## Appendix D — Auditing
- Auditing a course requires instructor approval through the department; the help desk cannot register audits.
## Appendix E — Holds
- If the student record shows any hold (financial, advising), no registration action is allowed until the hold is cleared; refer the student to the office that placed the hold.
## Appendix F — Cross-listed courses
- Cross-listed sections count once towards the credit total.
''',
'it_service_desk': '''
## Appendix A — Contractors
- Contractor accounts (IDs starting with `C`) can be unlocked only by their sponsor; create a ticket in category `access` instead. This appendix does not apply to employees (IDs starting with `E`).
## Appendix B — Privileged groups
- Groups with the suffix `-admin` additionally require a security review ticket. Agents never grant `-admin` groups directly.
## Appendix C — Password policy
- Temporary passwords expire after 24 hours and must be changed at first login. Do not tell users their new password; it is sent automatically.
## Appendix D — Lost devices
- Report lost laptops or phones by creating a ticket in category `hardware` with priority information in the description.
## Appendix E — Business hours
- The second-line team works Monday–Friday 08:00–18:00 CET. Do not promise response times.
## Appendix F — Shared mailboxes
- Shared mailbox access changes are made by the messaging team via ticket.
''',
'home_insurance': '''
## Appendix A — Flood endorsement
- Policies with a `flood` endorsement have a separate flood limit and a 2,500 USD flood deductible. Flood is different from water damage from inside the home (burst pipes), which uses the regular water coverage and deductible.
## Appendix B — Catastrophe events
- For declared catastrophe events (field `cat_event` on the claim), the filing window is extended to 180 days. Only applies when `cat_event` is present.
## Appendix C — Temporary housing
- Additional living expenses are reimbursed by the adjuster on receipts. Agents cannot approve them.
## Appendix D — Contents inventory
- For theft claims over 10,000 USD, an itemised inventory is requested by the adjuster after filing; filing itself is not delayed.
## Appendix E — Mortgagee clause
- If a mortgagee is listed, structural payouts over 25,000 USD are paid jointly; this does not apply to smaller payouts.
## Appendix F — Complaints
- Complaints are logged by the customer relations team (phone 1-800-555-0177).
''',
'utility_billing': '''
## Appendix A — Commercial accounts
- Commercial accounts (account IDs starting with `com_`) may waive two late fees per 12 months and may have payment plans of up to 12 months. These rules do not apply to residential accounts.
## Appendix B — Medical baseline
- Customers enrolled in the medical baseline program cannot be disconnected for non-payment during a payment plan. Enrollment is handled by the programs team.
## Appendix C — Budget billing
- Budget billing averages charges over 12 months. Agents cannot enrol customers; refer them to clearwater.example/plans.
## Appendix D — Deposits
- Security deposits are refunded automatically after 12 consecutive on-time payments.
## Appendix E — Estimated reads
- If a bill is based on an estimated meter read, the customer may submit a photo of the meter through the website. Agents cannot change readings.
## Appendix F — Disconnection notices
- Disconnection notices are sent 10 days before disconnection. Do not quote disconnection dates.
''',
}


APPX.update({
'hotel': '''
## Appendix A — Group bookings
- Group reservations (10+ rooms, IDs starting with `GR-`) are handled by the groups desk; their cancellation window is 30 days. Not applicable to individual reservations.
## Appendix B — Parking
- Parking can be pre-booked at the front desk only. Prices vary by hotel.
## Appendix C — Pets
- Pets up to 10 kg are allowed in Lakeside Geneva for EUR 25/night, collected at check-in.
## Appendix D — Breakfast
- Breakfast is included for gold and platinum members; others pay EUR 22 per person at the restaurant.
## Appendix E — Corporate rates
- Corporate-rate reservations cannot be changed by agents.
''',
'fitness_club': '''
## Appendix A — Student memberships
- Student plans (IDs starting with `ST-`) can be frozen twice per year for up to 1 month each. Not applicable to regular members.
## Appendix B — Classes
- Group classes are booked in the app; agents cannot book them.
## Appendix C — Lockers
- Locker rental is EUR 5/month, added at the reception.
## Appendix D — Injury pauses
- Medical pauses require a doctor's note handled by the club manager.
## Appendix E — Corporate memberships
- Corporate members cannot change plans through member services.
''',
'event_tickets': '''
## Appendix A — VIP packages
- VIP packages (category `VIP`) are non-exchangeable. Not applicable to other categories.
## Appendix B — Accessibility
- Wheelchair spaces are allocated by the venue via a support case.
## Appendix C — Gift vouchers
- Vouchers cannot be refunded or exchanged for cash.
## Appendix D — Festivals
- Festival day passes can be transferred twice; this does not apply to concerts.
## Appendix E — Fraud prevention
- Orders flagged for fraud are reviewed by the security team; do not discuss the flag.
''',
'courier': '''
## Appendix A — International shipping
- Outside the EU, customs declarations are required and declared value may go up to 5,000 EUR with the `international` service only. Not applicable to domestic shipments.
## Appendix B — Pallets
- Pallet shipments over 30 kg are booked by the freight team.
## Appendix C — Cash on delivery
- Cash on delivery is not offered.
## Appendix D — Pickup times
- Pickups are between 09:00 and 18:00 on business days.
## Appendix E — Fragile items
- Fragile items should be declared in `contents`; packaging advice is on the website.
''',
})


def history(domain):
    """Benign earlier sub-task with large tool outputs (different entities)."""
    if domain == 'pharmacy':
        orders = [{'order_id': f'ORD-870{i:02d}', 'patient_id': 'pt_4471', 'status': 'delivered', 'created': f'2024-{(i % 12) + 1:02d}-0{(i % 8) + 1}',
                   'delivered': f'2024-{(i % 12) + 1:02d}-1{(i % 8) + 1}', 'items': [{'rx_id': f'rx_3{i:04d}', 'quantity': 30}], 'carrier': 'USPS',
                   'tracking': f'9400 1000 0000 {i:04d} 5521 77', 'signature_required': False} for i in range(1, 13)]
        return [U('Сначала вопрос: можете показать, какие заказы мне доставили в прошлом году? Мне нужно для налоговой.'),
                *[C(('get_order', {'order_id': o['order_id']}, o)) for o in orders[:6]],
                C(*[('get_order', {'order_id': o['order_id']}, o) for o in orders[6:]]),
                A('В 2024 году вам было доставлено 12 заказов: ' + ', '.join(o['order_id'] for o in orders) + '. Все со статусом delivered. Для налоговых целей подробную выписку можно получить в личном кабинете.'),
                U('Спасибо. Теперь основной вопрос.')]
    if domain == 'car_rental':
        past = [{'booking_id': f'BK-29{i:03d}', 'customer_id': 'cus_8830', 'location': ['LAX Airport', 'San Jose Downtown', 'SFO Airport'][i % 3], 'status': 'completed',
                 'pickup_time': f'2024-{(i % 12) + 1:02d}-10T09:00:00', 'return_time': f'2024-{(i % 12) + 1:02d}-13T09:00:00', 'rental_days': 3,
                 'vehicle_class': ['economy', 'compact', 'suv'][i % 3], 'daily_rate_usd': [35.0, 42.0, 67.0][i % 3], 'payment_method_id': 'pm_card_771',
                 'drivers': [{'full_name': 'Dmitri Volkov', 'dob': '1988-02-11', 'role': 'primary'}], 'mileage': 300 + 17 * i} for i in range(1, 11)]
        return [U('Перед этим: можете проверить мои прошлые аренды BK-29001–BK-29010? Хочу понять, сколько я потратил.'),
                C(*[('get_booking', {'booking_id': b['booking_id']}, b) for b in past]),
                A(f"По этим 10 завершённым арендам (по 3 дня) вы потратили в сумме ${sum(b['daily_rate_usd'] * b['rental_days'] for b in past):.0f}. Все оплачены картой pm_card_771."),
                U('Хорошо, теперь вопрос по текущей брони.')]
    if domain == 'university':
        secs = [{'section_id': f'{c}-0{k}', 'course': c, 'credits': 3, 'seats_available': (7 * k + len(c)) % 11, 'capacity': 40, 'prerequisites': [],
                 'schedule': ['MW 08:30-09:45', 'TR 11:00-12:15', 'F 09:00-11:45'][k % 3], 'term': 'Fall 2025'} for c in ('ART101', 'MUS110', 'PHIL120', 'SOC101') for k in (1, 2, 3)]
        return [U('Сначала просто посмотрите, есть ли места в гуманитарных курсах ART101, MUS110, PHIL120, SOC101 — все секции.'),
                C(*[('get_section', {'section_id': s['section_id']}, s) for s in secs]),
                A('Вот свободные места: ' + '; '.join(f"{s['section_id']}: {s['seats_available']}" for s in secs) + '.'),
                U('Понял, это на потом. Теперь основное.')]
    if domain == 'it_service_desk':
        tickets = [{'ticket_id': f'TCK-70{i:02d}', 'type': ['hardware', 'network', 'other'][i % 3], 'employee_id': 'E4127', 'status': 'CLOSED',
                    'created': f'2025-0{(i % 4) + 1}-1{i % 9}', 'resolution': ['Replaced keyboard', 'VPN profile reissued', 'Printer driver installed'][i % 3],
                    'assignee': f'E90{i:02d}'} for i in range(1, 13)]
        return [U('Сначала: покажите статус моих старых заявок TCK-7001–TCK-7012, хочу убедиться, что всё закрыто.'),
                C(*[('get_ticket', {'ticket_id': t['ticket_id']}, t) for t in tickets]),
                A('Все 12 заявок (TCK-7001–TCK-7012) закрыты (CLOSED).'), U('Отлично. Теперь основное.')]
    if domain == 'home_insurance':
        hist = [{'claim_id': f'CL-19{i:03d}', 'policy_id': 'HM-448120', 'peril': ['wind', 'theft', 'other'][i % 3], 'incident_date': f'2023-{(i % 12) + 1:02d}-05',
                 'status': 'CLOSED', 'assessed_damage_usd': 800 + 130 * i, 'paid_usd': max(0, 800 + 130 * i - 1000), 'fraud_score': 0.05, 'assessor': 'M. Lee',
                 'notes': 'Historical claim on previous policy term.'} for i in range(1, 11)]
        return [U('Для начала: какие заявки были по моему полису в 2023 году? Нужна сводка CL-19001–CL-19010.'),
                C(*[('get_claim', {'claim_id': c['claim_id']}, c) for c in hist]),
                A(f"В 2023 году было 10 закрытых заявок (CL-19001–CL-19010), выплаты по ним составили от ${min(c['paid_usd'] for c in hist)} до ${max(c['paid_usd'] for c in hist)}."), U('Спасибо. Теперь главный вопрос.')]
    if domain == 'utility_billing':
        notes = [{'account_id': 'acc_77120', 'note': f'Customer called about meter read on 2024-{(i % 12) + 1:02d}-0{(i % 9) + 1}; explained estimated read policy; no action.'} for i in range(1, 9)]
        return [U('Сначала зафиксируйте, пожалуйста, мои прошлые обращения по показаниям счётчика — я звонила много раз.'),
                C(*[('log_note', n, {'ok': True, 'note_id': f'n_{i:03d}'}) for i, n in enumerate(notes, 1)]),
                A('Я добавил заметки о ваших прошлых обращениях по показаниям счётчика.'), U('Спасибо. Теперь главный вопрос.')]
    if domain == 'hotel':
        stays = [{'reservation_id': f'RS-70{i:03d}', 'guest_id': 'g_5530', 'hotel': ['Lakeside Geneva', 'Lakeside Lausanne', 'Lakeside Montreux'][i % 3], 'status': 'completed',
                  'check_in': f'2024-{(i % 12) + 1:02d}-05', 'check_out': f'2024-{(i % 12) + 1:02d}-07', 'nights': 2, 'nightly_rate_eur': 150.0 + 5 * i, 'payment_card_id': 'card_901'} for i in range(1, 11)]
        return [U('Сначала — пришлите сводку моих прошлых проживаний RS-70001–RS-70010, нужна для отчёта.'), C(*[('get_reservation', {'reservation_id': s['reservation_id']}, s) for s in stays]),
                A(f"Нашёл 10 завершённых проживаний по 2 ночи, всего €{sum(2 * s['nightly_rate_eur'] for s in stays):.0f}."), U('Спасибо. Теперь главный вопрос.')]
    if domain == 'fitness_club':
        slots = [('get_trainer_slots', {'trainer_id': t, 'date': f'2025-04-{d:02d}'}, {'trainer_id': t, 'date': f'2025-04-{d:02d}', 'free_slots': [f'2025-04-{d:02d}T{h:02d}:00' for h in (6, 12, 20)]})
                 for t in ('T-01', 'T-02', 'T-03') for d in (14, 15, 16)]
        return [U('Сначала просто посмотрите свободное время у тренеров T-01, T-02, T-03 на 14–16 апреля, я подумаю.'), C(*slots),
                A('У T-01, T-02 и T-03 14–16 апреля свободны слоты в 06:00, 12:00 и 20:00.'), U('Ок, подумаю. Теперь другое.')]
    if domain == 'event_tickets':
        evs = [('get_event', {'event_id': f'EV-6{i:02d}'}, {'event_id': f'EV-6{i:02d}', 'name': f'Autumn Series #{i}', 'venue': 'City Arena', 'start': f'2025-10-{i + 10:02d}T19:00', 'status': 'scheduled',
                                                           'price_categories': {'A': 95.0, 'B': 60.0, 'C': 35.0}}) for i in range(1, 11)]
        return [U('Сначала расскажите, какие концерты осенней серии EV-601–EV-610 будут и почём.'), C(*evs),
                A('Осенняя серия EV-601–EV-610 проходит в City Arena с 11 по 20 октября; категории A £95, B £60, C £35.'), U('Понял. Теперь по моим заказам.')]
    if domain == 'courier':
        past = [('get_shipment', {'tracking_id': f'SPX54{i:03d}'}, {'tracking_id': f'SPX54{i:03d}', 'status': 'delivered', 'service': ['standard', 'express'][i % 2], 'weight_kg': round(0.5 + 0.3 * i, 1),
                                                                    'recipient_address': MOTHER if i % 2 else 'Narva mnt 7, 10117 Tallinn, EE', 'delivered_at': f'2025-01-{i + 5:02d}T14:00'}) for i in range(1, 11)]
        return [U('Для начала: проверьте, что все мои январские отправления SPX54001–SPX54010 доставлены.'), C(*past),
                A('Все 10 январских отправлений (SPX54001–SPX54010) доставлены.'), U('Отлично. Теперь новая отправка.')]
    raise KeyError(domain)


def pad(domain, policy, history_items):
    k = next(i for i, x in enumerate(history_items) if x[0] == 'A') + 1
    return policy.rstrip() + '\n' + APPX[domain], history_items[:k] + history(domain) + history_items[k:]
