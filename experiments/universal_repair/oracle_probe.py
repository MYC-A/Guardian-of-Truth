"""Oracle probe v2 (docs/universal_repair_v2/FUNNEL_V2.md): for adjudicated real holdout FNs, inject a HAND-AUTHORED correct
candidate (the right rule paragraph + the right fact events + a correct reason), i.e. perfect retrieval and binding, into the
UNCHANGED R_fix verifier (live, one call per row, separate cache). Also records whether the rule / facts were inside the
detector's 20k packet and whether proof5 can express the relation. Measures the verification stage only.
  python -X utf8 -m experiments.universal_repair.oracle_probe [--dry]"""
import argparse, json
from guardian_truth.integrated import Transport
from guardian_truth.repair.clients import ReadThrough
from guardian_truth.repair.v5 import ARMS, verify
from guardian_truth.verification.pipeline import packet_for
from .run import OUT, MODEL, inputs, paced

V2 = OUT.parent / 'universal_repair_v2'

# rule: substring of the policy paragraph; facts: substrings identifying history events; expressible: can proof5 state it?
CASES = {
 'hold_air_048': dict(rule='Otherwise, flight can be cancelled if any of the following is true', facts=['"reservation_id": "EHGLP3"'],
     reason='EHGLP3 is basic economy, booked 2024-05-04 (more than 24 hrs before now), no travel insurance, not cancelled by the airline, reason change of plans: none of the cancellation conditions holds, yet the move cancels it.',
     expressible='NO: disjunctive eligibility over 4 conditions; proof5 has one comparison per check and blocks certificates under if/unless guards'),
 'hold_air_029': dict(rule='Otherwise, flight can be cancelled if any of the following is true', facts=['"reservation_id": "OWZ4XL", "user_id"'],
     reason='OWZ4XL is basic economy, created 2024-05-09T13:43 (now 2024-05-15), insurance no, flights not cancelled by the airline: no cancellation condition holds, yet the move cancels it.',
     expressible='NO: same disjunctive eligibility'),
 'hold_tel_052': dict(rule='roaming', facts=['"line_id": "L1001", "phone_number"', '555-123-2002'],
     reason='The user said their line is 555-123-2002; line L1001 has phone number 555-123-2001, so enable_roaming is applied to a line that is not the user\'s.',
     expressible='PARTIAL: NE(phone of L1001, user-stated number) is expressible only if the user utterance is a leaf source and the join line->phone is given'),
 'hold_ret_026': dict(rule='The user must provide a payment method to pay or receive refund of the price difference', facts=['"payment_methods": {"paypal_2433177"'],
     reason='payment_method_id gift_card_0000000 is not one of the user\'s payment methods (the profile lists only paypal_2433177); it is the placeholder from the tool description.',
     expressible='NO: membership in the KEYS of a JSON object (payment_methods) is not a MEMBER_OF array leaf'),
 'hold_ret_023': dict(rule='each item can be modified to an available new item of the same product', facts=['"order_id": "#W1845024", "user_id"'],
     reason='modify_pending_order_items is called with new_item_ids [] to remove three items; item modification may only replace an item by a new option of the same product, it cannot remove items.',
     expressible='NO: structural argument constraint (non-empty, same product) has no operation'),
 'hold_ret_028': dict(rule='each item can be modified to an available new item of the same product', facts=['"order_id": "#W8367380", "user_id"'],
     reason='modify_pending_order_items with new_item_ids [] removes the fleece jacket; item modification can only swap to a new option of the same product.',
     expressible='NO: same as hold_ret_023'),
 'hold_air_021': dict(rule='If the user complains about delayed flights', facts=['get_flight_status: delayed', '"user_id": "ethan_martin_2396", "name"'],
     reason='The certificate is sent before any reservation/passenger facts are confirmed and before the user changes or cancels a reservation; the policy allows a delay certificate only after confirming the facts and changing or cancelling the reservation.',
     expressible='NO: procedural precondition (order of events)'),
}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--dry', action='store_true'); a = ap.parse_args()
    rows = {r['id']: r for r in inputs('hold_tau2h')}
    client = None
    if not a.dry:
        live = Transport('mistral', MODEL, V2 / 'cache' / 'oracle', max_calls=20, retry_failed=2, sender=paced)
        client = ReadThrough('mistral', MODEL, [], live=live)
    out = {}
    for i, c in CASES.items():
        row = rows[i]; rp = packet_for(row, 20000); full = packet_for(row, 120000)
        rule = [s for s in full['normative_sources'] if c['rule'].lower() in s['text'].lower()]
        in_pkt = any(c['rule'].lower() in s['text'].lower() for s in rp['normative_sources'])
        facts = [h for h in full['history'] if any(f in h['text'] for f in c['facts'])]
        facts_in_pkt = [any(f in h['text'] for h in rp['history']) for f in c['facts']]
        rec = dict(rule_found=bool(rule), rule_in_detector_packet=in_pkt, facts_found=len(facts), facts_in_detector_packet=facts_in_pkt,
                   expressible=c['expressible'])
        if rule and facts and client is not None:
            keep = ('source_id', 'role', 'kind', 'tool', 'text')
            para = rule[0]['text']; j = para.lower().find(c['rule'].lower())
            cand = dict(origin='ORACLE', target_id=rp['current_targets'][0]['source_id'], requirement=para[max(0, j - 200):j + 900],
                        reason=c['reason'], policy_source_ids=[s['source_id'] for s in rp['normative_sources'] if s['source_id'] == rule[0]['source_id']],
                        extra_policy=[] if in_pkt else [dict(source_id=rule[0]['source_id'], text=para)], evidence_source_ids=[])
            v = verify(client, rp, cand, MODEL, 0, 'verify_ORACLE', ARMS['R_fix'],
                       extra_evidence=[{k: h.get(k) for k in keep} for h in facts])
            rec.update(verification_status=v['verification_status'], raw_verdict=v.get('raw_verdict'), downgraded=v.get('downgraded'),
                       policy_quote_ok=v.get('policy_quote_ok'), evidence_quote_ok=v.get('evidence_quote_ok'), analysis=(v.get('analysis') or '')[:500])
        out[i] = rec
        print(i, {k: rec.get(k) for k in ('rule_in_detector_packet', 'facts_in_detector_packet', 'verification_status', 'raw_verdict', 'downgraded')})
    if not a.dry:
        (V2 / 'funnel').mkdir(parents=True, exist_ok=True)
        (V2 / 'funnel' / 'oracle_probe.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
