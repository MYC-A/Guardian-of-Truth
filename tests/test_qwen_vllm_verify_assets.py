import copy
import hashlib
import json

import pytest

from scripts import qwen_vllm_verify_assets as assets


def fixture(tmp_path):
    content = {'one.safetensors': b'weight bytes',
               'model.safetensors.index.json': json.dumps({'weight_map': {'w': 'one.safetensors'}}).encode(),
               'config.json': b'{"quantization_config":{"quant_method":"fp8"}}'}
    siblings = []
    for name, raw in content.items():
        (tmp_path / name).write_bytes(raw)
        entry = dict(rfilename=name, size=len(raw),
                     blobId=hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest())
        if name.endswith('.safetensors'):
            entry['lfs'] = dict(sha256=hashlib.sha256(raw).hexdigest())
        siblings.append(entry)
    return dict(id=assets.REPOSITORY, sha=assets.REVISION, siblings=siblings), list(content)


def test_all_weight_and_small_asset_bytes_have_upstream_proofs(tmp_path):
    meta, selected = fixture(tmp_path)
    result = assets.verify(tmp_path, meta, selected)
    assert result['revision'] == assets.REVISION
    assert {r['upstream_verification']['method'] for r in result['files']} == {
        'UPSTREAM_LFS_SHA256', 'UPSTREAM_GIT_BLOB_SHA1'}


@pytest.mark.parametrize('name', ['one.safetensors', 'config.json'])
def test_same_size_corruption_cannot_pass_local_hash_recording(tmp_path, name):
    meta, selected = fixture(tmp_path)
    raw = (tmp_path / name).read_bytes()
    (tmp_path / name).write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    with pytest.raises(ValueError, match='SHA_MISMATCH|BLOB_MISMATCH'):
        assets.verify(tmp_path, meta, selected)


def test_missing_expected_weight_sha_is_failure(tmp_path):
    meta, selected = fixture(tmp_path)
    meta['siblings'][0].pop('lfs')
    with pytest.raises(ValueError, match='MISSING_UPSTREAM_WEIGHT_SHA'):
        assets.verify(tmp_path, meta, selected)


def test_missing_index_shard_is_failure(tmp_path):
    meta, selected = fixture(tmp_path)
    with pytest.raises(ValueError, match='INDEX_WEIGHT_SET_MISMATCH'):
        assets.verify(tmp_path, meta, selected[1:])


@pytest.mark.parametrize('bad', ['../escape', '/escape', 'folder\\escape'])
def test_unsafe_manifest_paths_are_rejected(tmp_path, bad):
    meta, selected = fixture(tmp_path)
    with pytest.raises(ValueError, match='UNSAFE_ASSET_PATH'):
        assets.verify(tmp_path, meta, selected + [bad])
