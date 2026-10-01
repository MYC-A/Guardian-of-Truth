"""Package/process metadata; no environment variable or credential dump."""
import argparse
import importlib.metadata
import json
import os
import platform
from pathlib import Path


def report():
    packages = {}
    for name in ("fastapi", "uvicorn", "openai", "pandas", "pyarrow", "torch",
                 "transformers", "nltk", "psutil"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {"python": platform.python_version(), "platform": platform.system(),
            "pid": os.getpid(), "packages": packages}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    value = report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(value))
