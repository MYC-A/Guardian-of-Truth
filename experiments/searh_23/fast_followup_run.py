#!/usr/bin/env python3
"""Gold-free, resumable paired run for the fast Guardian follow-up.

Stages: prepare -> local/witness -> pgjudge -> refute -> tq -> score.
Only score reads labels. Every stage checks the frozen input hash.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for directory in ("src", "experiments/full21", "experiments/big_researh",
                  "experiments/searh_23"):
    sys.path.insert(0, str(REPO / directory))

from guardian_truth.parsing import parse_events  # noqa: E402
from demo_frozen import granite_label, structural_label  # noqa: E402
from preprocess_granite_function_calls import prepare_record  # noqa: E402
from run_granite_modes import GraniteLocalRunner, SCORE_RE  # noqa: E402
import fp_refute_layer_v3 as v3  # noqa: E402
import fp_refute_layer_v4 as v4  # noqa: E402
import p_precond_api as pg  # noqa: E402
import tq_questions as tq  # noqa: E402
import typed_witnesses as witnesses  # noqa: E402
import feasibility_witness as feasibility  # noqa: E402
import completion_witness as completion  # noqa: E402

MANIFEST_VERSION = "fast-followup-v1"
CONTEXT_BUDGETS = (12000, 24000, 60000)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_cases(path: Path) -> list[dict]:
    csv.field_size_limit(2 ** 30)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        if fields != {"id", "prompt", "response"}:
            raise ValueError("inference CSV must contain exactly id,prompt,response")
        cases = list(reader)
    ids = [row["id"] for row in cases]
    if not cases or any(not cid for cid in ids) or len(ids) != len(set(ids)):
        raise ValueError("cases must have unique nonempty ids")
    return cases


def read_jsonl(path: Path, *, require_ok: bool = False) -> dict[str, dict]:
    if not path.is_file():
        raise FileNotFoundError(path)
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if not require_ok or row.get("status") == "OK":
                result[row["id"]] = row
    return result


def prepare(cases_path: Path, run_dir: Path) -> None:
    cases_path = cases_path.resolve()
    cases = read_cases(cases_path)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "manifest.json"
    if path.exists():
        raise FileExistsError(f"manifest already exists: {path}")
    shape = {}
    for row in cases:
        calls = [e for e in parse_events(row["response"], "response")
                 if e.role == "assistant" and e.kind == "call"]
        shape[row["id"]] = bool(calls)
    manifest = {"version": MANIFEST_VERSION, "cases": str(cases_path),
                "cases_sha256": file_hash(cases_path), "ids": [r["id"] for r in cases],
                "response_has_call": shape}
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"prepared {len(cases)} label-free cases at {run_dir}")


def frozen(run_dir: Path) -> tuple[dict, list[dict]]:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != MANIFEST_VERSION:
        raise ValueError("manifest version mismatch")
    cases_path = Path(manifest["cases"])
    if file_hash(cases_path) != manifest["cases_sha256"]:
        raise ValueError("frozen cases changed")
    cases = read_cases(cases_path)
    if [r["id"] for r in cases] != manifest["ids"]:
        raise ValueError("case IDs/order changed")
    return manifest, cases


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def local_stage(run_dir: Path, model_path: Path, skip_model: bool) -> None:
    manifest, cases = frozen(run_dir)
    path = run_dir / "local.jsonl"
    done = read_jsonl(path, require_ok=True) if path.exists() else {}
    model = None if skip_model else GraniteLocalRunner(model_path)
    for case in cases:
        cid = case["id"]
        if cid in done:
            continue
        prompt, response = case["prompt"], case["response"]
        row = {"id": cid, "status": "PARTIAL" if skip_model else "OK",
               "input_sha256": hashlib.sha256(
                   (prompt + "\0" + response).encode("utf-8")).hexdigest(),
               "shape_call": manifest["response_has_call"][cid],
               "structural": structural_label(prompt, response)}
        if model is not None:
            row["granite"] = {}
            for budget in CONTEXT_BUDGETS:
                row["granite"][str(budget)] = granite_label(
                    model, prompt, response, max_context_chars=budget)
            row["c1"] = {
                str(budget): (None if row["granite"][str(budget)]["label"] is None
                              else int(row["structural"]["label"] == 1 or
                                       row["granite"][str(budget)]["label"] == 1))
                for budget in CONTEXT_BUDGETS}
            prepared = prepare_record(case)
            row["function_call"] = {"adapter_status": prepared.row["adapter_status"],
                                    "adapter_reason": prepared.row["adapter_reason"],
                                    "trace": prepared.trace}
            if prepared.row["adapter_status"] == "ready":
                messages = [{"role": "user", "content": prepared.row["prompt"]},
                            {"role": "assistant", "content": prepared.row["response"]}]
                chat = model.tokenizer.apply_chat_template(
                    messages, guardian_config={"criteria_id": "function_call"},
                    available_tools=json.loads(prepared.row["tools"]), think=False,
                    tokenize=False, add_generation_prompt=True)
                generation = model.generate(chat, 200)
                matches = SCORE_RE.findall(generation["text"])
                row["function_call"].update({
                    "label": None if not matches else int(matches[-1].lower() == "yes"),
                    "raw_excerpt": generation["text"][:200],
                    "input_token_count": generation["input_token_count"]})
            else:
                row["function_call"]["label"] = None
        append_jsonl(path, row)
        print(f"[local] {cid}: {row['status']}", flush=True)


def witness_stage(run_dir: Path) -> None:
    """Gold-free source inventory; this diagnostic never changes a label."""
    manifest, cases = frozen(run_dir)
    path = run_dir / "witnesses.json"
    if path.exists():
        raise FileExistsError(path)
    rows = [{"id": case["id"], **witnesses.local_record(case)} for case in cases]
    path.write_text(json.dumps({"input_sha256": manifest["cases_sha256"],
                                "per_case": rows}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(f"recorded source witnesses for {len(rows)} cases")


def feasibility_stage(run_dir: Path) -> None:
    _, cases = frozen(run_dir)
    feasibility.run(cases, run_dir / "feasibility.jsonl")


def completion_stage(run_dir: Path) -> None:
    _, cases = frozen(run_dir)
    completion.run(cases, run_dir / "completion.jsonl")


def pgjudge_stage(run_dir: Path) -> None:
    _, cases = frozen(run_dir)
    if not pg.API_KEY:
        raise RuntimeError("MISTRAL_API_KEY missing; set it in the server environment")
    pg.OUT_ROOT = run_dir / "pgjudge"
    pg.run_extract(cases)
    cards_path = pg.OUT_ROOT / "extract/cards.jsonl"
    reanchor_cards(cases, cards_path)
    extracted = read_jsonl(cards_path, require_ok=True)
    missing = [c["id"] for c in cases if c["id"] not in extracted]
    if missing:
        raise RuntimeError(f"card extraction incomplete: {missing}")
    pg.run_judge(cases, "pgjudge")
    judged = read_jsonl(pg.OUT_ROOT / "pgjudge/records.jsonl", require_ok=True)
    missing = [c["id"] for c in cases if c["id"] not in judged]
    if missing:
        raise RuntimeError(f"pgjudge incomplete: {missing}")


def reanchor_cards(cases: list[dict], cards_path: Path) -> None:
    """Repair source line-wraps without changing model-generated card content.

    The journal remains append-only. `cards_block` and scoring use the latest
    successful record; the original model card and its failed anchor survive.
    """
    latest = read_jsonl(cards_path, require_ok=True)
    for case in cases:
        row = latest.get(case["id"])
        if row is None:
            continue
        policy = pg.policy_text(case)
        changed = False
        cards = []
        for card in row.get("cards", []):
            card = dict(card)
            if not card.get("quote_grounded"):
                proposed = card.get("policy_quote") or ""
                start, end, issues = pg.anchor_quote(proposed, policy)
                if start is not None:
                    card["model_policy_quote"] = proposed
                    card["policy_quote"] = policy[start:end]
                    card["quote_grounded"] = True
                    card["quote_issues"] = issues
                    card["policy_source_span"] = [start, end]
                    changed = True
            cards.append(card)
        if changed:
            updated = {**row, "cards": cards, "n_grounded": sum(
                bool(card.get("quote_grounded")) for card in cards),
                "source_reanchored": True}
            append_jsonl(cards_path, updated)


def card_decisions(base: dict, grounded: list[dict], sig: dict, refuter,
                   *, structural_guard: str | None = None) -> tuple[int, list[dict]]:
    idxs = base.get("violated_cards") or []
    if not isinstance(idxs, list):
        idxs = []
    if idxs and any(not isinstance(i, int) or i < 1 or i > len(grounded)
                    for i in idxs):
        verdicts = [{"verdict": "UNKNOWN", "evidence": "invalid grounded-card index"}]
    elif not idxs:
        verdict, evidence = refuter(None, sig, base.get("reason") or "")
        verdicts = [{"verdict": verdict, "evidence": evidence}]
    else:
        verdicts = []
        for idx in idxs:
            verdict, evidence = refuter(grounded[idx - 1], sig,
                                       base.get("reason") or "")
            verdicts.append({"card_index": idx, "verdict": verdict,
                             "evidence": evidence})
    if structural_guard:
        verdicts.insert(0, {"verdict": "STRUCTURAL_GUARD",
                            "evidence": structural_guard})
    return int(not verdicts or any(v["verdict"] != "REFUTED" for v in verdicts)), verdicts


def source_safe_guard(guard: str | None) -> str | None:
    """A listed catalog may be incomplete; explicit required fields remain binding."""
    return None if guard and guard.startswith("undeclared tool called:") else guard


def refute_stage(run_dir: Path) -> None:
    _, cases = frozen(run_dir)
    case_map = {c["id"]: c for c in cases}
    records = read_jsonl(run_dir / "pgjudge/pgjudge/records.jsonl", require_ok=True)
    cards = read_jsonl(run_dir / "pgjudge/extract/cards.jsonl", require_ok=True)
    if set(records) != set(case_map) or set(cards) != set(case_map):
        raise ValueError("pgjudge/card coverage incomplete")
    output = {"layer": "v3.1 / v4 / v4-source-safe gold-free replay",
              "input_sha256": frozen(run_dir)[0]["cases_sha256"],
              "per_case": []}
    for cid in sorted(case_map):
        base = records[cid]
        row = {"id": cid, "gold": None, "pgjudge": base["label"],
               "new_label": base["label"]}
        if base["label"] == 1:
            case = case_map[cid]
            grounded = [c for c in cards[cid].get("cards", [])
                        if c.get("quote_grounded")]
            s3 = v3.case_signals(case["prompt"], case["response"])
            s4 = v4.case_signals(case["prompt"], case["response"])
            l3, d3 = card_decisions(base, grounded, s3, v3.refute_card)
            guard = v4.structural_violation(case["prompt"], case["response"])
            l4, d4 = card_decisions(base, grounded, s4, v4.refute_card,
                                    structural_guard=guard)
            # A parsed tool list is not proof that no dynamic tools may exist.
            # Required fields are explicit; catalog absence alone is not.
            safe_guard = source_safe_guard(guard)
            l4_safe, d4_safe = card_decisions(
                base, grounded, s4, v4.refute_card, structural_guard=safe_guard)
            row.update({"v31_label": l3, "v31_verdicts": d3,
                        "v4_label": l4, "v4_verdicts": d4,
                        "v4_safe_label": l4_safe, "v4_safe_verdicts": d4_safe,
                        "structural_guard": guard,
                        "source_safe_guard": safe_guard})
            row["new_label"] = l4_safe
        output["per_case"].append(row)
    path = run_dir / "refute.json"
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"refuted {sum(r['pgjudge'] == 1 and r['new_label'] == 0 for r in output['per_case'])} alarms")


def tq_stage(run_dir: Path) -> None:
    manifest, _ = frozen(run_dir)
    path = run_dir / "refute.json"
    if not path.exists():
        raise FileNotFoundError(path)
    if json.loads(path.read_text(encoding="utf-8"))["input_sha256"] != manifest["cases_sha256"]:
        raise ValueError("refute input hash mismatch")
    import subprocess
    command = [sys.executable, str(REPO / "experiments/searh_23/tq_questions.py"),
               "--records", str(run_dir / "pgjudge/pgjudge/records.jsonl"),
               "--cards", str(run_dir / "pgjudge/extract/cards.jsonl"),
               "--cases", manifest["cases"], "--v31", str(path),
               "--out", str(run_dir), "--tag", "_fast_followup", "--no-gold"]
    subprocess.run(command, check=True)


def read_gold(path: Path) -> dict[str, int]:
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
    else:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            raw = {row["id"]: row["label"] for row in csv.DictReader(handle)}
    gold = {cid: int(value) for cid, value in raw.items()}
    if any(value not in (0, 1) for value in gold.values()):
        raise ValueError("gold labels must be 0 or 1")
    return gold


def score_stage(run_dir: Path, gold_path: Path, allow_partial: bool = False,
                rubric_path: Path | None = None) -> None:
    manifest, cases = frozen(run_dir)
    seal_path = run_dir / "prediction_seal.json"
    if seal_path.exists() or (run_dir / "score.json").exists():
        raise FileExistsError("score/seal already exists; use a fresh run directory")
    files = [run_dir / name for name in
             ("local.jsonl", "pgjudge/extract/cards.jsonl",
              "pgjudge/pgjudge/records.jsonl", "refute.json",
              "tq_questions_fast_followup.json")]
    witness_path = run_dir / "witnesses.json"
    if witness_path.exists():
        witness_data = json.loads(witness_path.read_text(encoding="utf-8"))
        if witness_data.get("input_sha256") != manifest["cases_sha256"] or \
                [r.get("id") for r in witness_data.get("per_case", [])] != manifest["ids"]:
            raise RuntimeError("witness coverage or input hash mismatch")
        files.append(witness_path)
    e2e_paths = {mode: run_dir / f"e2e_{mode}.jsonl" for mode in ("R1", "R2")}
    e2e_rows = {}
    for mode, path in e2e_paths.items():
        if not path.exists():
            continue
        rows = read_jsonl(path, require_ok=True)
        if not allow_partial and set(rows) != set(manifest["ids"]):
            raise RuntimeError(f"E2E {mode} coverage incomplete")
        for case in cases:
            row = rows.get(case["id"])
            if row is None:
                continue
            expected_hash = hashlib.sha256(
                (case["prompt"] + "\0" + case["response"]).encode()).hexdigest()
            if row.get("input_sha256") != expected_hash or \
                    row.get("cases_sha256") != manifest["cases_sha256"] or \
                    row.get("source_commit") != \
                    "300dc2edd20e631928b9997a8f581ab8659a75b2":
                raise RuntimeError(f"E2E {mode} input/source mismatch: {case['id']}")
        e2e_rows[mode] = rows
        files.append(path)
    proposal_rows = {}
    for family in ("feasibility", "completion"):
        path = run_dir / f"{family}.jsonl"
        if not path.exists():
            continue
        rows = read_jsonl(path, require_ok=True)
        if not allow_partial and set(rows) != set(manifest["ids"]):
            raise RuntimeError(f"{family} coverage incomplete")
        for case in cases:
            row = rows.get(case["id"])
            if row is None:
                continue
            expected_hash = hashlib.sha256(
                (case["prompt"] + "\0" + case["response"]).encode()).hexdigest()
            if row.get("input_sha256") != expected_hash:
                raise RuntimeError(f"{family} input hash mismatch: {case['id']}")
        proposal_rows[family] = rows
        files.append(path)
    if not allow_partial:
        absent = [str(path.relative_to(run_dir)) for path in files if not path.exists()]
        if absent:
            raise RuntimeError(f"prediction stages incomplete: {absent}")
        local_done = read_jsonl(files[0], require_ok=True)
        extract_done = read_jsonl(files[1], require_ok=True)
        judge_done = read_jsonl(files[2], require_ok=True)
        refute_done = {row["id"] for row in json.loads(
            files[3].read_text(encoding="utf-8"))["per_case"]}
        tq_done = {row["id"] for row in json.loads(
            files[4].read_text(encoding="utf-8"))["per_case"]}
        ids = set(manifest["ids"])
        if any(set(rows) != ids for rows in (local_done, extract_done, judge_done)) \
                or refute_done != ids:
            raise RuntimeError("prediction coverage incomplete")
        for case in cases:
            cid = case["id"]
            expected_hash = hashlib.sha256(
                (case["prompt"] + "\0" + case["response"]).encode("utf-8")).hexdigest()
            if local_done[cid].get("input_sha256") != expected_hash:
                raise RuntimeError(f"local input hash mismatch: {cid}")
        surviving = {row["id"] for row in json.loads(
            files[3].read_text(encoding="utf-8"))["per_case"]
            if row["new_label"] == 1 and row["pgjudge"] == 1}
        if tq_done != surviving:
            raise RuntimeError("TQ surviving-alarm coverage incomplete")
    sealed = {str(path.relative_to(run_dir)): file_hash(path) for path in files if path.exists()}
    seal_path.write_text(json.dumps({"version": MANIFEST_VERSION,
                                     "cases_sha256": manifest["cases_sha256"],
                                     "prediction_sha256": sealed}, indent=2), encoding="utf-8")
    gold = read_gold(gold_path)
    if set(gold) != set(manifest["ids"]):
        raise ValueError("gold ids do not match frozen case ids")
    families = {}
    if rubric_path is not None:
        rubric = json.loads(rubric_path.read_text(encoding="utf-8"))
        if not isinstance(rubric, list) or \
                {row["id"] for row in rubric} != set(manifest["ids"]) or \
                len(rubric) != len(manifest["ids"]) or \
                any(int(row["label"]) != gold[row["id"]] or
                    not isinstance(row.get("family"), str) for row in rubric):
            raise ValueError("rubric IDs or labels differ from gold")
        families = {row["id"]: row["family"] for row in rubric}
    local = read_jsonl(run_dir / "local.jsonl") if files[0].exists() else {}
    base = read_jsonl(run_dir / "pgjudge/pgjudge/records.jsonl",
                      require_ok=True) if files[2].exists() else {}
    refute = {r["id"]: r for r in json.loads(
        (run_dir / "refute.json").read_text(encoding="utf-8"))["per_case"]
              } if files[3].exists() else {}
    tq_rows = {r["id"]: r for r in json.loads(
        files[4].read_text(encoding="utf-8"))["per_case"]
               } if files[4].exists() else {}
    witness_rows = {r["id"]: r for r in witness_data["per_case"]} \
        if witness_path.exists() else {}
    arms: dict[str, dict[str, int | None]] = {}
    for case in cases:
        cid = case["id"]
        loc = local.get(cid, {})
        arms.setdefault("shape", {})[cid] = int(manifest["response_has_call"][cid])
        if loc:
            arms.setdefault("structural", {})[cid] = loc["structural"]["label"]
            if loc.get("status") == "OK":
                for budget in CONTEXT_BUDGETS:
                    key = str(budget)
                    arms.setdefault("c1_" + key, {})[cid] = loc["c1"][key]
                fc = loc.get("function_call", {}).get("label")
                c1 = loc["c1"]["12000"]
                if c1 == 1:
                    joined = 1
                elif c1 is None or (manifest["response_has_call"][cid] and fc is None):
                    joined = None
                else:
                    joined = int(fc == 1)
                arms.setdefault("c1_12000_plus_function_call", {})[cid] = joined
                arms.setdefault("function_call_eligible", {})[cid] = fc
        if cid in base:
            arms.setdefault("pgjudge", {})[cid] = int(base[cid]["label"])
        for mode, rows in e2e_rows.items():
            if cid in rows:
                arms.setdefault("e2e_" + mode.lower(), {})[cid] = rows[cid]["label"]
        if cid in proposal_rows.get("feasibility", {}):
            arms.setdefault("feasibility_proposal", {})[cid] = int(
                proposal_rows["feasibility"][cid]["verdict"] == "CANDIDATE")
        if cid in proposal_rows.get("completion", {}):
            arms.setdefault("completion_proposal", {})[cid] = int(
                proposal_rows["completion"][cid]["verdict"] ==
                "UNSUPPORTED_COMPLETION_CANDIDATE")
        if cid in refute:
            for name in ("v31", "v4", "v4_safe"):
                arms.setdefault(name, {})[cid] = refute[cid].get(name + "_label", refute[cid]["pgjudge"])
            if files[4].exists():
                arms.setdefault("tq", {})[cid] = (
                    tq_rows[cid]["new_label"] if cid in tq_rows else
                    refute[cid]["new_label"])
    # A refutation layer may also be used as a veto on C1 alarms. This paired
    # arm is diagnostic only until its TP cost is measured on new inputs.
    c1_predictions = arms.get("c1_12000", {})
    for partner in ("pgjudge", "v4_safe", "tq"):
        partner_predictions = arms.get(partner)
        if not c1_predictions or partner_predictions is None:
            continue
        joined = arms.setdefault("c1_12000_and_" + partner, {})
        for cid in manifest["ids"]:
            left, right = c1_predictions.get(cid), partner_predictions.get(cid)
            if left == 0 or right == 0:
                joined[cid] = 0
            elif left == 1 and right == 1:
                joined[cid] = 1
            else:
                joined[cid] = None
    for mode in ("r1", "r2"):
        other = arms.get("e2e_" + mode)
        if not other or not c1_predictions:
            continue
        joined = arms.setdefault("c1_12000_or_e2e_" + mode, {})
        for cid in manifest["ids"]:
            left, right = c1_predictions.get(cid), other.get(cid)
            joined[cid] = (1 if left == 1 or right == 1 else
                           0 if left == 0 and right == 0 else None)
    for family in ("feasibility", "completion"):
        proposal = arms.get(family + "_proposal")
        if proposal and c1_predictions:
            joined = arms.setdefault("c1_12000_or_" + family + "_proposal", {})
            for cid in manifest["ids"]:
                left, right = c1_predictions.get(cid), proposal.get(cid)
                joined[cid] = (1 if left == 1 or right == 1 else
                               0 if left == 0 and right == 0 else None)
    scores = {}
    for arm, predictions in arms.items():
        covered = [cid for cid in manifest["ids"] if predictions.get(cid) in (0, 1)]
        tp = sum(predictions[cid] == 1 and gold[cid] == 1 for cid in covered)
        fp = sum(predictions[cid] == 1 and gold[cid] == 0 for cid in covered)
        fn = sum(predictions[cid] == 0 and gold[cid] == 1 for cid in covered)
        tn = sum(predictions[cid] == 0 and gold[cid] == 0 for cid in covered)
        complete = len(covered) == len(manifest["ids"])
        scores[arm] = {"covered": len(covered), "total": len(manifest["ids"]),
                       "TP": tp, "FP": fp, "FN": fn, "TN": tn,
                       "F1": (round(2 * tp / (2 * tp + fp + fn), 4)
                              if complete and 2 * tp + fp + fn else None),
                       "missing": [cid for cid in manifest["ids"] if cid not in covered],
                       "by_shape": {
                           str(bit): {
                               "TP": sum(predictions[cid] == 1 and gold[cid] == 1
                                         for cid in covered if manifest["response_has_call"][cid] == bit),
                               "FP": sum(predictions[cid] == 1 and gold[cid] == 0
                                         for cid in covered if manifest["response_has_call"][cid] == bit),
                               "FN": sum(predictions[cid] == 0 and gold[cid] == 1
                                         for cid in covered if manifest["response_has_call"][cid] == bit),
                               "TN": sum(predictions[cid] == 0 and gold[cid] == 0
                                         for cid in covered if manifest["response_has_call"][cid] == bit)}
                           for bit in (False, True)}}
    comparisons = {}
    for before, after in (("pgjudge", "v31"), ("pgjudge", "v4"),
                          ("pgjudge", "v4_safe"), ("v4_safe", "tq"),
                          ("c1_12000", "c1_12000_plus_function_call"),
                          ("c1_12000", "c1_24000"),
                          ("c1_12000", "c1_60000"),
                          ("c1_12000", "c1_12000_and_pgjudge"),
                          ("c1_12000", "c1_12000_and_v4_safe"),
                          ("c1_12000", "c1_12000_and_tq")):
        if before not in arms or after not in arms:
            continue
        common = [cid for cid in manifest["ids"]
                  if arms[before].get(cid) in (0, 1)
                  and arms[after].get(cid) in (0, 1)]
        removed = [cid for cid in common
                   if arms[before][cid] == 1 and arms[after][cid] == 0]
        added = [cid for cid in common
                 if arms[before][cid] == 0 and arms[after][cid] == 1]
        comparisons[f"{before} -> {after}"] = {
            "paired_covered": len(common), "total": len(manifest["ids"]),
            "tp_gained": [cid for cid in added if gold[cid] == 1],
            "tp_lost": [cid for cid in removed if gold[cid] == 1],
            "fp_removed": [cid for cid in removed if gold[cid] == 0],
            "fp_added": [cid for cid in added if gold[cid] == 0]}
    for after in ("e2e_r1", "e2e_r2", "c1_12000_or_e2e_r1",
                  "c1_12000_or_e2e_r2", "c1_12000_or_feasibility_proposal",
                  "c1_12000_or_completion_proposal"):
        before = "c1_12000"
        if before not in arms or after not in arms:
            continue
        common = [cid for cid in manifest["ids"]
                  if arms[before].get(cid) in (0, 1) and arms[after].get(cid) in (0, 1)]
        removed = [cid for cid in common
                   if arms[before][cid] == 1 and arms[after][cid] == 0]
        added = [cid for cid in common
                 if arms[before][cid] == 0 and arms[after][cid] == 1]
        comparisons[f"{before} -> {after}"] = {
            "paired_covered": len(common), "total": len(manifest["ids"]),
            "tp_gained": [cid for cid in added if gold[cid] == 1],
            "tp_lost": [cid for cid in removed if gold[cid] == 1],
            "fp_removed": [cid for cid in removed if gold[cid] == 0],
            "fp_added": [cid for cid in added if gold[cid] == 0]}
    opportunity = {}
    if witness_rows:
        for name, predicate in (
                ("opaque_arg_without_exact_source", lambda r: any(
                    arg["opaque_field"] and arg["status"] == "UNKNOWN_NO_EXACT_SOURCE"
                    for target in r["arguments"] for arg in target["args"])),
                ("exact_failed_replay", lambda r: bool(r["repeated_failed_calls"])),
                ("text_claim_hint", lambda r: bool(r["claim_hints"]))):
            ids = [cid for cid in manifest["ids"] if predicate(witness_rows[cid])]
            opportunity[name] = {"ids": ids, "count": len(ids),
                                  "positive": sum(gold[cid] == 1 for cid in ids),
                                  "negative": sum(gold[cid] == 0 for cid in ids)}
    family_scores = {}
    if families:
        for family in sorted(set(families.values())):
            ids = [cid for cid in manifest["ids"] if families[cid] == family]
            family_scores[family] = {}
            for arm, predictions in arms.items():
                covered = [cid for cid in ids if predictions.get(cid) in (0, 1)]
                family_scores[family][arm] = {
                    "covered": len(covered), "total": len(ids),
                    "TP": sum(predictions[cid] == 1 and gold[cid] == 1 for cid in covered),
                    "FP": sum(predictions[cid] == 1 and gold[cid] == 0 for cid in covered),
                    "FN": sum(predictions[cid] == 0 and gold[cid] == 1 for cid in covered),
                    "TN": sum(predictions[cid] == 0 and gold[cid] == 0 for cid in covered)}
    result = {"version": MANIFEST_VERSION, "gold_sha256": file_hash(gold_path),
              "rubric_sha256": file_hash(rubric_path) if rubric_path else None,
              "prediction_seal": file_hash(seal_path), "scores": scores,
              "comparisons": comparisons, "witness_opportunities": opportunity,
              "by_family": family_scores,
              "per_case": [{"id": cid, "gold": gold[cid],
                            "shape_call": manifest["response_has_call"][cid],
                            "predictions": {name: rows.get(cid) for name, rows in arms.items()}}
                           for cid in manifest["ids"]]}
    (run_dir / "score.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    print(json.dumps({"scores": scores, "comparisons": comparisons},
                     ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="stage", required=True)
    p = subs.add_parser("prepare")
    p.add_argument("--cases", type=Path, required=True)
    p.add_argument("--run-dir", type=Path, required=True)
    for stage in ("local", "witness", "feasibility", "completion",
                  "pgjudge", "refute", "tq", "score"):
        subs.add_parser(stage).add_argument("--run-dir", type=Path, required=True)
    subs.choices["local"].add_argument("--model-path", type=Path,
                                        default=Path("/mnt/data/guardian/models/granite-guardian-3.3-8b-b3421eda"))
    subs.choices["local"].add_argument("--skip-model", action="store_true")
    subs.choices["score"].add_argument("--gold", type=Path, required=True)
    subs.choices["score"].add_argument("--rubric", type=Path)
    subs.choices["score"].add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare(args.cases, args.run_dir)
    elif args.stage == "local":
        local_stage(args.run_dir, args.model_path, args.skip_model)
    elif args.stage == "witness":
        witness_stage(args.run_dir)
    elif args.stage == "feasibility":
        feasibility_stage(args.run_dir)
    elif args.stage == "completion":
        completion_stage(args.run_dir)
    elif args.stage == "pgjudge":
        pgjudge_stage(args.run_dir)
    elif args.stage == "refute":
        refute_stage(args.run_dir)
    elif args.stage == "tq":
        tq_stage(args.run_dir)
    elif args.stage == "score":
        score_stage(args.run_dir, args.gold, args.allow_partial, args.rubric)


if __name__ == "__main__":
    main()
