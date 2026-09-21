#!/usr/bin/env python3
"""Sweep: перезапуск FAILED-записей джорнала с KEYLESS_NO_CACHE=1 (свежие вызовы).

用法 (на сервере): python sweep_failed.py <journal_path> <runner_cmd...>
1. FAILED-строки переносятся в <journal>.failed.bak
2. runner перезапускается с env KEYLESS_NO_CACHE=1 (только незавершённые кейсы)
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    journal = Path(sys.argv[1])
    cmd = sys.argv[2:]
    if not journal.is_file():
        print("no journal:", journal)
        return 1
    rows = []
    with open(journal, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rows.append((line, json.loads(line)))
            except json.JSONDecodeError:
                continue
    failed = [l for l, r in rows if r.get("status") != "OK"]
    kept = [l for l, r in rows if r.get("status") == "OK"]
    if not failed:
        print("nothing to sweep (all OK)")
        return 0
    bak = journal.with_suffix(journal.suffix + ".failed.bak")
    with open(bak, "a", encoding="utf-8") as f:
        f.writelines(failed)
    with open(journal, "w", encoding="utf-8") as f:
        f.writelines(kept)
    print(f"swept {len(failed)} FAILED lines to {bak.name}; kept {len(kept)} OK")
    import os
    env = dict(os.environ)
    env["KEYLESS_NO_CACHE"] = "1"
    W = "/mnt/data/guardian/agent-workspace/Guardian-superz-fullcycle"
    r = subprocess.run(cmd, env=env, cwd=W)
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
