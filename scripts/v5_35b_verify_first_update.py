"""CPU verification/export of the first committed optimizer checkpoint."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import tarfile


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8'); temp.replace(path)


def main():
    p = argparse.ArgumentParser(); p.add_argument('--root', type=Path, required=True); a = p.parse_args()
    r = a.root.resolve()
    if not str(r).startswith('/workspace/') or not (r / 'OWNER.json').exists():
        raise ValueError('NOT_AN_OWNED_EXPERIMENT')
    folder = r / 'train-v1/checkpoint-0001'
    record = json.loads((folder / 'CHECKPOINT.json').read_bytes())
    if record['optimizer_updates'] != 1 or record['steps'] != 1 or record['rows_done'] != 16:
        raise ValueError('FIRST_CHECKPOINT_STEP_DRIFT')
    import torch
    from safetensors.torch import load_file
    file = folder / 'adapter/adapter_model.safetensors'; digest = sha(file)
    if digest != record['adapter_sha256']:
        raise ValueError('FIRST_ADAPTER_SHA_DRIFT')
    zero = json.loads((r / 'pilot8-budget9h-v1/DONE.json').read_bytes())
    if digest == zero['zero_adapter_sha256']:
        raise ValueError('ADAPTER_BYTES_UNCHANGED')
    tensors = load_file(file, device='cpu')
    if not tensors or any('.lora_A.' not in k and '.lora_B.' not in k for k in tensors):
        raise ValueError('UNEXPECTED_FIRST_ADAPTER_TENSORS')
    if not all(bool(torch.isfinite(t).all()) for t in tensors.values()):
        raise ValueError('NONFINITE_FIRST_ADAPTER')
    bkeys = [k for k in tensors if '.lora_B.' in k]
    changed = [k for k in bkeys if bool(torch.count_nonzero(tensors[k]))]
    if len(bkeys) != 50 or not changed:
        raise ValueError('FIRST_ADAPTER_B_NOT_UPDATED')
    state = torch.load(folder / 'state.pt', map_location='cpu', weights_only=True)
    if state['steps'] != 1 or state['rows_done'] != 16 or len(state['optimizer']['state']) != len(tensors):
        raise ValueError('FIRST_OPTIMIZER_STATE_DRIFT')
    if any(int(v['step']) != 1 or not bool(torch.isfinite(v['exp_avg']).all()) or
           not bool(torch.isfinite(v['exp_avg_sq']).all()) for v in state['optimizer']['state'].values()):
        raise ValueError('INVALID_FIRST_OPTIMIZER_MOMENTS')
    log = [json.loads(line) for line in (r / 'train-v1/training.jsonl').read_bytes().splitlines()]
    first = log[0]
    if first['step'] != 1 or not math.isfinite(first['loss']) or not math.isfinite(first['grad_norm']):
        raise ValueError('FIRST_PROGRESS_INVALID')
    result = dict(complete=True, optimizer_updates=1, rows_done=16, adapter_sha256=digest,
        zero_adapter_sha256=zero['zero_adapter_sha256'], tensor_count=len(tensors),
        lora_B_tensor_count=len(bkeys), nonzero_lora_B_tensor_count=len(changed),
        all_adapter_weights_finite=True, optimizer_moments_finite=True,
        trainable_parameters=sum(t.numel() for t in tensors.values()), first_progress=first,
        training_profile_sha256=sha(r / 'TRAINING_PROFILE.json'),
        verifier_source_sha256=sha(Path(__file__)), quality_improvement_measured=False)
    write(r / 'FIRST_UPDATE_VERIFIED.json', result)
    archive = r / 'checkpoint0001-export.tar.gz'
    if archive.exists():
        raise FileExistsError('FIRST_CHECKPOINT_EXPORT_EXISTS')
    with tarfile.open(archive, 'w:gz', compresslevel=3) as tar:
        tar.add(folder, arcname='checkpoint-0001')
        tar.add(r / 'FIRST_UPDATE_VERIFIED.json', arcname='FIRST_UPDATE_VERIFIED.json')
    write(r / 'checkpoint0001-export.INDEX.json', dict(complete=True, name=archive.name,
        bytes=archive.stat().st_size, sha256=sha(archive), optimizer_updates=1))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
