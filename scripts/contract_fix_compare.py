"""Compare complete paired replay receipts without changing historical scores."""
import argparse
import json
from pathlib import Path


def compare(before, after):
    def indexed(items, key):
        result = {key(item): item for item in items}
        if len(result) != len(items):
            raise ValueError('DUPLICATE_RECEIPT_ID')
        return result
    key = lambda item: (item['set'], item['rep'], item['arm'])
    old = indexed(before['phases'], key)
    new = indexed(after['phases'], key)
    if old.keys() != new.keys():
        raise ValueError('PHASE_SET_MISMATCH')
    reports, unavailable = [], []
    for identity in old:
        a, b = old[identity], new[identity]
        if a['status'] != b['status']:
            raise ValueError('PHASE_STATUS_MISMATCH')
        if b['status'] != 'REPLAYED':
            unavailable.append(dict(set=identity[0], rep=identity[1], arm=identity[2], status=b['status']))
            continue
        for field in ('expected_ids', 'source_sha256', 'input_sha256', 'gold_sha256'):
            if a[field] != b[field]:
                raise ValueError('PAIRED_IDENTITY_MISMATCH:' + field)
        aa = indexed(a['rows'], lambda row: row['id'])
        bb = indexed(b['rows'], lambda row: row['id'])
        if aa.keys() != bb.keys() or set(aa) != set(a['expected_ids']):
            raise ValueError('ROW_SET_MISMATCH')
        flips, reasons, missing, historical = [], [], [], []
        for identifier, row in bb.items():
            previous = aa[identifier]
            if previous['gold'] != row['gold']:
                raise ValueError('GOLD_DRIFT')
            if row['binary'] != previous['binary']:
                flips.append(dict(id=identifier, gold=row['gold'], before=previous['binary'], after=row['binary']))
            if row['accusation'] != previous['accusation']:
                reasons.append(dict(id=identifier, before=previous['accusation'], after=row['accusation']))
            if row['missing'] or previous['missing']:
                missing.append(dict(id=identifier, before=previous['missing'], after=row['missing']))
            if previous['binary'] != previous['source_binary'] or previous['accusation'] != previous['source_accusation']:
                historical.append(identifier)
        reports.append(dict(set=identity[0], rep=identity[1], arm=identity[2], rows=len(bb),
                            before=a['metrics'], after=b['metrics'], binary_flips=flips,
                            reason_changes=reasons, missing=missing, baseline_vs_original_saved=historical))
    return dict(phases=len(reports), row_projections=sum(r['rows'] for r in reports),
                binary_flips=sum(len(r['binary_flips']) for r in reports),
                reason_changes=sum(len(r['reason_changes']) for r in reports),
                missing=sum(len(r['missing']) for r in reports),
                baseline_vs_original_saved=sum(len(r['baseline_vs_original_saved']) for r in reports),
                unavailable=unavailable, phases_detail=reports)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--before', required=True, type=Path)
    parser.add_argument('--after', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = compare(json.loads(args.before.read_text(encoding='utf-8')), json.loads(args.after.read_text(encoding='utf-8')))
    with args.output.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'phases_detail'}))
