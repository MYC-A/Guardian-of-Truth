"""Finite external sampling of one owned PID; no command/env inspection."""
import argparse
import json
import subprocess
import time
from pathlib import Path


def sample(pid):
    status = Path(f"/proc/{pid}/status")
    if not status.exists():
        return None
    values = {}
    for line in status.read_text().splitlines():
        key, _, value = line.partition(":")
        if key in ("VmRSS", "VmHWM", "VmSize"):
            values[key + "_kib"] = int(value.strip().split()[0])
    result = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory",
        "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
    used = []
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            fields = [x.strip() for x in line.split(",")]
            if len(fields) == 2 and fields[0] == str(pid):
                used.append(int(fields[1]))
    return {"ts": time.time(), "pid": pid, **values, "gpu_used_mib": used,
            "scope": "sampled resident usage, not allocator peak or isolated cold benchmark"}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--max-minutes", type=float, default=150)
    args = p.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.max_minutes * 60
    with args.output.open("a", encoding="utf-8") as file:
        while time.monotonic() < deadline:
            row = sample(args.pid)
            if row is None:
                break
            file.write(json.dumps(row) + "\n")
            file.flush()
            time.sleep(30)
