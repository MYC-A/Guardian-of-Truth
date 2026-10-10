"""Bundle the local GNU C/C++ tools for offline Triton/Inductor compilation."""
from __future__ import annotations

import os
import json
from pathlib import Path
import shutil
import subprocess


def link_file(source, target):
    source, target = Path(source).resolve(), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(target)
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def tree(source, target):
    source, target = Path(source), Path(target)
    if not source.is_dir():
        raise FileNotFoundError(source)
    for folder, dirs, files in os.walk(source, followlinks=False):
        # Debian include symlinks are files; no external directory traversal.
        for name in files:
            path = Path(folder) / name
            if path.is_file():
                link_file(path, target / path.relative_to(source))


def wrapper(stage, path, native, *, driver=False, machine='', version=''):
    climb = os.path.relpath(stage, path.parent).replace(os.sep, '/')
    relative = native.relative_to(stage).as_posix()
    text = '#!/bin/sh\nset -eu\n'
    text += f'root=$(CDPATH= cd -- "$(dirname -- "$0")/{climb}" && pwd)\n'
    text += 'tools="$root/runtime/toolchain"\n'
    text += 'unset LIBRARY_PATH CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH GCC_EXEC_PREFIX\n'
    text += 'export GCC_EXEC_PREFIX="$tools/usr/lib/gcc/"\n'
    args = ''
    if driver:
        args = (f'--sysroot="$tools" -B"$tools/usr/libexec/gcc/{machine}/{version}/" '
                f'-B"$tools/usr/lib/gcc/{machine}/{version}/" -B"$tools/usr/bin/" ')
    text += ('exec "$root/runtime/lib/ld-linux-x86-64.so.2" '
             '--library-path "$root/runtime/lib" '
             f'"$root/{relative}" {args}"$@"\n')
    path.write_text(text, encoding='utf-8', newline='\n')
    path.chmod(0o755)


def prepare(stage):
    stage = Path(stage).resolve()
    if os.name != 'posix':
        raise RuntimeError('LINUX_TOOLCHAIN_BUILD_REQUIRED')
    gcc, gxx = shutil.which('gcc'), shutil.which('g++')
    if not gcc or not gxx:
        raise RuntimeError('C_AND_CPP_COMPILER_REQUIRED')
    machine = subprocess.check_output([gcc, '-dumpmachine'], text=True).strip()
    version = subprocess.check_output([gcc, '-dumpversion'], text=True).strip()
    if any('/' in x or '\\' in x or '..' in x for x in (machine, version)):
        raise ValueError('INVALID_TOOLCHAIN_IDENTITY')
    tools = stage / 'runtime/toolchain'
    tools.mkdir(parents=True, exist_ok=False)
    tree('/usr/include', tools / 'usr/include')
    tree(Path('/usr/lib/gcc') / machine / version, tools / 'usr/lib/gcc' / machine / version)
    libexec = Path('/usr/libexec/gcc') / machine / version
    if libexec.is_dir():
        tree(libexec, tools / 'usr/libexec/gcc' / machine / version)
    # Preserve ELF loader paths and linker scripts inside the compiler sysroot.
    system_libs = Path('/usr/lib') / machine
    names = ['crt1.o', 'Scrt1.o', 'rcrt1.o', 'crti.o', 'crtn.o', 'libc.so',
             'libc.so.6', 'libc_nonshared.a', 'libm.so', 'libm.so.6', 'libm.a', 'libmvec.so',
             'libmvec.so.1', 'libgcc_s.so.1', 'libstdc++.so.6',
             'libpthread.a', 'libdl.a', 'librt.a', 'libutil.a']
    names += [p.name for p in system_libs.glob('libm-*.a')]
    for name in sorted(set(names)):
        source = system_libs / name
        if source.is_file():
            link_file(source, tools / 'usr/lib' / machine / name)
            # GNU libc linker scripts use both /usr/lib and /lib locations.
            link_file(source, tools / 'lib' / machine / name)
    ld = Path('/lib64/ld-linux-x86-64.so.2')
    link_file(ld, tools / 'lib64' / ld.name)
    driver_paths = []
    for source, name in ((gcc, 'gcc'), (gxx, 'g++'), (shutil.which('as'), 'as'),
                         (shutil.which('ld'), 'ld')):
        if not source:
            raise RuntimeError('MISSING_TOOLCHAIN_PROGRAM:' + name)
        target = tools / 'usr/bin' / name
        link_file(source, target.with_name(target.name + '.real'))
        driver_paths.append((target, name in ('gcc', 'g++')))
    # Frontends are executed by gcc; wrap them too so a newer bundled libc
    # never gets loaded by an older host ELF interpreter.
    for path in list((tools / 'usr/libexec').rglob('*')) + list((tools / 'usr/lib/gcc').rglob('*')):
        if (path.name in {'cc1', 'cc1plus', 'collect2', 'lto1', 'lto-wrapper'}
                and path.is_file() and os.access(path, os.X_OK)):
            with path.open('rb') as stream:
                elf = stream.read(4) == b'\x7fELF'
            if elf:
                real = path.with_name(path.name + '.real')
                path.rename(real)
                driver_paths.append((path, False))
    for path, driver in driver_paths:
        wrapper(stage, path, path.with_name(path.name + '.real'),
                driver=driver, machine=machine, version=version)
    notices = stage / 'licenses/toolchain'
    notices.mkdir(parents=True)
    for package in (f'gcc-{version}', f'g++-{version}', 'gcc', 'binutils', 'libc6-dev', 'libc6'):
        source = Path('/usr/share/doc') / package / 'copyright'
        if source.is_file():
            link_file(source, notices / (package + '.copyright'))
    common = Path('/usr/share/common-licenses')
    for name in ('GPL-3', 'LGPL-2.1', 'LGPL-3'):
        if (common / name).is_file():
            link_file(common / name, notices / name)
    records = subprocess.run(['dpkg-query', '-W', '-f=${Package}\t${Version}\t${source:Package}\t${source:Version}\n',
                              f'gcc-{version}', f'g++-{version}', 'binutils', 'libc6-dev', 'libc6'],
                             capture_output=True, text=True, timeout=10)
    (notices / 'PACKAGE_ORIGINS.json').write_text(json.dumps(dict(
        packages=records.stdout.splitlines(), corresponding_source_archive='https://launchpad.net/ubuntu/+source',
        scope='Unmodified local distribution binaries and headers; copied license notices'), indent=2), encoding='utf-8')
    return dict(machine=machine, version=version, cc='runtime/toolchain/usr/bin/gcc',
                cxx='runtime/toolchain/usr/bin/g++', origin='Local GNU toolchain; no host NVIDIA driver')


def environment_shell(stage=None):
    return ('export CC="$root/runtime/toolchain/usr/bin/gcc"\n'
            'export CXX="$root/runtime/toolchain/usr/bin/g++"\n'
            'export PATH="$root/runtime/toolchain/usr/bin:$root/runtime/python/bin:/usr/bin:/bin"\n')
