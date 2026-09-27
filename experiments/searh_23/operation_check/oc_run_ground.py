"""Arms E/F/G: event-to-tool grounding with embedding, cross-encoder reranker and NLI.

Grounds event spans against the tool catalog using DESCRIPTION + SCHEMA only
(tool names are deliberately NOT rendered, so these arms are name-blind by
construction; rename robustness for them measures entity-code effects only).

Inputs: suite + component_inputs (gold spans, labels-free) + optionally the
B-dependency arm's candidate spans (for the hybrid arm H).

Arm G also probes each tool's nature with four GENERIC NLI hypotheses
(no domain words): mutation / verification / reading / communication.

Frozen pair-label decision rule for G (fixed before any results):
  label = argmax entailment over 4 templates
  max entailment >= 0.50 -> that label
  0.35 <= max < 0.50     -> UNKNOWN
  < 0.35                 -> UNRELATED
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from oc_common import load_suite, load_component_inputs, out_dir, write_usage

import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer
from sentence_transformers import SentenceTransformer

LABELS = ["REALIZES_OPERATION", "CHECKS_PRECONDITION", "OBSERVES_STATE", "COMMUNICATES"]


def render_tool(tool) -> str:
    inp = ", ".join(f"{k}: {v}" for k, v in tool.get("input", {}).items()) or "none"
    outp = ", ".join(f"{k}: {v}" for k, v in tool.get("output", {}).items()) or "none"
    return f"{tool['description']} Input parameters: {inp}. Output: {outp}."


def pair_hypotheses(span: str) -> dict[str, str]:
    return {
        "REALIZES_OPERATION":
            f'Executing this tool performs the action described as: "{span}".',
        "CHECKS_PRECONDITION":
            f'Executing this tool verifies whether the state described as: "{span}" holds.',
        "OBSERVES_STATE":
            f'Executing this tool observes or reads the state described as: "{span}".',
        "COMMUNICATES":
            f'Executing this tool sends a communication concerning: "{span}".',
    }


TOOL_TYPE_HYPOTHESES = {
    "mutate": "Executing this tool changes business records or state.",
    "verify": "Executing this tool verifies whether a required condition holds.",
    "read": "Executing this tool reads or observes state without changing it.",
    "message": "Executing this tool sends a message or notification.",
}


def decide_nli_label(probs: dict[str, float]) -> str:
    best_label = max(probs, key=probs.get)
    best = probs[best_label]
    if best >= 0.50:
        return best_label
    if best >= 0.35:
        return "UNKNOWN"
    return "UNRELATED"


class Grounders:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.enc = SentenceTransformer("BAAI/bge-base-en-v1.5", device=self.device)
        self.rtok = AutoTokenizer.from_pretrained("BAAI/bge-reranker-base")
        self.rer = AutoModelForSequenceClassification.from_pretrained(
            "BAAI/bge-reranker-base").to(self.device).eval()
        self.ntok = AutoTokenizer.from_pretrained("cross-encoder/nli-deberta-v3-base")
        self.nli = AutoModelForSequenceClassification.from_pretrained(
            "cross-encoder/nli-deberta-v3-base").to(self.device).eval()
        # label order from config: {0: contradiction, 1: entailment, 2: neutral}
        self.entail_idx = [k for k, v in self.nli.config.id2label.items()
                           if v == "entailment"][0]

    def embed_rank(self, span: str, renderings: dict[str, str]) -> list[list]:
        names = list(renderings)
        vecs = self.enc.encode([span] + [renderings[n] for n in names],
                               normalize_embeddings=True)
        sims = (vecs[1:] @ vecs[0]).tolist()
        pairs = sorted(zip(names, sims), key=lambda x: -x[1])
        return [[n, round(s, 4)] for n, s in pairs]

    def rerank_rank(self, span: str, renderings: dict[str, str]) -> list[list]:
        names = list(renderings)
        with torch.no_grad():
            batch = self.rtok([span] * len(names), [renderings[n] for n in names],
                              padding=True, truncation=True, max_length=192,
                              return_tensors="pt").to(self.device)
            scores = self.rer(**batch).logits.view(-1).float().cpu().tolist()
        pairs = sorted(zip(names, scores), key=lambda x: -x[1])
        return [[n, round(s, 3)] for n, s in pairs]

    def nli_probs(self, premises: list[str], hypotheses: list[str]) -> list[dict[str, float]]:
        with torch.no_grad():
            batch = self.ntok(premises, hypotheses, padding=True, truncation=True,
                              max_length=192, return_tensors="pt").to(self.device)
            logits = self.nli(**batch).logits
            probs = torch.softmax(logits, -1).cpu().tolist()
        out = []
        for p in probs:
            out.append({"entailment": p[self.entail_idx],
                        "contradiction": p[0] if self.entail_idx != 0 else p[1],
                        "neutral": p[2] if self.entail_idx != 2 else p[1]})
        return out

    def nli_for_span(self, span: str, renderings: dict[str, str]) -> dict[str, dict]:
        names = list(renderings)
        hyps = pair_hypotheses(span)
        premises, hypotheses = [], []
        for n in names:
            for label in LABELS:
                premises.append(renderings[n])
                hypotheses.append(hyps[label])
        probs = self.nli_probs(premises, hypotheses)
        result = {}
        for i, n in enumerate(names):
            per = {label: probs[i * len(LABELS) + j]["entailment"]
                   for j, label in enumerate(LABELS)}
            per["label"] = decide_nli_label(per)
            per["max_e"] = round(max(per[l] for l in LABELS), 4)
            result[n] = {k: (round(v, 4) if isinstance(v, float) else v)
                         for k, v in per.items()}
        return result

    def tool_type_probe(self, renderings: dict[str, str]) -> dict[str, dict]:
        names = list(renderings)
        premises, hypotheses = [], []
        for n in names:
            for tlabel, hyp in TOOL_TYPE_HYPOTHESES.items():
                premises.append(renderings[n])
                hypotheses.append(hyp)
        probs = self.nli_probs(premises, hypotheses)
        result = {}
        for i, n in enumerate(names):
            per = {tlabel: probs[i * 4 + j]["entailment"]
                   for j, tlabel in enumerate(TOOL_TYPE_HYPOTHESES)}
            result[n] = {k: round(v, 4) for k, v in per.items()}
            result[n]["top"] = max(per, key=per.get)
        return result


def load_b_candidates(which: str) -> dict[str, list[dict]]:
    """Candidate spans produced by arm B for the hybrid arm (optional)."""
    d = Path(os.environ.get("OC_OUTPUTS", str(Path(__file__).parent / "outputs")))
    sub = "B_dependency" + suffix_for(which)
    path = d / sub
    if not path.is_dir():
        return {}
    out = {}
    for f in path.glob("*.json"):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if "case_id" in data:
            out[data["case_id"]] = data.get("events", [])
    return out


def main():
    which = os.environ.get("OC_SUITE", "original")
    arm = os.environ.get("OC_ARM_DIR", "EFG_grounding")
    suite = load_suite(which)
    comp = load_component_inputs(which)
    b_cand = load_b_candidates(which)
    g = Grounders()
    t0 = time.time()
    outdir = out_dir(arm + suffix_for(which))
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            continue
        renderings = {t["name"]: render_tool(t) for t in case["tools"]}
        result = {
            "case_id": case["case_id"],
            "renderings_without_names": renderings,
            "tool_type_probe": g.tool_type_probe(renderings),
            "gold_span_grounding": [],
            "b_candidate_grounding": [],
        }
        for span in comp.get(case["case_id"], []):
            result["gold_span_grounding"].append({
                "span": span,
                "embed_rank": g.embed_rank(span, renderings),
                "rerank_rank": g.rerank_rank(span, renderings),
                "nli": g.nli_for_span(span, renderings),
            })
        for cand in b_cand.get(case["case_id"], []):
            span = cand.get("span")
            if not span:
                continue
            result["b_candidate_grounding"].append({
                "span": span,
                "b_features": {k: cand.get(k) for k in
                               ("dep", "mark", "deontic", "neg", "passive",
                                "imperative", "root", "role_hypothesis", "even")},
                "embed_rank": g.embed_rank(span, renderings),
                "rerank_rank": g.rerank_rank(span, renderings),
                "nli": g.nli_for_span(span, renderings),
            })
        path.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    write_usage(arm + suffix_for(which),
                {"wall_seconds": round(time.time() - t0, 1), "suite": which,
                 "models": ["BAAI/bge-base-en-v1.5", "BAAI/bge-reranker-base",
                            "cross-encoder/nli-deberta-v3-base"],
                 "device": g.device})
    print("EFG done", which)


if __name__ == "__main__":
    main()
