"""W1 pipeline v3: deterministic-heavy H1 iteration 2.

Changes vs w1_pipeline.py (each pre-registered in STEP1_RESEARCH_LOG.md D1-v3):
  v1. verifier: any-form-inside-relation_text (extractor anchors = evidence only);
  v2. relation-text clause repair (expand to minimal covering span in sentence);
  v3. via_reference channel -> UNKNOWN-candidate passed to the judge;
  n1. member-form VARIANTS (original / article / predicate-only / subject-ext);
  n2. orphan-fragment drop (relation-less NP strictly inside another candidate);
  n3. artifact-subject taxonomy filter ('is a document', 'the log records X');
  b1. bnorm keep-override (indicative copula state clauses never dropped);
  b2. subject re-attachment for predicate-initial spans;
  p1. pair-proposal channels: CE band OR same-sentence OR entity-token bridge;
  v4. node_view passes type + arguments to extractor/judge;
  j1. judge sees the in-relation anchor form for each endpoint;
  j2. judge co-precondition rule strengthened.

Run:  python3 w1_pipe3.py <FRONTEND_ARM>     (LF_SUITE=main|f2)
Out:  outputs/W1_DOWN3_<ARM>/<case>.json
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
IE = HERE.parent / "event_ie_frontends_v1"
PL = HERE.parent / "policy_licensing_v1"
sys.path[:0] = [str(PL), str(IE)]
from pl_run_llm import SYSTEM, dir_user, cls_user  # noqa: E402
from pl_common import Mistral, render_tool  # noqa: E402
from lf_certificate import sanitize_quote, span_in  # noqa: E402

OUT = HERE / "outputs"
CE_BAND = 0.35
EVENTLIKE = {"EVENT", "EVENT_REFERENCE", "STATE_OR_FACET", "CHECK",
             "UNKNOWN"}
TYPE_TO_ROLE = {"EVENT": "OPERATION_EFFECT", "CHECK": "PRECONDITION_CHECK",
                "STATE_OR_FACET": "STATE_OBSERVATION",
                "EVENT_REFERENCE": "UNKNOWN", "UNKNOWN": "UNKNOWN"}

COPULA_START = re.compile(
    r"^(is|are|was|were|is\s+not|are\s+not|was\s+not|were\s+not)\b", re.I)
COPULA_ANY = re.compile(
    r"\b(is|are|was|were)\s+(not\s+)?[\w'-]+", re.I)
SUBJECT_STRIP = re.compile(
    r"^(only\s+if|only\s+when|if|when|while|unless|until|after|before|once|"
    r"provided\s+that|in\s+which\s+case|that|which|and|or|but|so|then)\s+",
    re.I)
ARTIFACT_HEAD = ("log|certificate|note|record|report|master|form|file|"
                 "reading|document")
TAXONOMY_PRED = re.compile(
    r"\b(is|are|was|were)\s+(a|an|the)?\s*"
    r"(document|log|record|report|note|file|form|mandatory|optional|"
    r"prohibited|required|forbidden)\b", re.I)
COMM_VERB = re.compile(
    r"\b(records|logs|documents|confirms|lists|states|certifies|indicates|"
    r"shows)\b", re.I)
ARTIFACT_SUBJ = re.compile(
    rf"^(?:[Tt]he\s+|[Aa]\s+|[Aa]n\s+)?[A-Za-z0-9'\- ]*?"
    rf"\b(?:{ARTIFACT_HEAD})\s+"
    rf"(?:is|are|was|were|records|logs|documents|confirms|lists|states|"
    rf"certifies|indicates|shows)\b", re.I)
STOP = {"the", "and", "or", "only", "after", "before", "when", "if",
        "unless", "until", "must", "may", "shall", "should", "with", "for",
        "from", "into", "upon", "during", "each", "every", "that", "which",
        "case", "where", "then", "this", "these", "those", "was", "were",
        "are", "is", "been", "being", "have", "has", "had", "not", "but",
        "his", "her", "its", "their", "any", "all", "both", "also", "more",
        "than", "less", "least", "most", "one", "two", "who", "what",
        "whose", "while", "since", "because", "so", "such", "own"}


def tokens_of(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z][a-z0-9'-]{2,}", text.lower())
            if t not in STOP}


def sent_span(policy: str, start: int) -> tuple[int, int]:
    """(begin, end) char span of the sentence containing offset start."""
    begin = policy.rfind(".", 0, start) + 1
    for punct in ("!", "?"):
        b2 = policy.rfind(punct, 0, start) + 1
        begin = max(begin, b2)
    end = len(policy)
    for punct in (".", "!", "?"):
        e2 = policy.find(punct, start)
        if e2 != -1:
            end = min(end, e2)
    return begin, min(end + 1, len(policy))


# ------------------------------------------------------------ E3 v3 prompts
E3_EXT_SYSTEM_V3 = """You extract proof certificates from a workplace policy. You must quote EXACT substrings of the policy, character by character (matching capitalization). Never paraphrase.
The relation_text must be the minimal COMPLETE clause that states the relation and must CONTAIN, inside itself, a representation of BOTH endpoints (directly or through references).
The a_in_relation / b_in_relation fields MUST be substrings INSIDE your relation_text: quote the representation that occurs inside the relation_text (any surface form of the endpoint counts).
Answer strictly as JSON with these fields:
{"a_anchor": "<exact substring of the POLICY where endpoint A is represented (any of its surface forms)" or "NO_ANCHOR",
 "b_anchor": "<exact substring of the POLICY where endpoint B is represented>" or "NO_ANCHOR",
 "a_in_relation": "<exact substring INSIDE the relation_text that represents endpoint A>" or "NO_ANCHOR",
 "b_in_relation": "<exact substring INSIDE the relation_text that represents endpoint B>" or "NO_ANCHOR",
 "a_via_reference": "<exact substring of a reference (e.g. 'this inspection') in the POLICY that points to endpoint A>" or null,
 "b_via_reference": "<exact substring of a reference in the POLICY that points to endpoint B>" or null,
 "relation_text": "<exact minimal complete clause of the policy stating the relation between endpoint A and endpoint B>" or "NO_RELATION",
 "direction": "A_TO_B" or "B_TO_A" or "UNKNOWN",
 "relation_type": "PRECONDITION" or "ORDER_BEFORE" or "ORDER_AFTER" or "STATE_GATE" or "RESPONSE" or "EXCEPTION" or "EVEN_IF" or "UNKNOWN"}
