"""Finite watcher: resume the same pinned journal only after a budget stop.

No gold reads or algorithm changes. Preserve the first receipt and stop
checkpoint, then permit one bounded continuation of missing pairs only.
"""
import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path


def run(args):
    folder = args.directory
    config = json.loads((folder / "run_config.json").read_text())
    actual = subprocess.check_output(["git", "-C", str(args.repo), "rev-parse", "HEAD"], text=True).strip()
    if actual != config["commit"]:
        raise ValueError("resume checkout is not the original pinned commit")
    deadline = time.monotonic() + args.wait_minutes * 60
    while time.monotonic() < deadline:
        status = json.loads((folder / "status.json").read_text())
        if status["state"] == "SUCCEEDED":
            return 0
        if status["state"] == "BUDGET_STOP":
            # Wait for the original process to release files/GPU before resuming.
            pid = status["pid"]
            for _ in range(30):
                if not Path(f"/proc/{pid}").exists():
                    break
                time.sleep(1)
            else:
                raise RuntimeError("original process still alive after budget stop")
            for name in ("launch_receipt.json", "status.json"):
                preserved = folder / ("before_resume_" + name)
                if preserved.exists():
                    raise ValueError("one continuation already attempted")
                shutil.copyfile(folder / name, preserved)
            command = ["/workspace/guardian/venv/bin/python",
                str(args.repo / "experiments/searh_23/hybrid_service_v1/campaign.py"),
                "--split", config["split"], "--arms", *config["config_sha256"],
                "--max-calls", "1700", "--max-tokens", "2600000", "--max-minutes", "90",
                "--output-root", str(folder.parent)]
            with (folder / "resume_stdout.json").open("w") as out, (
                    folder / "resume_stderr.log").open("w") as err:
                return subprocess.call(command, cwd=args.repo, stdout=out, stderr=err)
        if status["state"] in ("FAILED", "PARTIAL"):
            raise RuntimeError("resume is not authorized for a failed or partial run")
        time.sleep(30)
    raise TimeoutError("finite resume watcher deadline")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--wait-minutes", type=float, default=45)
    args = p.parse_args()
    raise SystemExit(run(args))
