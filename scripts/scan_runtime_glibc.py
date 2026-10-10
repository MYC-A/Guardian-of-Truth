"""Find runtime programs that would run on the host glibc and need a newer one.

A program started as a separate process (gcc, as, ld, ptxas, ninja...) uses the
host's /lib64/ld-linux loader and libc, not the bundled one. If its
.gnu.version_r asks for GLIBC_X.Y newer than the host has, it fails exactly like
gcc.real did on the platform (host glibc < 2.36). Pure stdlib, works on Windows,
reads the ZIP without extracting. Libraries loaded into the bundled Python are
reported separately (they use the bundled libc and are not at risk).
"""
import argparse
import json
from pathlib import Path
import stat
import struct
import zipfile


def glibc_key(version):
    return tuple(int(part) for part in version.split('_', 1)[1].split('.'))


def parse_elf(data):
    """Return dict(kind, interp, glibc=[versions]) for 64-bit little-endian ELF, else None."""
    if len(data) < 64 or data[:4] != b'\x7fELF' or data[4] != 2 or data[5] != 1:
        return None
    e_type, = struct.unpack_from('<H', data, 16)
    e_phoff, e_shoff = struct.unpack_from('<QQ', data, 32)
    e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx = struct.unpack_from('<HHHHH', data, 54)
    interp = None
    for index in range(e_phnum):
        offset = e_phoff + index * e_phentsize
        if offset + 56 > len(data):
            break
        p_type, = struct.unpack_from('<I', data, offset)
        if p_type == 3:  # PT_INTERP
            p_offset, = struct.unpack_from('<Q', data, offset + 8)
            p_filesz, = struct.unpack_from('<Q', data, offset + 32)
            interp = data[p_offset:p_offset + p_filesz].rstrip(b'\0').decode('ascii', 'replace')
    sections = []
    for index in range(e_shnum):
        offset = e_shoff + index * e_shentsize
        if offset + 64 > len(data):
            break
        sh_name, sh_type = struct.unpack_from('<II', data, offset)
        sh_offset, sh_size = struct.unpack_from('<QQ', data, offset + 24)
        sh_link, = struct.unpack_from('<I', data, offset + 40)
        sections.append((sh_name, sh_type, sh_offset, sh_size, sh_link))
    versions = set()
    for _, sh_type, sh_offset, sh_size, sh_link in sections:
        if sh_type != 0x6ffffffe or sh_link >= len(sections):  # SHT_GNU_verneed
            continue
        strtab = sections[sh_link]
        def name(at):
            start = strtab[2] + at
            return data[start:data.index(b'\0', start)].decode('ascii', 'replace')
        cursor = sh_offset
        while cursor < sh_offset + sh_size:
            vn_version, vn_cnt, vn_file, vn_aux, vn_next = struct.unpack_from('<HHIII', data, cursor)
            aux = cursor + vn_aux
            for _ in range(vn_cnt):
                _, _, _, vna_name, vna_next = struct.unpack_from('<IHHII', data, aux)
                label = name(vna_name)
                if label.startswith('GLIBC_') and label[6:7].isdigit():
                    versions.add(label)
                if not vna_next:
                    break
                aux += vna_next
            if not vn_next:
                break
            cursor += vn_next
    kind = {2: 'EXEC', 3: 'DYN'}.get(e_type, str(e_type))
    return dict(kind=kind, interp=interp, glibc=sorted(versions, key=glibc_key))


def entries(source):
    source = Path(source)
    if source.is_file():
        with zipfile.ZipFile(source) as archive:
            for info in archive.infolist():
                mode = info.external_attr >> 16
                if info.is_dir() or stat.S_ISLNK(mode):
                    continue
                with archive.open(info) as stream:
                    head = stream.read(4)
                if head != b'\x7fELF':
                    continue
                yield info.filename, bool(mode & 0o111), (lambda info=info: archive.read(info))
        return
    for path in sorted(source.rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open('rb') as stream:
            if stream.read(4) != b'\x7fELF':
                continue
        yield path.relative_to(source).as_posix(), bool(path.stat().st_mode & 0o111), path.read_bytes


def scan(source, host_glibc='2.35'):
    limit = glibc_key('GLIBC_' + host_glibc)
    programs, libraries, statics = [], 0, []
    for name, executable, read in entries(source):
        info = parse_elf(read())
        if info is None:
            continue
        newest = info['glibc'][-1] if info['glibc'] else None
        too_new = bool(newest and glibc_key(newest) > limit)
        if info['interp'] is None:
            if info['kind'] == 'EXEC':
                statics.append(name)
            else:
                libraries += too_new
            continue
        # Has PT_INTERP: started as its own process via that loader (host one unless bundled).
        programs.append(dict(path=name, interp=info['interp'], newest_glibc=newest,
                             needs_newer_than_host=too_new, executable_bit=executable))
    risky = [p for p in programs if p['needs_newer_than_host']]
    return dict(host_glibc=host_glibc, programs_with_interpreter=len(programs),
                at_risk=sorted(risky, key=lambda p: p['path']),
                safe_programs=sorted(p['path'] for p in programs if not p['needs_newer_than_host']),
                static_programs=sorted(statics),
                in_process_libraries_needing_newer_glibc=libraries)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', help='runtime ZIP, competition ZIP or unpacked directory')
    parser.add_argument('--host-glibc', default='2.35')
    parser.add_argument('--json', type=Path)
    options = parser.parse_args()
    report = scan(options.source, options.host_glibc)
    if options.json:
        options.json.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"host glibc {report['host_glibc']}: {report['programs_with_interpreter']} dynamic programs, "
          f"{len(report['at_risk'])} at risk, {len(report['static_programs'])} static")
    for item in report['at_risk']:
        print(f"AT RISK  {item['path']}  needs {item['newest_glibc']}  interp={item['interp']}")
