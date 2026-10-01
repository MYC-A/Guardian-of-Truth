"""Read API model metadata only. Never emit keys or response/error bodies."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "experiments/searh_23/three_architectures"))
from llm import DEFAULT_MISTRAL_MODEL, _client  # noqa: E402


def probe():
    report = {"observed_at": datetime.now(timezone.utc).isoformat(),
              "env_mistral_model": DEFAULT_MISTRAL_MODEL, "providers": {}}
    for provider in ("mistral", "ollama"):
        try:
            _, client = _client(provider + "/metadata-probe")
            response = client.with_options(timeout=30, max_retries=0).models.list()
            report["providers"][provider] = {"status": "LISTED",
                "models": sorted({item.id for item in response.data})}
        except Exception as exc:
            report["providers"][provider] = {"status": "UNAVAILABLE",
                "error_type": type(exc).__name__,
                "http_status": getattr(exc, "status_code", None)}
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    report = probe()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
