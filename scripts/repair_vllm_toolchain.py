"""Controlled wrapper-only repair, reusable for diagnostic and full submissions."""
import hashlib
import json
from pathlib import Path
import stat

try:
    from .vllm_bundle_toolchain import wrapper_text
except ImportError:
    from vllm_bundle_toolchain import wrapper_text


def archive_patches(source, *, system_compiler_contrast=True):
    names = set(source.namelist())
    machine, version = 'x86_64-linux-gnu', '13'
    base = f'runtime/toolchain/usr/libexec/gcc/{machine}/{version}/'
    programs = ['runtime/toolchain/usr/bin/' + p for p in ('gcc', 'g++', 'as', 'ld')]
    programs += [base + p for p in ('cc1', 'cc1plus', 'collect2', 'lto1', 'lto-wrapper', 'g++-mapper-server')]
    required = ['runtime/lib/ld-linux-x86-64.so.2',
                f'runtime/toolchain/lib/{machine}/libc.so.6',
                f'runtime/toolchain/usr/lib/{machine}/libstdc++.so.6']
    if any(p not in names for p in required):
        raise ValueError('PRIVATE_TOOLCHAIN_LIBRARIES_MISSING')
    manifest = json.loads(source.read('MANIFEST.json'))['files']
    patches, changes = {}, {}
    for name in programs:
        info = source.getinfo(name)
        raw = source.read(info)
        mode = stat.S_IMODE(info.external_attr >> 16)
        sha = hashlib.sha256(raw).hexdigest()
        record = manifest.get(name, {})
        if record.get('sha256') != sha or record.get('bytes') != len(raw) or record.get('mode') != mode:
            raise ValueError('PATCH_SOURCE_IDENTITY_MISMATCH:' + name)
        native = name + '.real'
        if raw.startswith(b'\x7fELF') and name.endswith('/g++-mapper-server'):
            if native in names:
                raise ValueError('MAPPER_NATIVE_COLLISION')
            patches[native] = (raw, mode)
        elif raw.startswith(b'#!/bin/sh\n') and native in names:
            if (b'--library-path "$root/runtime/lib"' not in raw or
                    ('"$root/' + native + '"').encode() not in raw):
                raise ValueError('UNKNOWN_TOOLCHAIN_WRAPPER:' + name)
        else:
            raise ValueError('UNKNOWN_TOOLCHAIN_PROGRAM:' + name)
        stage = Path('/guardian-stage')
        new = wrapper_text(stage, stage / name, stage / native,
                           driver=name.rsplit('/', 1)[1] in ('gcc', 'g++'),
                           machine=machine, version=version).encode()
        patches[name] = (new, 0o755)
        changes[name] = dict(original_sha256=sha, repaired_sha256=hashlib.sha256(new).hexdigest(),
                             native=native)
    if not system_compiler_contrast:
        return patches, changes
    name = 'runtime/python/run_python.sh'
    raw = source.read(name)
    record = manifest.get(name, {})
    if (record.get('sha256') != hashlib.sha256(raw).hexdigest() or
            record.get('bytes') != len(raw) or record.get('mode') !=
            stat.S_IMODE(source.getinfo(name).external_attr >> 16)):
        raise ValueError('PATCH_SOURCE_IDENTITY_MISMATCH:' + name)
    start = b'export CC="$ROOT/runtime/toolchain/usr/bin/gcc"\n'
    end = b'export PATH="$ROOT/runtime/toolchain/usr/bin:$ROOT/runtime/python/bin:/usr/bin:/bin"\n'
    if raw.count(start) != 1 or raw.count(end) != 1:
        raise ValueError('UNKNOWN_PYTHON_TOOLCHAIN_SELECTION')
    patched = raw.replace(start, b'if [ "${GUARDIAN_USE_SYSTEM_COMPILER:-0}" = 1 ]; then\n'
        b'    test -x /usr/bin/gcc\n    test -x /usr/bin/g++\n'
        b'    export CC=/usr/bin/gcc CXX=/usr/bin/g++\n'
        b'    export PATH="$ROOT/runtime/python/bin:/usr/bin:/bin"\nelse\n' + start)
    patched = patched.replace(end, end + b'fi\n')
    patches[name] = (patched, 0o755)
    changes[name] = dict(original_sha256=hashlib.sha256(raw).hexdigest(),
                         repaired_sha256=hashlib.sha256(patched).hexdigest(),
                         purpose='Optional system-compiler contrast; default remains repaired bundled tools')
    return patches, changes
