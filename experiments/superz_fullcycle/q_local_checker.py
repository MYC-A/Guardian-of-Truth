#!/usr/bin/env python3
"""Q answer stage — LOCAL independent checkers (granite guardian + NLI DeBERTa).

For each divergence between theory A (blockrun) and theory B (pollinations):
  1. Build two READING CLAIMS (natural-language statements of each reading).
  2. Granite Guardian 3.3-8B groundedness (validated E7 mechanism): is the claim
     supported by the policy document? -> yes/no + probability (first yes/no
     token logit softmax).
  3. NLI DeBERTa v3 base (local): entailment of claim given the policy fragment
     around the two anchored quotes (mechanically derived local context).
  4. Decision: A/B if exactly one reading is supported (granite primary; NLI
     recorded as cross-check; decisive requires granite decision and NLI not
     contradicting it).

No API quota; fully local; model families distinct from both theory builders.
Journal: outputs/superz_fullcycle/q_discriminate/answer/records.jsonl
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from p_precond import load_cases, policy_text  # noqa: E402

OUT_ROOT = REPO / "outputs" / "superz_fullcycle" / "q_discriminate"
GRANITE_PATH = "/mnt/data/guardian/models/granite-guardian-3.3-8b-b3421eda"
NLI_SNAP = glob.glob("/mnt/data/guardian/hf_cache/hub/models--cross-encoder--nli-deberta-v3-base/snapshots/*/")[0]
FRAGMENT_PAD = 400

MODALITY_VERB = {"FORBID": "is forbidden", "REQUIRE": "is required",
                 "PERMIT": "is permitted", "": "is not regulated"}


def render_claim(ftype: str, target: str, cond: str, value, is_a: bool) -> str:
    cond_clause = f" when {cond}" if cond else ""
    if ftype == "modality":
        verb = MODALITY_VERB.get(str(value or "").strip().upper(), "is regulated differently")
        return (f"According to the policy, the action '{target}'{cond_clause} {verb} "
                f"(exactly as stated).")
    if ftype == "condition":
        if value:
            return (f"According to the policy, the rule about '{target}' applies ONLY under "
                    f"this condition: {value}.")
        return (f"According to the policy, the rule about '{target}' applies unconditionally, "
                "with no condition restricting it.")
    if ftype == "exception":
        if value:
            return (f"According to the policy, there is an exception that removes the "
                    f"requirement on '{target}': {value}.")
        return (f"According to the policy, there is no exception that removes the requirement "
                f"on '{target}'.")
    # temporal
    if value:
        return (f"According to the policy, the temporal order for '{target}' is: {value}.")
    return (f"According to the policy, there is no temporal order requirement for '{target}'.")


def fragment_around(policy: str, span_a, span_b) -> str:
    spans = [s for s in (span_a, span_b) if s]
    if not spans:
        return policy[:3000]
    start = max(0, min(s[0] for s in spans) - FRAGMENT_PAD)
    end = min(len(policy), max(s[1] for s in spans) + FRAGMENT_PAD)
    return policy[start:end]


def done_keys(journal: Path) -> set:
    keys = set()
    if journal.is_file():
        with open(journal, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("status") == "OK":
                    keys.add(rec["key"])
    return keys


def normalise_token(t: str) -> str:
    return t.replace("Ġ", "").replace("▁", "").strip().lower()


def main() -> int:
    import torch
    from transformers import AutoModelForCausalLM, AutoModelForSequenceClassification, AutoTokenizer

    divs = [json.loads(l) for l in open(OUT_ROOT / "divergences.jsonl", encoding="utf-8")
            if l.strip()]
    cases = load_cases()
    out_dir = OUT_ROOT / "answer"
    out_dir.mkdir(parents=True, exist_ok=True)
    journal = out_dir / "records.jsonl"
    done = done_keys(journal)
    print(f"[q-checker] {len(divs)} divergences, {len(done)} done", flush=True)

    # --- load granite guardian ---
    t0 = __import__("time").time()
    gtok = AutoTokenizer.from_pretrained(GRANITE_PATH, local_files_only=True,
                                         trust_remote_code=False)
    gmodel = AutoModelForCausalLM.from_pretrained(
        GRANITE_PATH, local_files_only=True, trust_remote_code=False,
        torch_dtype=torch.float16, device_map="cuda")
    gmodel.eval()
    yes_ids = [tid for tok, tid in gtok.get_vocab().items()
               if normalise_token(tok) == "yes"]
    no_ids = [tid for tok, tid in gtok.get_vocab().items()
              if normalise_token(tok) == "no"]
    print(f"[q-checker] granite loaded in {__import__('time').time()-t0:.0f}s "
          f"(yes_ids={len(yes_ids)}, no_ids={len(no_ids)})", flush=True)

    # --- load NLI ---
    t1 = __import__("time").time()
    nli_tok = AutoTokenizer.from_pretrained(NLI_SNAP, local_files_only=True)
    nli_model = AutoModelForSequenceClassification.from_pretrained(
        NLI_SNAP, local_files_only=True, torch_dtype=torch.float16, device_map="cuda")
    nli_model.eval()
    # cross-encoder/nli-deberta-v3-base label order: [contradiction, entailment, neutral]
    nli_labels = list(nli_model.config.id2label.values())
    print(f"[q-checker] NLI loaded in {__import__('time').time()-t1:.0f}s, labels={nli_labels}",
          flush=True)

    def granite_grounding(policy: str, claim: str) -> dict:
        msgs = [{"role": "assistant", "content": claim}]
        chat = gtok.apply_chat_template(
            msgs, guardian_config={"criteria_id": "groundedness"},
            documents=[{"doc_id": "policy", "text": policy}],
            think=False, tokenize=False, add_generation_prompt=True)
        inputs = gtok(chat, add_special_tokens=False, return_tensors="pt").to("cuda")
        with torch.inference_mode():
            gen = gmodel.generate(**inputs, do_sample=False, max_new_tokens=20,
                                  return_dict_in_generate=True, output_scores=True,
                                  pad_token_id=gtok.eos_token_id)
        completion_ids = gen.sequences[0, inputs["input_ids"].shape[1]:]
        raw = gtok.decode(completion_ids, skip_special_tokens=True).strip()
        # first yes/no token logits
        score = None
        pos = None
        for i, tid in enumerate(completion_ids.tolist()):
            if tid in yes_ids or tid in no_ids:
                row = gen.scores[i][0]
                yes_logit = torch.logsumexp(row[yes_ids], dim=0)
                no_logit = torch.logsumexp(row[no_ids], dim=0)
                p_yes = float(torch.softmax(torch.stack((yes_logit, no_logit)), dim=0)[0])
                score = p_yes
                pos = i
                break
        yes = None if score is None else (score >= 0.5)
        return {"raw": raw[:60], "p_yes": None if score is None else round(score, 4),
                "yes": yes, "token_pos": pos}

    def nli_entail(premise: str, hypothesis: str) -> dict:
        enc = nli_tok(premise, hypothesis, return_tensors="pt", truncation=True,
                      max_length=512).to("cuda")
        with torch.inference_mode():
            logits = nli_model(**enc).logits[0]
        probs = torch.softmax(logits, dim=-1)
        idx = {label.lower(): i for i, label in enumerate(nli_labels)}
        ent = float(probs[idx.get("entailment", 1)])
        con = float(probs[idx.get("contradiction", 0)])
        neu = float(probs[idx.get("neutral", 2)])
        return {"entail": round(ent, 4), "contradict": round(con, 4),
                "neutral": round(neu, 4)}

    for i, d in enumerate(divs):
        key = f"div{i:04d}"
        if key in done:
            continue
        case = cases[d["case"]]
        policy = policy_text(case)
        # context fields for claims
        tgt = (d.get("target") or "the action")[:160]
        cond = d.get("condition") or ""
        claim_a = render_claim(d["type"], tgt, cond, d["value_a"], True)
        claim_b = render_claim(d["type"], tgt, cond, d["value_b"], False)
        # policy fragment for NLI (mechanical local context around both quotes)
        frag = fragment_around(policy, d.get("span_a"), d.get("span_b"))
        # local divergence-specific policy fragment from quote text is unknown here;
        # use the quotes themselves to locate spans
        try:
            ga = granite_grounding(policy, claim_a)
            gb = granite_grounding(policy, claim_b)
        except Exception as e:
            ga = gb = {"error": str(e)[:150]}
        try:
            na = nli_entail(frag, claim_a)
            nb = nli_entail(frag, claim_b)
        except Exception as e:
            na = nb = {"error": str(e)[:150]}

        choice, decisive, reason = "NEITHER", False, ""
        if ga.get("yes") is not None and gb.get("yes") is not None:
            if ga["yes"] and not gb["yes"]:
                choice = "A"
            elif gb["yes"] and not ga["yes"]:
                choice = "B"
        # NLI cross-check: decisive requires NLI entailment not to contradict granite
        if choice in ("A", "B") and "entail" in na and "entail" in nb:
            win_nli, lose_nli = (na, nb) if choice == "A" else (nb, na)
            if win_nli["entail"] + 0.1 >= lose_nli["entail"]:
                decisive = True
                reason = (f"granite: A={'yes' if ga['yes'] else 'no'} "
                          f"(p={ga['p_yes']}), B={'yes' if gb['yes'] else 'no'} "
                          f"(p={gb['p_yes']}); NLI ent A={na['entail']} B={nb['entail']}")
            else:
                reason = ("NLI contradicts granite decision (loser has higher entailment); "
                          "not decisive")
        elif choice in ("A", "B"):
            decisive = False
            reason = "NLI unavailable"
        else:
            reason = (f"granite inconclusive: A p={ga.get('p_yes')}, B p={gb.get('p_yes')}")

        rec = {"key": key, "case": d["case"], "type": d["type"],
               "value_a": d["value_a"], "value_b": d["value_b"],
               "rule_a_index": d["rule_a_index"], "rule_b_index": d["rule_b_index"],
               "claim_a": claim_a, "claim_b": claim_b,
               "granite": {"a": ga, "b": gb},
               "nli": {"a": na, "b": nb},
               "checker": "granite-guardian-3.3-8b-groundedness + nli-deberta-v3-crosscheck",
               "choice": choice, "decisive": decisive,
               "reason": reason[:400], "status": "OK"}
        with open(journal, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[q-checker] {key} {d['type']} -> {choice}"
              f"{' DECISIVE' if decisive else ''}", flush=True)
    print("[q-checker] DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
