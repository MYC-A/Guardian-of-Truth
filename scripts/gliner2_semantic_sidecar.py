#!/usr/bin/env python3
"""One-shot JSON stdin/stdout GLiNER2.5 worker for its isolated environment."""

from __future__ import annotations

from contextlib import redirect_stdout
import json
import sys
import time


def main() -> int:
    request = json.load(sys.stdin)
    started = time.monotonic()
    # Keep library progress messages away from the JSON protocol on stdout.
    with redirect_stdout(sys.stderr):
        from gliner2 import AutoExtractor
        loaded_at = time.monotonic()
        model = AutoExtractor.from_pretrained(
            request["model"], map_location=request.get("device", "cuda"),
            quantize=bool(request.get("quantize", True)),
        )
        load_finished = time.monotonic()
        rows = []
        for item in request.get("items", ()):
            text = item["text"]
            entities = model.extract_entities(
                text, request["entity_labels"], include_confidence=True, include_spans=True)
            relations = model.extract_relations(
                text, request["relation_labels"], include_confidence=True, include_spans=True)
            rows.append({"id": item["id"], "entities": entities,
                         "relations": relations})
        finished = time.monotonic()
    response = {
        "status": "EXECUTED",
        "model": request["model"],
        "architecture": getattr(getattr(model, "config", None), "architecture", None),
        "device": request.get("device", "cuda"),
        "load_duration_s": round(load_finished - loaded_at, 6),
        "execution_duration_s": round(finished - load_finished, 6),
        "total_duration_s": round(finished - started, 6),
        "rows": rows,
    }
    sys.stdout.write(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
