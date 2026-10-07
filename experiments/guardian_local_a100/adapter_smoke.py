"""Adapter smoke test for a local OpenAI-compatible endpoint (zero gold leakage into prompts).

Checks, in order:
  1. GET /v1/models lists the served model id.
  2. Guided JSON decoding works: one analysis-style request with the study's
     json_schema response_format parses and validates against the schema.
  3. End-to-end: one ERROR row and one CLEAN row from the dev diagnostics go
     through the unchanged run_v5 review with the local client; the review
     reply parses, receipts carry the local model identity (response_model ==
     model id), and both decision rules (R_fix and v6fix) are present.

Writes a receipt JSON (ids, timings, usage, verdicts) next to the run output.
No gold label ever enters any request; the gold of the two rows is recorded in
the receipt only for reporting.

Usage:
  python -m experiments.guardian_local_a100.adapter_smoke --backend vllm \
      --model-id '...' [--out outputs/guardian_local_a100/<backend>/<model>/smoke.json]
"""
import argparse
import json
import time
from pathlib import Path

from guardian_truth.integrated import Transport
from guardian_truth.repair.clients import ReadThrough
from guardian_truth.repair.v5 import ARMS, run_v5, decide as decide_v5
from guardian_truth.v6fix.pipeline import Layers, decide
from guardian_truth.parsing import decode_json
from guardian_truth.verification.common import schema_errors

from experiments.guardian_semantic.variants import BLIND_PROMPT, analysis_schema, _req, _parse
from experiments.guardian_addons.variants2 import Hook2

from .providers import register_local_providers, backend_endpoint
from .run_local import rows, model_dir, ROOT, OUTROOT

DEV = ROOT / 'outputs/guardian_semantic/data'


def gold_for(set_name):
    return json.loads((DEV / f'{set_name}_GOLD.json').read_text(encoding='utf-8'))


def http_get(url, timeout=30):
    import urllib.request
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--backend', required=True, choices=('vllm', 'llamacpp'))
    ap.add_argument('--model-id', required=True)
    ap.add_argument('--out')
    ap.add_argument('--review-max-tokens', type=int, default=None,
                    help='override review-call max_tokens (default 1700; reason-capable models: 8192)')
    ap.add_argument('--pre-max-tokens', type=int, default=None,
                    help='override guided-JSON pre-analysis max_tokens (default 1700)')
    ap.add_argument('--frules-max-tokens', type=int, default=None,
                    help='override F-extraction max_tokens (default 700)')
    a = ap.parse_args()
    provider = f'local-{a.backend}'
    register_local_providers()
    receipt = dict(backend=a.backend, provider=provider, model_id=a.model_id,
                   endpoint=backend_endpoint(provider), checks={})

    # 1. model listing
    t0 = time.time()
    models = http_get(backend_endpoint(provider).rsplit('/chat/completions', 1)[0] + '/models')
    ids = [m.get('id') for m in models.get('data', [])]
    receipt['checks']['models_listed'] = dict(ok=a.model_id in ids, ids=ids[:8], seconds=round(time.time() - t0, 2))

    # 2. guided JSON smoke on a small analysis packet
    dev_rows = rows('dev')
    gold = gold_for('dev')
    row_err = next(r for r in dev_rows if gold[r['id']]['label'] == 1)
    row_ok = next(r for r in dev_rows if gold[r['id']]['label'] == 0)
    client = ReadThrough(provider, a.model_id, [], live=Transport(provider, a.model_id,
                        OUTROOT / a.backend / model_dir(a.model_id) / 'cache' / 'smoke'))
    # neutral view of the error row (prompt only, current move hidden)
    from experiments.guardian_semantic.neutral import neutral_view
    user, view = neutral_view(row_err, 20000)
    receipt['checks']['neutral_view'] = dict(ok=user is not None, reason=(view or {}).get('reason'),
                                             sources=len(user.get('normative_sources') or []) if user else None)
    if user is None:
        print(json.dumps(receipt, ensure_ascii=False, indent=1))
        raise SystemExit('NEUTRAL_VIEW_FAILED')
    schema = analysis_schema(user)
    t0 = time.time()
    r = client.call(_req(a.model_id, BLIND_PROMPT, user, schema, 'pre_analysis_neutral_v2',
                         a.pre_max_tokens if a.pre_max_tokens is not None else 1700))
    v = _parse(r, schema)
    receipt['checks']['guided_json'] = dict(
        ok=v is not None,
        status=(r.get('transport') or {}).get('status'),
        finish_reason=r.get('finish_reason'),
        response_model=r.get('response_model'),
        schema_validation=r.get('schema_validation'),
        usage=r.get('usage'),
        seconds=round(time.time() - t0, 2))

    # 3. end-to-end review on the error row and the clean row (unchanged run_v5)
    layers = Layers(ReadThrough(provider, a.model_id, [], live=Transport(provider, a.model_id,
                    OUTROOT / a.backend / model_dir(a.model_id) / 'cache' / 'smoke')),
                    a.model_id, budget=20000, attempts=(0, 1),
                    frules_max_tokens=a.frules_max_tokens if a.frules_max_tokens is not None else 700)
    e2e = {}
    for tag, row in (('error_row', row_err), ('clean_row', row_ok)):
        t0 = time.time()
        hook = Hook2(client, None, a.model_id, original_row=row)
        rec = run_v5(row, hook, flags=ARMS['R_fix'], provider=provider, model=a.model_id, attempt=0,
                     review_max_tokens=a.review_max_tokens)
        d_rfix, _ = decide_v5(rec)
        lay = layers.findings(row)
        d = decide(rec, lay['findings'])
        # recursive search for the review step record (same traversal as the offline scorer's cost())
        found = []
        def _walk(o):
            if isinstance(o, dict):
                if o.get('tag') == 'review' and ('usage' in o or 'content' in o or 'raw_content' in o):
                    found.append(o)
                for v in o.values():
                    _walk(v)
            elif isinstance(o, list):
                for v in o:
                    _walk(v)
        _walk(rec)
        e2e[tag] = dict(id=row['id'], gold=gold[row['id']]['label'],
                        binary_rfix=d_rfix, binary=d['binary'], owner=d['decision_owner'],
                        findings=len(lay.get('findings') or []),
                        review_response_model=found[0].get('response_model') if found else None,
                        review_usage=found[0].get('usage') if found else None,
                        seconds=round(time.time() - t0, 2))
    receipt['checks']['end_to_end'] = e2e
    receipt['ok'] = (receipt['checks']['models_listed']['ok'] and receipt['checks']['guided_json']['ok']
                     and all(x['review_response_model'] == a.model_id for x in e2e.values()))
    out = Path(a.out) if a.out else OUTROOT / a.backend / model_dir(a.model_id) / 'smoke.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    print(json.dumps(receipt, ensure_ascii=False, indent=1))
    if not receipt['ok']:
        raise SystemExit('SMOKE_FAILED')


if __name__ == '__main__':
    main()

