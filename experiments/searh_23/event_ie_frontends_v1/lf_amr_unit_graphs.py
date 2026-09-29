"""Precompute AMR graphs for certificate unit policies (run in amr_env).

Parses every certificate-case policy sentence with the SPRAY/BART AMR
parser and stores the raw graphs keyed by policy hash. lf_certificate.py
(main venv) reads them for the E3W structural witness without needing
the AMR stack.

Run: /workspace/guardian/venvs/amr_env/bin/python lf_amr_unit_graphs.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "outputs"
MODEL = "/workspace/guardian/models/amrlib/model_parse_xfm_bart_large-v0_1_0"


def split_sentences(policy: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", policy.strip())
    return [p for p in parts if p.strip()]


def main() -> None:
    import amrlib
    stog = amrlib.load_stog_model(MODEL, device="cpu")
    items = json.loads((HERE / "frozen" / "certificate_cases.json")
                       .read_text(encoding="utf-8"))
    outdir = OUT / "AMR_UNIT_GRAPHS"
    outdir.mkdir(parents=True, exist_ok=True)
    seen = set()
    for it in items:
        policy = it["policy"]
        key = hashlib.sha256(policy.encode()).hexdigest()[:16]
        if key in seen:
            continue
        seen.add(key)
        sents = split_sentences(policy)
        graphs = stog.parse_sents(sents, disable_progress=True)
        (outdir / f"{key}.json").write_text(
            json.dumps({"policy": policy, "sentences": sents,
                        "graphs": graphs}, indent=1) + "\n",
            encoding="utf-8")
        print(it["id"], len(graphs), "graphs", flush=True)
    print("AMR unit graphs done:", len(seen))


if __name__ == "__main__":
    main()
