#!/usr/bin/env python3
"""New holdout dataset builder (directive §5).

Design:
  * families/  — one spec per policy family: a FRESH domain (disjoint from
    all previous suites: public46 domains airline/banking/retail/telecom,
    V2 families bakery/ferry/museum/orchard/cinema/quarry/apiary/transit/
    archive, hotel, service-desk, AgentHallu frameworks), a multi-sentence
    policy with conditions/exceptions, a tool catalog with argument
    schemas, and 5 authored case variants (mix of ERROR and hard NO_ERROR)
  * cases/     — rendered official-format cases (id, prompt, response) +
    independent gold: label, error_type or admissibility_reason, grounds
    (verbatim policy quotes / event refs), domain_id, policy_family_id,
    parent_case_id, source, labeling_verification
  * rename/paraphrase/mutation variants stay INSIDE the same family and
    the same split (rename never creates an independent domain)
  * manifest.json freezes splits + sha256 before any test inference

Gold is authored from the policy text DIRECTLY (independent spec), never
produced by the evaluated Guardian runtime; LLM consistency checks, if
run, are recorded as LLM checks.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATASET = HERE / "dataset"
FAMILIES = DATASET / "families"
CASES = DATASET / "cases"

# domains already used by previous suites (rename/disjointness rule)
USED_DOMAINS = {
    "airline", "banking", "retail", "telecom",
    "bakery", "ferry", "museum", "orchard", "cinema", "quarry", "apiary",
    "transit", "archive", "lab", "hotel", "service_desk", "depot",
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------ rendering

def render_catalog(tools: list) -> str:
    """tools: [{name, description, params: [{name, type, required,
    enum, desc, subfields}]}] -> official [AVAILABLE TOOLS] text."""
    out = ["[AVAILABLE TOOLS]"]
    for t in tools:
        out.append(f"- {t['name']} — {t['description']}")
        for p in t.get("params", []):
            req = "!" if p.get("required") else ""
            enum = (f" [enum: {'|'.join(p['enum'])}]"
                    if p.get("enum") else "")
            desc = f" — {p['desc']}" if p.get("desc") else ""
            out.append(f"    {p['name']}: {p.get('type', 'string')}{req}"
                       f"{enum}{desc}")
            for sf in p.get("subfields", []):
                sreq = "!" if sf.get("required") else ""
                out.append(f"        · {sf['name']}: "
                           f"{sf.get('type', 'string')}{sreq}"
                           + (f" — {sf['desc']}" if sf.get("desc") else ""))
    return "\n".join(out)


def render_prompt(policy: str, catalog_text: str, turns: list) -> str:
    """turns: [{role: user|assistant, text, calls: [{name, args}|],
    results: [{name, payload}]}] -> official prompt format."""
    parts = [f"⟦SYSTEM⟧\n{policy}\n\n{catalog_text}"]
    for t in turns:
        if t["role"] == "user":
            parts.append(f"⟦USER⟧\n{t['text']}")
        else:
            body = t.get("text", "")
            lines = [body] if body else []
            for call in t.get("calls", []):
                args_json = json.dumps(call["args"], ensure_ascii=False)
                lines.append(f"\t→ TOOL_CALL {call['name']}: {args_json}")
            for res in t.get("results", []):
                payload_json = json.dumps(res["payload"],
                                          ensure_ascii=False)
                lines.append(f"\t← TOOL_RESPONSE {res['name']}: "
                             f"{payload_json}")
            parts.append("⟦ASSISTANT⟧\n" + "\n".join(lines))
    return "\n\n".join(parts) + "\n\n"


def render_response(text: str, calls: list = None, results: list = None) -> str:
    lines = [text] if text else []
    for call in calls or []:
        args_json = json.dumps(call["args"], ensure_ascii=False)
        lines.append(f"\t→ TOOL_CALL {call['name']}: {args_json}")
    for res in results or []:
        payload_json = json.dumps(res["payload"], ensure_ascii=False)
        lines.append(f"\t← TOOL_RESPONSE {res['name']}: {payload_json}")
    return "\n".join(lines)


# ------------------------------------------------------------ family spec

FAMILY_SPEC_KEYS = {
    "family_id", "domain_id", "split", "policy", "catalog", "cases",
    "notes",
}
CASE_SPEC_KEYS = {
    "case_id", "kind", "text", "calls", "results", "label",
    "error_type", "admissibility_reason", "grounds", "history",
    "parent_case_id", "rename_of",
}


def validate_family(spec: dict) -> list:
    errs = []
    missing = FAMILY_SPEC_KEYS - set(spec)
    if missing:
        errs.append(f"family missing keys: {sorted(missing)}")
    if spec.get("domain_id", "") in USED_DOMAINS:
        errs.append(f"domain '{spec['domain_id']}' already used by a "
                    f"previous suite (freshness rule)")
    if not spec.get("policy"):
        errs.append("empty policy")
    if not spec.get("catalog"):
        errs.append("empty catalog")
    cases = spec.get("cases", [])
    if len(cases) < 5:
        errs.append(f"family needs >=5 cases, got {len(cases)}")
    n_pos = sum(1 for c in cases if c.get("label") == 1)
    if n_pos == 0 or n_pos == len(cases):
        errs.append("family must mix ERROR and NO_ERROR cases")
    for c in cases:
        cmiss = CASE_SPEC_KEYS - set(c)
        cmiss.discard("rename_of")
        cmiss.discard("parent_case_id")
        if cmiss:
            errs.append(f"case {c.get('case_id')} missing keys "
                        f"{sorted(cmiss)}")
        if c.get("label") == 1 and not c.get("error_type"):
            errs.append(f"case {c.get('case_id')}: ERROR needs error_type")
        if c.get("label") == 0 and not c.get("admissibility_reason"):
            errs.append(f"case {c.get('case_id')}: NO_ERROR needs "
                        f"admissibility_reason")
        if not c.get("grounds"):
            errs.append(f"case {c.get('case_id')}: no grounds")
        for g in c.get("grounds", []):
            q = g.get("quote", "")
            if g.get("kind") == "policy_quote" and q and q not in spec.get("policy", ""):
                errs.append(f"case {c.get('case_id')}: policy_quote not "
                            f"verbatim in policy: {q[:60]!r}")
    # rename cases must stay in-family
    for c in cases:
        if c.get("rename_of") and c.get("rename_of") not in {
                x.get("case_id") for x in cases}:
            errs.append(f"case {c.get('case_id')}: rename_of target not "
                        f"in same family")
    return errs


# ------------------------------------------------------------ build

def build(family_files: list, outdir: Path = CASES) -> dict:
    FAMILIES.mkdir(parents=True, exist_ok=True)
    outdir.mkdir(parents=True, exist_ok=True)
    all_cases, index = [], []
    for ff in family_files:
        spec = json.loads(Path(ff).read_text())
        errs = validate_family(spec)
        if errs:
            raise ValueError(f"{ff} invalid:\n  " + "\n  ".join(errs))
        catalog_text = render_catalog(spec["catalog"])
        for c in spec["cases"]:
            prompt = render_prompt(spec["policy"], catalog_text,
                                   c.get("history", []))
            response = render_response(c.get("text", ""),
                                       c.get("calls", []),
                                       c.get("results", []))
            case = {
                "id": f"{spec['family_id']}::{c['case_id']}",
                "domain_id": spec["domain_id"],
                "policy_family_id": spec["family_id"],
                "split": spec["split"],
                "parent_case_id": c.get("parent_case_id"),
                "rename_of": c.get("rename_of"),
                "source": "authored_synthetic_holdout_v1",
                "input": {"prompt": prompt, "response": response},
                "target_label": c["label"],
                "error_type": c.get("error_type"),
                "admissibility_reason": c.get("admissibility_reason"),
                "grounds": c["grounds"],
                "labeling_verification": {
                    "method": "independent_manual_spec",
                    "runtime_involved": None,
                    "note": ("gold authored directly from the policy text "
                             "before any inference; not produced by the "
                             "evaluated Guardian runtime")},
            }
            path = outdir / f"{case['id'].replace('::', '__')}.json"
            path.write_text(json.dumps(case, ensure_ascii=False, indent=2))
            all_cases.append(case)
            index.append({"id": case["id"],
                          "family": spec["family_id"],
                          "split": spec["split"],
                          "label": case["target_label"],
                          "path": str(path.relative_to(HERE))})
    return {"cases": all_cases, "index": index}


def freeze(outdir: Path = DATASET) -> dict:
    """Freeze manifest: splits + sha256 of every case file."""
    case_files = sorted((outdir / "cases").glob("*.json"))
    fam_files = sorted((outdir / "families").glob("*.json"))
    entries = []
    for p in case_files:
        data = json.loads(p.read_text())
        entries.append({
            "id": data["id"], "family": data["policy_family_id"],
            "domain": data["domain_id"], "split": data["split"],
            "label": data["target_label"],
            "sha256": sha256_text(p.read_text()),
            "path": str(p.relative_to(outdir))})
    fams = {}
    for p in fam_files:
        spec = json.loads(p.read_text())
        fams[spec["family_id"]] = {
            "domain": spec["domain_id"], "split": spec["split"],
            "sha256": sha256_text(p.read_text()),
            "n_cases": len(spec["cases"])}
    splits = {}
    for e in entries:
        splits.setdefault(e["split"], []).append(e["id"])
    manifest = {
        "frozen_at": time.time(),
        "frozen_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_cases": len(entries),
        "n_families": len(fams),
        "splits": {k: sorted(v) for k, v in splits.items()},
        "families": fams,
        "cases": entries,
        "rules": [
            "rename/paraphrase/mutation variants stay inside the same "
            "family and the same split",
            "dev split usable for prompt/threshold selection; sealed split "
            "opened only after predictions are recorded",
            "gold authored from policy text directly (independent spec); "
            "LLM checks must be labeled as LLM checks",
        ],
    }
    (outdir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def to_official_csv(manifest: dict, split: str, out_csv: Path) -> int:
    """id,prompt,response CSV for a split (label NEVER included)."""
    import csv
    rows = []
    for e in manifest["cases"]:
        if e["split"] != split:
            continue
        data = json.loads((DATASET / e["path"]).read_text())
        rows.append({"id": data["id"],
                     "prompt": data["input"]["prompt"],
                     "response": data["input"]["response"]})
    csv.field_size_limit(10 ** 9)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "prompt", "response"])
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def gold_csv(manifest: dict, split: str, out_csv: Path) -> int:
    import csv
    rows = [{"id": e["id"], "label": e["label"]}
            for e in manifest["cases"] if e["split"] == split]
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "label"])
        w.writeheader()
        w.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "freeze":
        m = freeze()
        print(json.dumps({k: m[k] for k in
                          ("n_cases", "n_families", "splits")}, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "csv":
        m = json.loads((DATASET / "manifest.json").read_text())
        split = sys.argv[2]
        n = to_official_csv(m, split, DATASET / f"{split}_input.csv")
        g = gold_csv(m, split, DATASET / f"{split}_gold.csv")
        print(f"{split}: {n} cases -> {split}_input.csv / {split}_gold.csv")
    else:
        print(__doc__)