direction semantics: A_TO_B means A must happen first (A gates, precedes, enables or triggers B); B_TO_A means B must happen first.
IMPORTANT: a quote that merely asserts that BOTH A and B gate some third event (co-preconditions of the same operation) does NOT state a relation between A and B; use NO_RELATION in that case.
IMPORTANT: if A and B denote the SAME underlying action (one mention is a passive/nominalized/reference variant of the other, or a state describing the other), the pair is not a relation between two distinct actions; use NO_RELATION."""


def e3_ext_user_v3(policy: str, a: dict, b: dict) -> str:
    def render(x: dict, name: str) -> str:
        forms = [f for f in (x.get("all_forms") or
                             [x.get("source_span")]) if f][:8]
        args = "; ".join(f"{g['role']}=\"{g['span']}\""
                         for g in (x.get("arguments") or [])[:4])
        return (f"ENDPOINT {name} is represented by these surface forms "
                f"(any of them may appear in the policy):\n"
                + "\n".join(f'  - "{f}"' for f in forms)
                + f"\n  (proposed type: {x.get('type', 'UNKNOWN')})"
                + (f"\n  (arguments: {args})" if args else ""))

    return (f"POLICY:\n{policy}\n\n"
            + render(a, "A") + "\n" + render(b, "B") + "\n\n"
            "Task: build the proof certificate for the candidate relation "
            "A -> B. Quote exact substrings. The relation_text MUST contain "
            "representations of BOTH endpoints inside itself. If A or B is "
            "represented only through a reference, give that reference in "
            "the *_via_reference field. If the policy states no relation "
            "between these two endpoints, or they are the same action, use "
            "NO_RELATION.\nAnswer strictly as JSON.")


E3_JUDGE_SYSTEM_V3 = """You are a strict endpoint verifier. You see ONE quoted evidence text (an exact quote from a workplace policy), descriptions of two candidate endpoints A and B, and where each endpoint is represented inside the evidence. An endpoint may be represented in the evidence DIRECTLY, through a REFERENCE (a noun phrase like 'this inspection', a result artifact like 'the swr reading'), or through a STATE facet of the endpoint (e.g. 'the tower is drained' for the draining action).
Answer five SEPARATE questions strictly as JSON:
{"q1_where_is_a": "<exact substring of the evidence representing endpoint A, directly, via a reference, or via a state facet>" or "NONE",
 "q2_where_is_b": "<exact substring of the evidence representing endpoint B>" or "NONE",
 "q3_relation_between_these_two": "YES" or "NO" or "UNKNOWN",
 "q4_direction": "A_TO_B" or "B_TO_A" or "UNKNOWN",
 "q5_relation_type": "PRECONDITION" or "ORDER_BEFORE" or "ORDER_AFTER" or "STATE_GATE" or "RESPONSE" or "EXCEPTION" or "EVEN_IF" or "SEMANTIC_LINK" or "UNKNOWN"}
