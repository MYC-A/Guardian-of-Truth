"""Freeze new boundary controls before implementing the anchored extractor.

These are author-written unit contrasts, not a hidden contest benchmark.
Expected cores anchor action clauses. References/entities outside those
cores are not scored as false candidates: this test isolates contamination
and event recovery, not the complete inventory problem.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).parent
CASES = [
    ("e6_prism", "Clean prism C. Calibrate prism C only after the cleaning is verified.",
     ["Clean prism C", "Calibrate prism C", "the cleaning is verified"]),
    ("e6_drum", "Inspect drum 6 before rotating drum 6. Rotate drum 6 only after inspection.",
     ["Inspect drum 6", "rotating drum 6", "Rotate drum 6"]),
    ("e6_rope", "Before cutting rope 9, measure rope 9 and label its ends.",
     ["cutting rope 9", "measure rope 9", "label its ends"]),
    ("e6_shutter", "The operator, after the sensor is checked, must close shutter 2.",
     ["the sensor is checked", "close shutter 2"]),
    ("e6_folio", "Bind folio M when the archivist confirms that all leaves are dry.",
     ["Bind folio M", "the archivist confirms", "all leaves are dry"]),
    ("e6_buoy", "If buoy 5 is damaged, report the fault; otherwise moor buoy 5.",
     ["buoy 5 is damaged", "report the fault", "moor buoy 5"]),
    ("e6_lens", "Focus lens 7 and lock lens 7 before taking a photograph.",
     ["Focus lens 7", "lock lens 7", "taking a photograph"]),
    ("e6_coupon", "Before coating coupon B, verify coupon B's roughness. Coat coupon B after verification.",
     ["coating coupon B", "verify coupon B's roughness", "Coat coupon B"]),
    ("e6_mesh", "Raise mesh 3 only when the actuator works. Inspect mesh 3 before raising it again.",
     ["Raise mesh 3", "the actuator works", "Inspect mesh 3", "raising it again"]),
    ("e6_cue", "The controller must record cue X and then play cue X unless the channel is muted.",
     ["record cue X", "play cue X", "the channel is muted"]),
    ("e6_negative", "Never energize coil H while the panel remains open. Do not bypass the latch.",
     ["energize coil H", "the panel remains open", "bypass the latch"]),
    ("e6_relative", "The crate that arrived yesterday must remain sealed until the inspector releases it.",
     ["arrived yesterday", "remain sealed", "the inspector releases it"]),
]


def main():
    inputs, gold = [], {}
    for cid, policy, cores in CASES:
        inputs.append({"id": cid, "policy": policy})
        gold[cid] = [{"text": text, "start": policy.index(text),
                      "end": policy.index(text)+len(text)} for text in cores]
    frozen = HERE / "frozen"
    frozen.mkdir(exist_ok=True)
    for name, data in (("boundary_inputs.json", inputs), ("boundary_gold.json", gold)):
        path = frozen / name
        if path.exists():
            raise RuntimeError(f"already frozen: {path}")
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {"n_cases": len(inputs), "n_cores": sum(map(len,gold.values())),
                "scope": "new author-written boundary controls; not full event inventory or downstream",
                "metrics": ["required_core_coverage", "clean_core_coverage", "multi_core_candidates", "cross_sentence_candidates"],
                "algorithm_constraint": "sentence terminals + child-clause exclusion + head-containing contiguous chunk; no domain lexicon",
                "hashes": {name: hashlib.sha256((frozen/name).read_bytes()).hexdigest()
                           for name in ("boundary_inputs.json", "boundary_gold.json")}}
    (frozen / "boundary_manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
