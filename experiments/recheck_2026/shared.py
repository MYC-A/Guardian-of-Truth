"""Input, model transport, and output contracts shared by recheck runners."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CASES = REPO / "outputs/full21/input/public46_label_free.csv"
DEFAULT_GOLD = REPO / "outputs/full21/control_repro_percase.csv"
DEFAULT_MISTRAL_ENV_FILE = Path("/mnt/data/guardian/secrets/mistral.env")
FALLBACK_MISTRAL_ENV_FILE = Path("/mnt/data/guardian/agent-workspace/.mistral.env")


def mistral_settings() -> dict[str, str]:
    """Read the existing server secret file without copying or logging it."""
    configured = os.getenv("MISTRAL_ENV_FILE")
    path = Path(configured) if configured else next(
        (candidate for candidate in (DEFAULT_MISTRAL_ENV_FILE,
                                      FALLBACK_MISTRAL_ENV_FILE)
         if os.access(candidate, os.R_OK) and candidate.is_file()),
        DEFAULT_MISTRAL_ENV_FILE)
    saved: dict[str, str] = {}
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("export "):
                line = line[7:].strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() in {"MISTRAL_API_KEY", "MISTRAL_MODEL"}:
                saved[key.strip()] = value.strip().strip("\"'")
    return {"MISTRAL_API_KEY": os.getenv("MISTRAL_API_KEY") or saved.get("MISTRAL_API_KEY", ""),
            "MISTRAL_MODEL": os.getenv("MISTRAL_MODEL") or saved.get(
                "MISTRAL_MODEL", "ministral-14b-latest")}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def cases(path: Path) -> dict[str, dict]:
    csv.field_size_limit(1 << 30)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"id", "prompt", "response"} <= set(reader.fieldnames or ()):
            raise ValueError("cases need id,prompt,response")
        rows = list(reader)
    result = {r["id"]: r for r in rows}
    if len(result) != len(rows) or any(not key for key in result):
        raise ValueError("duplicate or empty case id")
    return result


def policy_text(case: dict) -> str:
    match = re.search(r"<policy>(.*?)</policy>", case["prompt"], re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else case["prompt"]


def labels(path: Path | None, column: str = "gold") -> dict[str, int]:
    if path is None:
        return {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        result = {}
        for row in csv.DictReader(stream):
            if row.get(column) not in {"0", "1"}:
                raise ValueError(f"invalid {column} label for {row.get('id')}")
            if row["id"] in result:
                raise ValueError(f"duplicate label id {row['id']}")
            result[row["id"]] = int(row[column])
    return result


def jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary.replace(path)


def new_output(path: Path) -> Path:
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(f"refusing to overwrite {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


def prepare_run(path: Path, config: dict, resume: bool = False) -> list[dict]:
    """Create a run or resume only when the frozen input/config match exactly."""
    if path.exists() and any(path.iterdir()):
        if not resume:
            raise FileExistsError(f"refusing to overwrite {path}; pass --resume")
        config_path = path / "config.json"
        if not config_path.exists() or json.loads(config_path.read_text(encoding="utf-8")) != config:
            raise ValueError("resume config differs from existing run")
        records_path = path / "records.jsonl"
        return jsonl(records_path) if records_path.exists() else []
    path.mkdir(parents=True, exist_ok=True)
    write_json(path / "config.json", config)
    return []


def score(rows: list[dict], pred: str, gold: str = "gold") -> dict:
    valid = [r for r in rows if r.get(pred) in (0, 1) and r.get(gold) in (0, 1)]
    tp = sum(r[pred] == r[gold] == 1 for r in valid)
    fp = sum(r[pred] == 1 and r[gold] == 0 for r in valid)
    fn = sum(r[pred] == 0 and r[gold] == 1 for r in valid)
    tn = sum(r[pred] == r[gold] == 0 for r in valid)
    return {"n": len(valid), "TP": tp, "FP": fp, "FN": fn, "TN": tn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "F1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}


def bounded(text: str, limit: int, mode: str = "head_tail") -> dict:
    if limit < 200:
        raise ValueError("context limit must be at least 200 characters")
    if len(text) <= limit:
        return {"text": text, "original_chars": len(text), "kept_chars": len(text),
                "truncated": False, "mode": mode}
    marker = "\n[... omitted context ...]\n"
    if mode == "head":
        kept = text[:limit]
    elif mode == "tail":
        kept = text[-limit:]
    elif mode == "head_tail":
        left = (limit - len(marker)) // 2
        kept = text[:left] + marker + text[-(limit - len(marker) - left):]
    else:
        raise ValueError(f"unknown context mode {mode}")
    return {"text": kept, "original_chars": len(text), "kept_chars": len(kept),
            "truncated": True, "mode": mode}


def json_object(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        try:
            value = json.loads(text, strict=False)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                raise ValueError("model returned no JSON object") from None
            value = json.loads(match.group(), strict=False)
    if not isinstance(value, dict):
        raise ValueError("model returned non-object JSON")
    return value


class Mistral:
    def __init__(self, *, model: str | None = None, api_key: str | None = None):
        settings = mistral_settings()
        self.model = model or settings["MISTRAL_MODEL"]
        self.key = api_key or settings["MISTRAL_API_KEY"]
        if not self.key:
            raise RuntimeError("MISTRAL_API_KEY is required for live runs")

    def ask(self, system: str, user: str, *, max_tokens: int = 400) -> dict:
        payload = {"model": self.model, "temperature": 0,
                   "max_tokens": max_tokens,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}]}
        request = urllib.request.Request(
            "https://api.mistral.ai/v1/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.key}",
                     "Content-Type": "application/json"})
        start = time.perf_counter()
        with urllib.request.urlopen(request, timeout=300) as response:
            body = json.load(response)
        choice = body["choices"][0]
        raw = choice["message"]["content"]
        return {"value": json_object(raw), "raw": raw,
                "finish_reason": choice.get("finish_reason"),
                "latency_s": round(time.perf_counter() - start, 3),
                "input_sha256": hashlib.sha256((system + "\n" + user).encode("utf-8")).hexdigest(),
                "input_chars": len(system) + len(user),
                "model": body.get("model", self.model), "usage": body.get("usage", {})}
