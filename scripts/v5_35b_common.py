"""Pinned assets and target selection for the isolated 35B experiment."""
import hashlib
import json
from pathlib import Path
import re

BASE_ID = 'cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit'
BASE_REVISION = '00fcea2d3bcf5389b518d4fc082e5590e0ba4844'
FROZEN_SHA256 = '15a55e7e4a4f35b35f36e498f401ad9b373bd8d5533bec874ce8283a3d66f093'
TRAIN_SHA256 = 'd45beff78c52727afdc775f52326f3097e2ce00001b748566a71daae04d6b9dd'
ATTENTION_TARGETS = ('q_proj', 'k_proj', 'v_proj', 'o_proj', 'in_proj_qkv', 'in_proj_z', 'out_proj')
SHARED_TARGETS = ('shared_expert.gate_proj', 'shared_expert.up_proj', 'shared_expert.down_proj')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 << 20), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return [json.loads(line) for line in Path(path).read_bytes().split(b'\n') if line.strip()]


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')
    temporary.replace(path)


def verify_frozen(root):
    root = Path(root)
    if sha(root / 'FROZEN.json') != FROZEN_SHA256:
        raise ValueError('FROZEN_METADATA_DRIFT')
    frozen = json.loads((root / 'FROZEN.json').read_bytes())
    if frozen['status'] != 'EXPLORATORY_ONLY_HUMAN_UNVERIFIED':
        raise ValueError('FROZEN_STATUS_DRIFT')
    for name, digest in frozen['files'].items():
        if Path(name).name != name or sha(root / name) != digest:
            raise ValueError('FROZEN_FILE_DRIFT:' + name)
    if sha(root / 'train.jsonl') != TRAIN_SHA256:
        raise ValueError('TRAIN_SOURCE_DRIFT')
    return frozen


def verify_model(root, manifest_path):
    root = Path(root)
    manifest = json.loads(Path(manifest_path).read_bytes())
    if (manifest['repository'], manifest['revision']) != (BASE_ID, BASE_REVISION):
        raise ValueError('35B_MODEL_IDENTITY_DRIFT')
    for row in manifest['files']:
        name = row['path']
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('UNSAFE_MODEL_MEMBER')
        p = root / name
        if p.stat().st_size != row['size'] or sha(p) != row['sha256']:
            raise ValueError('35B_MODEL_FILE_DRIFT:' + name)
    cfg = json.loads((root / 'config.json').read_bytes())
    q = cfg['quantization_config']
    if cfg['model_type'] != 'qwen3_5_moe' or cfg['text_config']['num_hidden_layers'] != 40:
        raise ValueError('35B_MODEL_ARCHITECTURE_DRIFT')
    if (q['quant_method'], q['bits'], q['group_size']) != ('awq', 4, 32):
        raise ValueError('35B_QUANTIZATION_DRIFT')
    return manifest


def target_suffixes(shared):
    return list(ATTENTION_TARGETS + (SHARED_TARGETS if shared else ()))


def target_names(names, layers, shared):
    """Match only the language tower, never routed experts, vision, router or MTP."""
    if layers not in (8, 40):
        raise ValueError('UNREGISTERED_LAYER_PROFILE')
    suffixes = target_suffixes(shared)
    result = []
    for name in names:
        match = re.search(r'(?:^|\.)language_model\.layers\.(\d+)\.', name)
        if not match or not 40 - layers <= int(match[1]) < 40:
            continue
        if '.mlp.experts.' in name or '.visual.' in name or '.mtp.' in name or name.startswith('mtp.'):
            continue
        if any(name.endswith('.' + suffix) for suffix in suffixes):
            result.append(name)
    return sorted(result)
