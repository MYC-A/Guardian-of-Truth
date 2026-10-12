"""Enforce preservation of model requests and fail closed on archive corruption."""
import ast
import hashlib
import json
from pathlib import Path
import stat
import zipfile

import pytest

from scripts import build_b2_rowfix_submission as builder
from scripts import qwen_vllm_adapter as adapter


def test_adapter_logging_removal_preserves_all_inference_statements():
    source = Path(adapter.__file__).read_bytes()
    tree = ast.parse(source)
    tree.body = [n for n in tree.body if not isinstance(n, ast.FunctionDef) or n.name != 'emit_row_progress']
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    class RemoveCall(ast.NodeTransformer):
        def visit_Expr(self, node):
            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == 'emit_row_progress':
                return None
            return node
    RemoveCall().visit(main)
    original = ast.unparse(tree).encode()
    assert builder.logging_only_adapter(original, source) == source
    with pytest.raises(ValueError, match='NON_LOGGING_ADAPTER_CHANGE'):
        builder.logging_only_adapter(original, source.replace(b"'--enable-prefix-caching'", b"'--disable-prefix-caching'"))


def test_member_validation_checks_content_mode_and_full_set(tmp_path):
    archive = tmp_path / 'small.zip'
    data = b'actual payload'
    info = zipfile.ZipInfo('payload')
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o755) << 16
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr(info, data)
    record = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), mode=0o755)
    builder.validate_members(archive, {'payload': record})
    with pytest.raises(ValueError, match='FINAL_MEMBER_MISMATCH'):
        builder.validate_members(archive, {'payload': dict(record, sha256='0' * 64)})
    with pytest.raises(ValueError, match='FINAL_MEMBER_MISMATCH'):
        builder.validate_members(archive, {'payload': dict(record, mode=0o644)})
    with pytest.raises(ValueError, match='FINAL_FILE_SET_MISMATCH'):
        builder.validate_members(archive, {})


def test_wrong_source_hash_never_creates_a_candidate(tmp_path):
    source = tmp_path / 'source.zip'
    source.write_bytes(b'not the pinned archive')
    output = tmp_path / 'candidate.zip'
    with pytest.raises(ValueError, match='SOURCE_ZIP_SHA256_MISMATCH'):
        builder.build(source, output)
    assert not output.exists() and not output.with_name(output.name + '.partial').exists()


def test_whole_repack_preserves_weights_runtime_and_publishes_verified_receipts(tmp_path):
    tree = ast.parse(Path(adapter.__file__).read_bytes())
    class Strip(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            return None if node.name == 'emit_row_progress' else self.generic_visit(node)
        def visit_Expr(self, node):
            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == 'emit_row_progress':
                return None
            return self.generic_visit(node)
    old_adapter = ast.unparse(Strip().visit(tree)).encode()
    payloads = {'scripts/predict.py': b'old entrypoint',
                'scripts/qwen_vllm_adapter.py': old_adapter, 'README.md': b'old readme',
                'runtime/python/run_python.sh': b'#!/bin/sh\nunchanged runtime',
                'model/pinned/weights.safetensors': b'unchanged model bytes' * 100}
    files = {name: dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                       mode=0o755 if name.endswith('.sh') else 0o644) for name, data in payloads.items()}
    manifest = dict(files=files, model_mode='FULL_MODELS_SHA256_VERIFIED', source_sha='original-build')
    source = tmp_path / 'source.zip'
    with zipfile.ZipFile(source, 'w') as bundle:
        for name, data in dict(payloads, **{'MANIFEST.json': builder.json_bytes(manifest)}).items():
            mode = files[name]['mode'] if name in files else 0o644
            bundle.writestr(builder.file_info(name, mode), data)
    source_bytes = source.read_bytes()
    output = tmp_path / 'candidate.zip'
    result = builder.build(source, output, source_sha256=hashlib.sha256(source_bytes).hexdigest())
    assert source.read_bytes() == source_bytes
    assert result['all_members_verified'] is True and result['under_cap'] is True
    assert hashlib.sha256(output.read_bytes()).hexdigest() == result['sha256']
    with zipfile.ZipFile(output) as bundle:
        for name in ('runtime/python/run_python.sh', 'model/pinned/weights.safetensors'):
            assert bundle.read(name) == payloads[name]
        repaired = json.loads(bundle.read('MANIFEST.json'))
        assert repaired['source_sha'] == 'original-build'
        assert repaired['operator_row_identity_repair']['row_identity'] == 'POSITION'
        assert repaired['files']['model/pinned/weights.safetensors'] == files['model/pinned/weights.safetensors']
    assert json.loads(output.with_suffix('.ready.json').read_text())['real_model_quality_and_full_platform_time_tested'] is False
    assert not output.with_name(output.name + '.partial').exists()
