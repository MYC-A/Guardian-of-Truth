#!/usr/bin/env python3
"""Final pre-benchmark verification (directive: INCONSISTENT -> PROVED_ERROR audit).

Replays the three reported verdict-transition cases (dev-023, hold-099,
hold-100) OFFLINE through the B4h-sound-v1 arm (merged per-slice live caches,
zero LLM calls) and dumps the full proof anatomy per case:

  * world count and per-world obligations / groups / markers;
  * every primitive proof (atom, truth, supporting/refuting evidence ids);
  * per-obligation safety values and the world error value;
  * BOTH evidence (same-position contradictions), if any;
  * the exact FALSE safety witness (obligation whose safety value is FALSE);
  * certificate validity and the witness ids the checker re-executed.

Also runs the independence ablation: each case with the t1 mutation call
REMOVED - if PROVED_ERROR survives without the contradicting verified effect,
the ERROR is certified by the fresh read alone (classification A evidence).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from guardian_truth.vnext.adapters import AdapterMode  # noqa: E402
from guardian_truth.vnext.e2e.backend_v1 import build_live_backend  # noqa: E402
from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1  # noqa: E402
from guardian_truth.vnext.e2e.e2e_types_v1 import E2EArmConfig, E2ESemantics  # noqa: E402
from guardian_truth.vnext.e2e.experiment_v1 import load_corpus, registry_for  # noqa: E402
from guardian_truth.vnext.types import Truth  # noqa: E402

TARGET_CASES = ("dev-023", "hold-099", "hold-100")
CORPORA = {
    "dev": ("outputs/vnext/e2e_v1_dev_corpus.json",
            "outputs/vnext/e2e_v1_dev_llm_cache.json"),
    "holdout": ("outputs/vnext/e2e_v1_holdout_corpus.json",
                "outputs/vnext/e2e_v1_holdout_llm_cache.json"),
}
SLICES = 6
SEMANTICS = E2ESemantics(conservative_state=True, alternative_groups=True,
                         inconsistent_status=True, claim_typing=True)


class OfflineInner:
    def propose(self, task, payload, schema):
        raise RuntimeError(f"OFFLINE CACHE MISS: task={task}")


def replay_backend() -> object:
    backend = build_live_backend(cache_path=None, env_path=ROOT / ".env")
    merged = {}
    for corpus_name in CORPORA:
        for i in range(SLICES):
            path = ROOT / f"outputs/vnext/e2e_v1_cycle3_{corpus_name}_B4h_live_cache_slice{i}.json"
            if path.exists():
                merged.update(json.loads(path.read_text(encoding="utf-8")))
        corpus_cache = ROOT / CORPORA[corpus_name][1]
        if corpus_cache.exists():
            merged.update(json.loads(corpus_cache.read_text(encoding="utf-8")))
    backend.cache.update(merged)
    backend.cache_path = None  # replay-only: never write
    return backend


def describe_case(case, backend) -> dict:
    arm = E2EArmConfig("B4h", ("h0_hist",), ("conservative",))
    guardian = GuardianE2EV1(backend, registry=registry_for(case), arm=arm,
                             max_worlds=4096, adapter_mode=AdapterMode.AUDIT,
                             semantics=SEMANTICS)
    analysis = guardian.analyze_e2e_v1(case)
    result = analysis.result
    worlds = []
    for world in result.world_proofs:
        obligations = []
        for obligation_id, value in world.obligation_safety:
            obligations.append({"obligation_id": obligation_id, "safety": value.name})
        primitives = []
        for prim in world.primitives:
            primitives.append({
                "atom_id": prim.atom.atom_id,
                "kind": prim.atom.kind.value,
                "predicate": prim.atom.predicate,
                "entity": f"{prim.atom.entity.namespace}:{prim.atom.entity.value}",
                "expected": prim.atom.expected_json,
                "time_mode": prim.atom.time_mode.value,
                "truth": prim.value.name,
                "support_ids": list(prim.supports),
                "refute_ids": list(prim.refutes),
                "reasons": [r.name for r in prim.reasons],
            })
        worlds.append({"world_id": world.world_id, "choices": list(world.choices),
                       "safety": obligations, "error_value": world.error_value.name,
                       "primitives": primitives})
    cert = result.certificate_check
    return {
        "case_id": case.case_id,
        "status": result.status.value,
        "world_count": analysis.world_count,
        "required_worlds": analysis.required_worlds,
        "worlds": worlds,
        "certificate_valid": bool(cert and cert.valid),
        "certificate_reasons": list(cert.errors) if cert else [],
        "certified_evidence_ids": sorted({eid for w in result.world_proofs
                                          for prim in w.primitives
                                          for eid in (*prim.supports, *prim.refutes)}),
        "both_evidence": sorted({eid for w in result.world_proofs
                                 for prim in w.primitives
                                 if prim.value is Truth.BOTH
                                 for eid in (*prim.supports, *prim.refutes)}),
        "false_witnesses": [{"world": w.world_id, "obligation_id": oid, "safety": "FALSE"}
                            for w in result.world_proofs for oid, v in w.obligation_safety
                            if v is Truth.FALSE],
        "unknown_conjuncts": [{"world": w.world_id, "obligation_id": oid}
                              for w in result.world_proofs for oid, v in w.obligation_safety
                              if v is Truth.UNKNOWN],
    }


def main():
    backend = replay_backend()
    report = {}
    for corpus_name, (corpus_path, _cache) in CORPORA.items():
        cases = [c for c in load_corpus(ROOT / corpus_path) if c.case_id in TARGET_CASES]
        for case in cases:
            report[case.case_id] = describe_case(case, backend)

    # independence ablation: drop the t1 mutation call/result entirely
    for corpus_name, (corpus_path, _cache) in CORPORA.items():
        for case in load_corpus(ROOT / corpus_path):
            if case.case_id not in TARGET_CASES:
                continue
            trimmed = [h for h in case.history
                       if 'call_id="c1"' not in h]
            ablated = type(case)(**{**case.__dict__, "history": tuple(trimmed)})
            report[case.case_id]["ablation_without_t1_mutation"] = describe_case(ablated, backend)

    out = ROOT / "outputs/vnext/final_verification_inconsistent_to_error.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")

    for cid, detail in report.items():
        print("=" * 72)
        print(f"CASE {cid}: status={detail['status']} worlds={detail['world_count']}"
              f" cert_valid={detail['certificate_valid']}")
        for w in detail["worlds"]:
            print(f"  {w['world_id']} choices={w['choices']} error={w['error_value']}")
            for s in w["safety"]:
                print(f"      safety {s['obligation_id']}: {s['safety']}")
            for p in w["primitives"]:
                sup = ",".join(p["support_ids"]) or "-"
                ref = ",".join(p["refute_ids"]) or "-"
                print(f"      atom {p['predicate']}[{p['entity']}] exp={p['expected']}"
                      f" -> {p['truth']} (sup:{sup} ref:{ref})")
        print(f"  BOTH evidence: {detail['both_evidence'] or 'NONE'}")
        print(f"  FALSE witnesses: {detail['false_witnesses'] or 'NONE'}")
        print(f"  UNKNOWN conjuncts: {detail['unknown_conjuncts'] or 'NONE'}")
        abl = detail["ablation_without_t1_mutation"]
        print(f"  ABLATION (t1 mutation removed): status={abl['status']}"
              f" cert_valid={abl['certificate_valid']}"
              f" FALSE witnesses={abl['false_witnesses'] or 'NONE'}")


if __name__ == "__main__":
    main()
