#!/usr/bin/env python3
"""Test sanctioned access paths: ENVIRONMENT.txt, secrets readability, gateway process user."""
import os
import subprocess

def run(cmd, timeout=30):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr).strip()

print("== ENVIRONMENT.txt ==")
rc, out = run("cat /mnt/data/guardian/ENVIRONMENT.txt")
print(out)

print("=" * 70)
print("== secrets direct readability test (names only, no values) ==")
rc, out = run("ls /mnt/data/guardian/secrets/")
print(f"ls rc={rc}: {out}")
rc, out = run("test -r /mnt/data/guardian/secrets/mistral.env && echo READABLE || echo NOT_READABLE")
print(out)
rc, out = run("stat -c '%U:%G %a' /mnt/data/guardian/secrets 2>&1; stat -c '%U:%G %a' /mnt/data/guardian/ssh 2>&1")
print(out)

print("=" * 70)
print("== all gateway processes ==")
rc, out = run("ps aux | grep -iE 'gateway|worker' | grep -v grep")
print(out)

print("=" * 70)
print("== gateway-system dir ==")
rc, out = run("ls -la /mnt/data/guardian/gateway-system/ 2>&1")
print(out)

print("=" * 70)
print("== workspace copies of secrets? ==")
rc, out = run("ls -la /mnt/data/guardian/agent-workspace/*.env /mnt/data/guardian/agent-workspace/.env* 2>/dev/null; echo done")
print(out)

print("=" * 70)
print("== check venv python can see mistral key via env of current job ==")
rc, out = run("env | grep -c MISTRAL")
print(f"MISTRAL vars in job env: {out}")
