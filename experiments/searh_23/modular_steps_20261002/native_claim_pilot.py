"""Two actual native adapters, same frozen claims, one GPU model at a time."""
import gc
import json
import resource
import time
from modular_common import Budget, BudgetStop, HERE, RESULTS, append, sha, write


def run():
    import torch
    from transformers import AutoTokenizer
    from specialist_run import load_checker, REVISIONS, HUB_CACHE
    from factcg_native import native_inputs
    folder = HERE / 'dataset/native_claims'
    manifest = json.loads((folder / 'manifest.json').read_text())
    blob = (folder / 'input.jsonl').read_bytes()
    assert sha(blob) == manifest['input_sha256']
    rows = list(map(json.loads, blob.decode().splitlines()))
    budget = Budget()
    output = RESULTS / 'native_claim_pilot'
    write(output / 'selection.json', manifest)
    journal = output / 'predictions.jsonl'
    done = {(r['model'], r['id']) for r in map(json.loads, journal.read_text().splitlines())} if journal.exists() else set()
    try:
        for name in manifest['model_order']:
            repository = 'lytang/MiniCheck-Flan-T5-Large' if name == 'minicheck' else 'yaxili96/FactCG-DeBERTa-v3-Large'
            tokenizer = AutoTokenizer.from_pretrained(repository, revision=REVISIONS[name], cache_dir=HUB_CACHE, local_files_only=True)
            score, device = load_checker(name)
            torch.cuda.reset_peak_memory_stats()
            for row in rows:
                if (name, row['id']) in done:
                    continue
                values = [row['document'] + tokenizer.eos_token + row['claim']] if name == 'minicheck' else native_inputs(row['document'], row['claim'])
                lengths = [len(tokenizer.encode(v, truncation=False)) for v in values]
                tokens = sum(min(n, 2048) for n in lengths)
                rid = budget.reserve('modular/native/' + name, repository, sha(row), tokens, api=False)
                began = time.monotonic()
                result = score(row['document'], row['claim'])
                elapsed = time.monotonic() - began
                budget.finish(rid, tokens, elapsed, 'NATIVE_COMPLETE')
                append(journal, {'id': row['id'], 'case_id': row['case_id'], 'model': name,
                    'model_revision': REVISIONS[name], 'input_sha256': sha(row), **result,
                    'status': 'VALID' if result['support_score'] is not None else 'INVALID',
                    'native_input_token_lengths': lengths, 'truncated': any(n > 2048 for n in lengths),
                    'native_chunks': len(values), 'elapsed_seconds': elapsed,
                    'peak_vram_bytes': torch.cuda.max_memory_allocated(),
                    'peak_RSS_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
                done.add((name, row['id']))
            del score, tokenizer
            gc.collect()
            torch.cuda.empty_cache()
        write(output / 'status.json', {'state': 'COMPLETED', 'done': len(done), 'budget': budget.snapshot()})
    except BudgetStop:
        write(output / 'status.json', {'state': 'BUDGET_STOP', 'done': len(done), 'budget': budget.snapshot()})
    except Exception as exc:
        write(output / 'status.json', {'state': 'FAILED', 'done': len(done), 'error_type': type(exc).__name__, 'budget': budget.snapshot()})
        raise


if __name__ == '__main__':
    run()