IMPORTANT for q3: YES only if the evidence asserts a DIRECT relation between A and B specifically (one gates, precedes, enables, triggers or excepts the other). The following do NOT count:
- coordinated alternatives (A or B);
- mere co-occurrence of both in one sentence;
- co-preconditions: if A and B are coordinated clauses ('... only after A and B', 'A and B are both required before C') that JOINTLY gate a THIRD action C, then A does not gate B and B does not gate A - answer NO;
- both being mentioned only as facts about a third participant.
For q5 SEMANTIC_LINK: choose it when A and B denote the SAME underlying action (one is a passive, nominalized, reference or state facet of the other) - that is a semantic structure, not a normative relation between two distinct actions.
For q5 typing: look at HOW the antecedent is represented in the evidence. If the antecedent is represented as a STATE that must hold ('the tower is drained', 'the swr reading is below two'), type the relation STATE_GATE (or PRECONDITION if the state results from an executable check); reserve ORDER_BEFORE for two business operations sequenced as operations.
For q4: A_TO_B means A must happen first (A gates/precedes/enables B); B_TO_A means B must happen first."""


def e3_judge_user_v3(evidence: str, a: dict, b: dict, a_anchor: str | None,
                     b_anchor: str | None) -> str:
    def forms(x):
        return " / ".join(f'"{f}"' for f in (x.get("all_forms") or
                                             [x.get("source_span")]) if f)

    def anchor_line(name, anchor, x):
        if anchor:
            return (f"ENDPOINT {name} is represented in the evidence as: "
                    f"\"{anchor}\" (surface forms of {name}: {forms(x)}; "
                    f"type: {x.get('type', 'UNKNOWN')})")
        return (f"ENDPOINT {name} surface forms: {forms(x)} "
                f"(type: {x.get('type', 'UNKNOWN')}); find the representation "
                f"of {name} in the evidence yourself")

    return (f"EVIDENCE (exact quote from a policy):\n\"{evidence}\"\n\n"
            + anchor_line("A", a_anchor, a) + "\n"
            + anchor_line("B", b_anchor, b) + "\n\n"
            "Answer the five questions strictly as JSON.")


# ------------------------------------------------------ verifier v3
def _occurs_in_window(policy: str, form: str, w0: int, w1: int) -> bool:
    """True if some occurrence of form lies inside policy[w0:w1]."""
    if not form:
        return False
    window = policy[w0:w1]
    if form in window:
        return True
    low_w, low_f = window.lower(), form.lower()
    return low_f in low_w


def _find_in_window(policy: str, form: str, w0: int, w1: int):
    window = policy[w0:w1]
    off = window.find(form)
    if off >= 0:
        return w0 + off, w0 + off + len(form)
    off = window.lower().find(form.lower())
    if off >= 0:
        return w0 + off, w0 + off + len(form)
    return None


def verify_certificate_v3(policy: str, cert: dict, a: dict, b: dict) -> dict:
    """Deterministic verification, any-form variant (v1) + clause repair
    (v2) + via_reference channel (v3)."""
    v = {"verdict": "UNKNOWN", "reason": None}
    cert = {k: sanitize_quote(x) for k, x in (cert or {}).items()}
    if cert.get("a_anchor") == "NO_ANCHOR" or cert.get("b_anchor") == \
            "NO_ANCHOR":
        v["verdict"] = "UNSUPPORTED"
        v["reason"] = "endpoint_not_represented"
        return v
    if cert.get("relation_text") == "NO_RELATION":
        v["verdict"] = "UNSUPPORTED"
        v["reason"] = "no_relation"
        return v
    rel = span_in(policy, cert.get("relation_text"))
    if rel is None:
        v["verdict"] = "UNKNOWN"
        v["reason"] = "relation_text_not_verbatim"
        return v
    a_forms = [f for f in (a.get("all_forms") or [a.get("source_span")])
               if f]
    b_forms = [f for f in (b.get("all_forms") or [b.get("source_span")])
               if f]
    if not a_forms or not b_forms:
        v["verdict"] = "UNKNOWN"
        v["reason"] = "endpoint_form_not_verbatim"
        return v

    def anchors_in(w0, w1):
        aa = next((f for f in a_forms if _occurs_in_window(policy, f, w0,
                                                           w1)), None)
        bb = next((f for f in b_forms if _occurs_in_window(policy, f, w0,
                                                           w1)), None)
        return aa, bb

    a_hit, b_hit = anchors_in(rel[0], rel[1])
    if a_hit and b_hit:
        v.update({"verdict": "SUPPORTED", "reason": "both_forms_in_rel",
                  "a_anchor": a_hit, "b_anchor": b_hit,
                  "relation_text": policy[rel[0]:rel[1]],
                  "direction": cert.get("direction", "UNKNOWN"),
                  "relation_type": cert.get("relation_type", "UNKNOWN")})
        return v
    # v2: clause repair - expand to minimal covering span in the sentence
    s0, s1 = sent_span(policy, rel[0])
    sa, sb = anchors_in(s0, s1)
    if sa and sb:
        pa = _find_in_window(policy, sa, s0, s1)
        pb = _find_in_window(policy, sb, s0, s1)
        if pa and pb:
            w0, w1 = min(pa[0], pb[0]), max(pa[1], pb[1])
            repaired = policy[w0:w1]
            v.update({"verdict": "SUPPORTED",
                      "reason": "clause_repair_covering_span",
                      "a_anchor": sa, "b_anchor": sb,
                      "relation_text": repaired,
                      "direction": cert.get("direction", "UNKNOWN"),
                      "relation_type": cert.get("relation_type", "UNKNOWN")})
            return v
    # v3: via_reference channel -> judge resolves
    a_ref = cert.get("a_via_reference")
    b_ref = cert.get("b_via_reference")
    refs = []
    for ref, forms, name in ((a_ref, a_forms, "a"), (b_ref, b_forms, "b")):
        if isinstance(ref, str) and ref and ref not in ("NO_ANCHOR", "null"):
            r = span_in(policy, ref)
            if r and rel[0] <= r[0] and r[1] <= rel[1]:
                refs.append((name, ref))
    if refs and (a_ref or b_ref):
        got = {n for n, _ in refs}
        a_anchor = next((r for n, r in refs if n == "a"), a_hit)
        b_anchor = next((r for n, r in refs if n == "b"), b_hit)
        if a_anchor and b_anchor:
            v.update({"verdict": "UNKNOWN",
                      "reason": "via_reference_pending_judge",
                      "a_anchor": a_anchor, "b_anchor": b_anchor,
                      "relation_text": policy[rel[0]:rel[1]],
                      "direction": cert.get("direction", "UNKNOWN"),
                      "relation_type": cert.get("relation_type", "UNKNOWN")})
            return v
    v["verdict"] = "UNSUPPORTED"
    v["reason"] = "relation_text_not_connecting_both_endpoints"
    v["a_hit"], v["b_hit"] = a_hit, b_hit
    return v


# ----------------------------------------------------------------- nodes v3
BNORM_DIRS = sorted(OUT.glob("W1_BNORM*"), key=lambda p: p.stat().st_mtime
                    if p.exists() else 0)


def _load(path: Path) -> list[dict]:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))["candidates"]
    return []


def _in_policy(policy: str, s: str) -> bool:
    if not s:
        return False
    return s in policy or s.lower() in policy.lower()


def _grounded_forms(policy: str, base: str, orig: str | None,
                    dec: str) -> list[str]:
    """Boundary variants of one candidate span, all locatable in policy
    (case-tolerant, like span_in)."""
    forms: list[str] = []
    if base and _in_policy(policy, base):
        forms.append(base)
    if dec != "SPLIT" and orig and orig != base and _in_policy(policy,
                                                                orig):
        forms.append(orig)
    # article variant
    if base and not re.match(r"^(the|a|an)\b", base.strip(), re.I):
        for cand in (f"the {base}", f"The {base}"):
            if _in_policy(policy, cand) and cand not in forms:
                forms.append(cand)
                break
    # predicate-only variant: '<subject> <is/are/was/were> <pred>'
    m = re.match(r"^(.{3,60}?)\s+(is|are|was|were)\s+(not\s+)?(.+)$",
                 base or "", re.I)
    if m and len(m.group(1).split()) <= 5:
        pred = f"{m.group(2)} " + (m.group(3) or "") + m.group(4)
        if _in_policy(policy, pred) and pred not in forms:
            forms.append(pred)
    # subject-extended variant for predicate-initial spans (b2)
    if base and COPULA_START.match(base.strip()):
        ext = subject_extend(policy, base)
        if ext and ext not in forms:
            forms.append(ext)
    return [f for f in forms if f and f.strip()]


def subject_extend(policy: str, span: str) -> str | None:
    """Extend a predicate-initial span leftwards to include its subject.
    Stops at clause punctuation OR a leading connective word."""
    idx = policy.find(span)
    if idx < 0:
        idx = policy.lower().find(span.lower())
    if idx <= 0:
        return None
    left = policy[:idx]
    # maximal run of word characters/spaces ending at idx
    i = len(left)
    while i > 0 and (left[i - 1].isalnum() or left[i - 1] in " '-"):
        i -= 1
    words = left[i:].split()
    # walk right-to-left; stop before a connective or after 6 words
    subj: list[str] = []
    for w in reversed(words):
        if w.lower() in {"only", "if", "when", "while", "unless", "until",
                          "after", "before", "once", "provided", "that",
                          "which", "and", "or", "but", "so", "then",
                          "case", "where", "although", "though"}:
            break
        subj.insert(0, w)
        if len(subj) >= 6:
            break
    subject = " ".join(subj).strip()
    if not subject:
        return None
    ext = f"{subject} {span}"
    return ext if _in_policy(policy, ext) else None


def build_nodes_v3(arm: str, case: dict) -> list[dict]:
    policy = case["policy"]
    cid = case["case_id"]
    orig = {c["cid_local"]: c for c in _load(IE / "outputs" / arm /
                                             f"{cid}.json")}
    hyg = {c["cid_local"]: c for c in _load(OUT / "W1_HYG" / arm /
                                            f"{cid}.json")}
    bn = []
    for d in reversed(BNORM_DIRS):
        f = d / arm / f"{cid}.json"
        if f.exists():
            bn = _load(f)
            break
    survivors: dict[str, dict] = {}
    for c in bn:
        if c.get("bnorm_decision") == "DROP":
            continue
        root = c["cid_local"].split("_b")[0]
        base = c.get("span") or ""
        dec = c.get("bnorm_decision") or "KEEP"
        o = orig.get(root) or hyg.get(root) or {}
        variants = _grounded_forms(policy, base, o.get("span"), dec)
        if not variants:
            continue
        survivors[c["cid_local"]] = {
            "cid_local": c["cid_local"], "root": root,
            "span": variants[0], "forms": variants,
            "type": c.get("type") or o.get("type") or "UNKNOWN",
            "relations": c.get("relations") or o.get("relations") or [],
            "start": policy.find(variants[0]),
            "arguments": [g for g in (c.get("arguments") or
                                      o.get("arguments") or [])
                          if isinstance(g.get("span"), str)]}
    # b1: keep-override for dropped indicative state clauses
    present_roots = {s["root"] for s in survivors.values()}
    for k, c in hyg.items():
        if k in present_roots or any(sk.startswith(k + "_b")
                                     for sk in survivors):
            continue
        span = c.get("span") or ""
        if not span or c.get("type") not in ("STATE_OR_FACET", "CHECK",
                                             "UNKNOWN"):
            continue
        if not COPULA_ANY.search(span) or re.search(r"\bmust\b|\bshould\b",
                                                    span, re.I):
            continue  # only indicative copula states
        if len(COPULA_ANY.findall(span)) >= 2:
            continue  # conjunction of clauses - not a single state
        if not _in_policy(policy, span):
            continue
        base = span
        if COPULA_START.match(span.strip()):
            ext = subject_extend(policy, span)
            if ext:
                base = ext
        variants = _grounded_forms(policy, base, None, "KEEP")
        survivors[k] = {"cid_local": k, "root": k, "span": variants[0],
                        "forms": variants,
                        "type": c.get("type"),
                        "relations": c.get("relations") or [],
                        "start": policy.find(variants[0]),
                        "arguments": c.get("arguments") or []}
    # type filter + artifact-subject taxonomy filter (n3, any form)
    kept = {}
    for k, s in survivors.items():
        if s["type"] not in EVENTLIKE:
            continue
        if any(ARTIFACT_SUBJ.match(f) and (TAXONOMY_PRED.search(f)
                                           or COMM_VERB.search(f))
               for f in s["forms"]):
            continue
        kept[k] = s
    # merge survivors sharing the same primary span (bnorm/b1 duplication)
    by_span: dict[str, list[str]] = defaultdict(list)
    for k, s in kept.items():
        by_span[s["span"]].append(k)
    for span, keys in by_span.items():
        if len(keys) > 1:
            main = keys[0]
            for other in keys[1:]:
                kept[main]["forms"] = list(dict.fromkeys(
                    kept[main]["forms"] + kept[other]["forms"]))
                kept[main]["relations"] = list(
                    {json.dumps(r, sort_keys=True): r for r in
                     kept[main]["relations"] + kept[other]["relations"]}
                    .values())
                kept[main]["arguments"] = kept[main]["arguments"] + \
                    kept[other]["arguments"]
                del kept[other]
    # n2: orphan-fragment drop
    spans_all = [s["span"] for s in kept.values()]
    for k, s in list(kept.items()):
        if s["type"] in ("EVENT_REFERENCE", "CHECK", "ENTITY", "ARTIFACT") \
                and not s["relations"]:
            for other in spans_all:
                if other != s["span"] and s["span"] in other:
                    del kept[k]
                    break
    # union via SAME_EVENT / REFERENCE_OF
    parent = {k: k for k in kept}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    for k, s in kept.items():
        for r in s["relations"]:
            if r.get("type") in ("SAME_EVENT", "REFERENCE_OF") \
                    and r.get("to") in parent:
                union(k, r["to"])
    groups: dict[str, list] = defaultdict(list)
    for k, s in kept.items():
        groups[find(k)].append(s)
    nodes = []
    for i, (root, members) in enumerate(sorted(
            groups.items(),
            key=lambda kv: min(m["start"] if m["start"] >= 0 else 10 ** 6
                               for m in kv[1]))):
        ms = sorted(members, key=lambda m: m["start"]
                    if m["start"] >= 0 else 10 ** 6)
        forms: list[str] = []
        for m in ms:
            for f in m["forms"]:
                if f not in forms:
                    forms.append(f)
        types = [m["type"] for m in ms]
        nodes.append({
            "node_id": f"N{i+1:02d}",
            "members": [m["cid_local"] for m in ms],
            "span": forms[0], "start": ms[0]["start"],
            "type": max(set(types), key=types.count),
            "role": TYPE_TO_ROLE.get(max(set(types), key=types.count),
                                     "UNKNOWN"),
            "member_spans": forms,
            "arguments": [a for m in ms for a in m["arguments"]]})
    return nodes


def node_view_v3(case: dict, n: dict) -> dict:
    by_name = {t["name"]: t for t in case["tools"]}
    tools = " ".join(render_tool(by_name[t]) for t in n.get(
        "governed_tools", []) if t in by_name)
    forms = n.get("member_spans") or [n["span"]]
    return {"source_span": forms[0], "role": n["role"], "type": n["type"],
            "all_forms": forms,
            "governed_tools": n.get("governed_tools", []),
            "span_start": n.get("start", 0), "tool_semantics": tools,
            "arguments": n.get("arguments", [])}


# ----------------------------------------------------------------- main
def main() -> None:
    from sentence_transformers import CrossEncoder

    arm = sys.argv[1] if len(sys.argv) > 1 else "LLM_SG"
    fname = ("level_f2_cases.json" if os.environ.get("LF_SUITE") == "f2"
             else "level_f_cases.json")
    gold = {c["case_id"]: c for c in json.loads(
        (IE / "frozen" / fname).read_text(encoding="utf-8"))}
    rer = CrossEncoder("BAAI/bge-reranker-base", device="cuda",
                       max_length=512,
                       cache_folder="/workspace/guardian/hf_cache")
    client = Mistral(model="ministral-14b-latest", cache_dir=OUT / "_cache")
    outdir = OUT / f"W1_DOWN3_{arm}"
    outdir.mkdir(parents=True, exist_ok=True)

    def ask(system, user, max_tokens=600):
        for _ in range(4):
            try:
                r = client.ask(system, user, max_tokens=max_tokens)
                parsed, _err = Mistral.parse_json(r["raw"])
                if parsed:
                    return parsed
            except Exception:
                time.sleep(3)
        return {}

    for cid_, case in gold.items():
        path = outdir / f"{cid_}.json"
        if path.exists():
            continue
        policy = case["policy"]
        by_name = {t["name"]: t for t in case["tools"]}
        nodes = build_nodes_v3(arm, case)
        if not nodes:
            path.write_text(json.dumps({"case_id": cid_, "nodes": [],
                                        "edges": [], "pairs": []}) + "\n")
            continue
        # tool grounding (frozen: name-blind rerank top-1)
        pairs, owners = [], []
        for i, n in enumerate(nodes):
            for t in case["tools"]:
                pairs.append((n["span"], render_tool(t)))
                owners.append(i)
        scores = rer.predict(pairs, batch_size=32,
                             convert_to_numpy=True).tolist() if pairs else []
        top: dict[int, list] = defaultdict(list)
        for i, s in zip(owners, scores):
            top[i].append(float(s))
        for i, n in enumerate(nodes):
            tools = sorted(zip(case["tools"], top.get(i, [])),
                           key=lambda x: -x[1])
            n["governed_tools"] = [t["name"] for t, _ in tools[:1]]

        def tool_text(n):
            return " ".join(render_tool(by_name[t])
                            for t in n.get("governed_tools", [])
                            if t in by_name)

        # sentence + token maps for proposal channels (p1)
        sent_idx = {}
        node_sents = []
        node_tokens = []
        for n in nodes:
            sset, tset = set(), set()
            for f in n["member_spans"] or [n["span"]]:
                off = policy.find(f)
                if off >= 0:
                    s0, s1 = sent_span(policy, off)
                    sset.add((s0, s1))
                    tset |= tokens_of(policy[s0:s1])
            node_sents.append(sset)
            node_tokens.append(tset | tokens_of(" ".join(
                n["member_spans"] or [n["span"]])))

        def channels(i, j):
            ch = []
            if node_sents[i] & node_sents[j]:
                ch.append("same_sentence")
            if node_tokens[i] & node_tokens[j]:
                ch.append("entity_bridge")
            return ch

        # member-level CE gating (frozen construction) for all i<j pairs
        mpairs, owners2 = [], []
        for i in range(len(nodes)):
            for j in range(len(nodes)):
                if i >= j:
                    continue
                if set(nodes[i]["members"]) & set(nodes[j]["members"]):
                    continue  # self-loop gate
                if set(nodes[i]["member_spans"]) & \
                        set(nodes[j]["member_spans"]):
                    continue  # shared form gate (v3)
                for ma in nodes[i]["member_spans"] or [nodes[i]["span"]]:
                    for mb in nodes[j]["member_spans"] or [nodes[j]["span"]]:
                        oa = policy.find(ma)
                        ob = policy.find(mb)
                        if oa < 0 or ob < 0:
                            continue
                        sa = policy[sent_span(policy, oa)[0]:
                                    sent_span(policy, oa)[1]].strip()
                        tb = f"{mb}. {policy[sent_span(policy, ob)[0]: sent_span(policy, ob)[1]].strip()} {tool_text(nodes[j])}".strip()
                        mpairs.append((sa, tb))
                        owners2.append((i, j))
        scores2 = rer.predict(mpairs, batch_size=32,
                              convert_to_numpy=True).tolist() if mpairs \
            else []
        best: dict[tuple, float] = {}
        for (i, j), sc in zip(owners2, scores2):
            best[(i, j)] = max(best.get((i, j), -1e9), float(sc))
        edges, pair_log = [], []
        for (i, j), sc in sorted(best.items()):
            na, nb = nodes[i], nodes[j]
            ch = channels(i, j)
            rec = {"u": na["node_id"], "v": nb["node_id"],
                   "u_span": na["span"], "v_span": nb["span"],
                   "ce": round(sc, 4)}
            if sc < CE_BAND and not ch:
                rec["stage"] = "ce_band"
                pair_log.append(rec)
                continue
            rec["channels"] = ch
            rec["stage"] = "certificate"
            ev_a, ev_b = node_view_v3(case, na), node_view_v3(case, nb)
            cert = ask(E3_EXT_SYSTEM_V3, e3_ext_user_v3(policy, ev_a, ev_b),
                       500)
            v = verify_certificate_v3(policy, cert, ev_a, ev_b)
            rec["verify"] = v["verdict"]
            rec["verify_reason"] = v.get("reason")
            licensed, direction, rel = False, None, None
            if v["verdict"] in ("SUPPORTED", "UNKNOWN") and \
                    v.get("relation_text"):
                ev = v["relation_text"]
                judge = ask(E3_JUDGE_SYSTEM_V3,
                            e3_judge_user_v3(ev, ev_a, ev_b,
                                             v.get("a_anchor"),
                                             v.get("b_anchor")), 400)
                rec["stage"] = "judge"
                q1 = sanitize_quote(judge.get("q1_where_is_a"))
                q2 = sanitize_quote(judge.get("q2_where_is_b"))
                if judge.get("q3_relation_between_these_two") != "YES":
                    rec["judge_note"] = "verifier_q3_no"
                elif not (q1 and span_in(ev, q1) is not None
                          and q2 and span_in(ev, q2) is not None):
                    rec["judge_note"] = "verifier_q1q2_not_in_evidence"
                elif judge.get("q5_relation_type") == "SEMANTIC_LINK":
                    rec["judge_note"] = "semantic_link_routing"
                else:
                    licensed = True
                    direction = judge.get("q4_direction", "UNKNOWN")
                    rel = judge.get("q5_relation_type", "UNKNOWN")
                rec["judge"] = judge
            if not licensed:
                pair_log.append(rec)
                continue
            if direction in (None, "UNKNOWN"):
                ans3 = ask(SYSTEM, dir_user(case, ev_a, ev_b), 200)
                first = (ans3 or {}).get("first")
                if first == "A":
                    direction = "A_TO_B"
                elif first == "B":
                    direction = "B_TO_A"
                else:
                    ra, rb = na["role"], nb["role"]
                    if rb in ("PRECONDITION_CHECK", "STATE_OBSERVATION") \
                            and ra not in ("PRECONDITION_CHECK",
                                           "STATE_OBSERVATION"):
                        direction = "B_TO_A"
                    elif (na.get("start") or 0) > (nb.get("start") or 0):
                        direction = "B_TO_A"
                    else:
                        direction = "A_TO_B"
            if rel in (None, "UNKNOWN"):
                if direction == "B_TO_A":
                    cls_a, cls_b = ev_b, ev_a
                else:
                    cls_a, cls_b = ev_a, ev_b
                ans4 = ask(SYSTEM, cls_user(case, cls_a, cls_b), 240)
                rel = (ans4 or {}).get("relation", "UNKNOWN")
            edges.append({"u": na["node_id"], "v": nb["node_id"],
                          "u_members": na["members"],
                          "v_members": nb["members"],
                          "u_span": na["span"], "v_span": nb["span"],
                          "relation": rel, "direction": direction,
                          "ce": round(sc, 4),
                          "detail": {"certificate": cert, "verify": v}})
            rec["stage"] = "licensed"
            rec["direction"] = direction
            rec["relation"] = rel
            pair_log.append(rec)
        path.write_text(json.dumps({"case_id": cid_, "arm": arm,
                                    "ev_arm": "E3V3",
                                    "nodes": [{"node_id": n["node_id"],
                                               "span": n["span"],
                                               "type": n.get("type"),
                                               "start": n.get("start"),
                                               "members": n["members"],
                                               "member_spans":
                                                   n["member_spans"]}
                                              for n in nodes],
                                    "edges": edges, "pairs": pair_log},
                                   indent=1) + "\n", encoding="utf-8")
        print(cid_, len(nodes), "nodes ->", len(edges), "edges",
              f"({len(pair_log)} pairs logged)", flush=True)
    print("W1 DOWN3", arm, "done")


if __name__ == "__main__":
    main()
