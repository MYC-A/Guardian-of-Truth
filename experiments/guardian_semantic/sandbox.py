"""Isolated execution of reviewer-written Python (stdlib only).
Isolation: new user+network+mount namespaces (`unshare -rnm`): no network; tmpfs over /proc, /data, /home, /tmp, /root,
/var, /run, /mnt, /opt, /srv, /vercel (no host files, no other processes' environment); empty environment (no secrets);
no Docker socket. Limits (prlimit): CPU 5 s, address space 512 MiB, 64 processes for the uid, 1 MiB files, 64 fds;
wall timeout 10 s; stdout/stderr truncated to 6000 chars. If the isolation preflight fails, code is NOT run on the host
(status ISOLATION_UNAVAILABLE). Input is passed on stdin: PACKET (review packet dict) and SOURCES (source_id -> text)."""
import hashlib, json, subprocess, time

PY = '/usr/bin/python3.13'
MASK = ['/proc', '/data', '/home', '/tmp', '/root', '/var', '/run', '/mnt', '/opt', '/srv', '/vercel']
LIMITS = ['--cpu=5', '--as=536870912', '--nproc=64', '--fsize=1048576', '--nofile=64']
WALL, CAP = 10, 6000
RUNNER = ("import json,sys\n_d=json.load(sys.stdin)\n_c=_d.pop('code')\n"
          "exec(compile(_c,'<reviewer>','exec'),{'PACKET':_d['packet'],'SOURCES':_d['sources'],'__name__':'__main__'})\n")


def _cmd():
    masks = ' && '.join(f'mount -t tmpfs -o size=4m none {d}' for d in MASK)
    return ['unshare', '-rnm', 'sh', '-c', masks + f' && exec env -i PATH=/usr/bin:/bin prlimit {" ".join(LIMITS)} {PY} -I -S -c "$0"', RUNNER]


def sources(packet):
    out = {}
    for k in ('normative_sources', 'declarations', 'history', 'current_targets'):
        for x in packet.get(k) or []:
            out[x['source_id']] = x.get('text')
    return out


def run(code, packet, *, _cmd_override=None):
    import os
    inp = json.dumps(dict(packet=packet, sources=sources(packet)), ensure_ascii=False)
    payload = json.dumps(dict(code=code, packet=packet, sources=sources(packet)), ensure_ascii=False)
    t = time.time()
    try:
        p = subprocess.run(_cmd_override or _cmd(), input=payload.encode(), capture_output=True, timeout=WALL,
                           env={'PATH': '/usr/bin:/bin'})
        status = 'OK' if p.returncode == 0 else 'ERROR'
        out, err, rc = p.stdout.decode('utf-8', 'replace'), p.stderr.decode('utf-8', 'replace'), p.returncode
        if 'unshare:' in err[:200] or ('mount:' in err[:200] and rc != 0 and not out):
            status, out = 'ISOLATION_UNAVAILABLE', ''
    except subprocess.TimeoutExpired as e:
        status, out, err, rc = 'TIMEOUT', (e.stdout or b'').decode('utf-8', 'replace'), (e.stderr or b'').decode('utf-8', 'replace'), None
    return dict(status=status, exit_code=rc, seconds=round(time.time() - t, 3), stdout=out[:CAP], stderr=err[-CAP:],
                stdout_truncated=len(out) > CAP, code_sha256=hashlib.sha256(code.encode()).hexdigest(),
                input_sha256=hashlib.sha256(inp.encode()).hexdigest(), isolation='unshare -rnm + tmpfs masks + env -i + prlimit')


def preflight():
    r = run("import socket,os\ns=socket.socket();s.settimeout(1)\nprint('net', s.connect_ex(('1.1.1.1',443)))\nprint('data', os.listdir('/data'))\nprint('env', sorted(os.environ))", {})
    ok = r['status'] == 'OK' and "data []" in r['stdout'] and 'net 0' not in r['stdout']
    return ok, r
