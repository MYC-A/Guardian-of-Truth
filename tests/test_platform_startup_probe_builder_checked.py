import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_platform_startup_probe as builder


class Unseekable(io.BytesIO):
    def seek(self, *args):
        raise io.UnsupportedOperation('stream')


def source(path, descriptor=False, zip64=False, bad_manifest=False, duplicate=False):
    stream = Unseekable() if descriptor else io.BytesIO()
    records = {}
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        entries = {
            'runtime/python/run_python.sh': b'#!/bin/sh\n',
            'runtime/site-packages/vendor_cuda.pth': b'import os\n',
            'runtime/site-packages/kernel.bin': b'K' * 500,
            'licenses/NOTICE.txt': b'license',
            f'{builder.MODEL_PREFIX}config.json': b'{}',
            f'{builder.MODEL_PREFIX}tokenizer.json': b'{}',
            f'{builder.MODEL_PREFIX}weights.safetensors': b'NO',
        }
        for name, data in entries.items():
            info = builder.file_info(name, 0o755 if name.endswith('.sh') else 0o644)
            with archive.open(info, 'w', force_zip64=zip64) as target:
                target.write(data)
            records[name] = dict(bytes=len(data), mode=stat.S_IMODE(info.external_attr >> 16), sha256=hashlib.sha256(data).hexdigest())
        if bad_manifest:
            records['runtime/site-packages/vendor_cuda.pth']['sha256'] = '0' * 64
        if duplicate:
            with pytest.warns(UserWarning):
                archive.writestr(builder.file_info('runtime/site-packages/vendor_cuda.pth'), b'DUPLICATE')
        archive.writestr('MANIFEST.json', json.dumps(dict(files=records)))
    path.write_bytes(stream.getvalue())


@pytest.mark.parametrize('descriptor,zip64', [(False, False), (False, True), (True, False), (True, True)])
def test_compressed_members_preserved_and_runtime_pth_allowed(tmp_path, descriptor, zip64):
    src, out = tmp_path / 'source.zip', tmp_path / 'probe.zip'
    source(src, descriptor, zip64)
    receipt = builder.build(out, source_zip=src)
    with zipfile.ZipFile(src) as original, zipfile.ZipFile(out) as target:
        for name in ('runtime/python/run_python.sh', 'runtime/site-packages/vendor_cuda.pth', 'runtime/site-packages/kernel.bin', 'licenses/NOTICE.txt'):
            first, second = original.getinfo(name), target.getinfo(name)
            assert target.read(name) == original.read(name)
            assert second.external_attr == first.external_attr
            assert second.compress_size == first.compress_size
            assert second.flag_bits == first.flag_bits
        assert f'{builder.MODEL_PREFIX}weights.safetensors' not in target.namelist()
        assert target.testzip() is None
    assert receipt['all_copied_members_sha256_and_crc_verified']
    assert receipt['source_identity']['whole_source_sha256_verified'] is False
    assert not Path(str(out) + '.partial').exists()
    assert out.with_name(out.name + '.sha256').read_text().startswith(receipt['sha256'])


def test_tampered_manifest_never_publishes_zip(tmp_path):
    src, out = tmp_path / 'source.zip', tmp_path / 'probe.zip'
    source(src, bad_manifest=True)
    with pytest.raises(ValueError, match='COPIED_MEMBER_VERIFICATION_FAILED'):
        builder.build(out, source_zip=src)
    assert not out.exists()
    assert not Path(str(out) + '.partial').exists()


def test_duplicate_source_name_rejected(tmp_path):
    src, out = tmp_path / 'source.zip', tmp_path / 'probe.zip'
    source(src, duplicate=True)
    with pytest.raises(ValueError, match='DUPLICATE_SOURCE_ENTRIES'):
        builder.build(out, source_zip=src)
    assert not out.exists()


def test_existing_receipt_or_zip_refuses_without_changes(tmp_path):
    src, out = tmp_path / 'source.zip', tmp_path / 'probe.zip'
    source(src)
    receipt = out.with_suffix('.verification.json')
    receipt.write_bytes(b'KEEP')
    with pytest.raises(FileExistsError):
        builder.build(out, source_zip=src)
    assert receipt.read_bytes() == b'KEEP' and not out.exists()


def test_escaping_symlink_rejected(tmp_path):
    src = tmp_path / 'source.zip'
    with zipfile.ZipFile(src, 'w') as archive:
        info = builder.file_info('runtime/escape')
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, b'../../outside')
        archive.writestr(builder.file_info(f'{builder.MODEL_PREFIX}config.json'), b'{}')
    with pytest.raises(ValueError, match='UNSAFE_SYMLINK'):
        builder.build(tmp_path / 'probe.zip', source_zip=src)


def test_runtime_weight_like_suffix_not_filtered():
    assert builder.selected('runtime/vendor/kernel.pth', 500) == 'runtime'
    assert builder.selected('runtime/vendor/kernel.bin', 500) == 'runtime'
    assert builder.selected(f'{builder.MODEL_PREFIX}weights.pth', 500) is None


def test_output_inside_source_inventory_rejected(tmp_path):
    stage = tmp_path / 'stage'
    stage.mkdir()
    with pytest.raises(ValueError, match='OUTPUT_INSIDE_SELECTED_SOURCE_TREE'):
        builder.build(stage / 'runtime/probe.zip', source_root=stage)


def test_bad_streaming_descriptor_is_rejected(tmp_path):
    src, out = tmp_path / 'source.zip', tmp_path / 'probe.zip'
    source(src, descriptor=True, zip64=True)
    data = bytearray(src.read_bytes())
    descriptor_at = data.index(b'PK\x07\x08')
    data[descriptor_at + 4] ^= 1
    src.write_bytes(data)
    with pytest.raises(ValueError, match='INVALID_DATA_DESCRIPTOR'):
        builder.build(out, source_zip=src)
    assert not out.exists() and not Path(str(out) + '.partial').exists()
