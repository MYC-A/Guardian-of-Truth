"""One synthetic B.AI request with credential- and message-safe error metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from guardian_truth.settings import load_env_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    args = parser.parse_args()
    load_env_file(args.env_file)
    import os
    key = os.environ.get("b_ai_api_key", "")
    if not key:
        raise SystemExit("missing b_ai_api_key")
    payload = {"model": "qwen3.8-flash",
               "messages": [{"role": "user", "content": "Return exactly {\"ok\":true}."}],
               "temperature": 0, "stream": False, "max_tokens": 64}
    request = Request("https://api.b.ai/v1/chat/completions",
                      data=json.dumps(payload).encode("utf-8"), method="POST",
                      headers={"Authorization": "Bearer " + key,
                               "Content-Type": "application/json"})
    report = {"model": "qwen3.8-flash", "synthetic_only": True,
              "credential_serialized": False}
    try:
        with urlopen(request, timeout=90) as response:
            body = response.read(1024 * 1024)
            report.update(http_status=response.status, body_bytes=len(body), status="SUCCESS")
    except HTTPError as error:
        with error:
            body = error.read(65537)
            report.update(http_status=error.code, body_bytes=len(body), status="ERROR",
                          body_sha256=hashlib.sha256(body).hexdigest())
            try:
                value = json.loads(body)
                report["top_keys"] = sorted(value) if isinstance(value, dict) else []
                detail = value.get("error", value) if isinstance(value, dict) else {}
                if isinstance(detail, dict):
                    for name in ("type", "code", "param"):
                        item = detail.get(name)
                        if item is None or isinstance(item, (str, int, float, bool)):
                            report[name] = item
                    message = detail.get("message", "")
                    if isinstance(message, str):
                        lowered = message.casefold()
                        report["message_chars"] = len(message)
                        report["message_sha256"] = hashlib.sha256(message.encode()).hexdigest()
                        report["message_flags"] = {word: word in lowered for word in (
                            "balance", "credit", "quota", "billing", "insufficient",
                            "model", "temperature", "max_tokens", "reasoning", "unsupported")}
            except (ValueError, TypeError):
                report["json_body"] = False
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("status") == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
