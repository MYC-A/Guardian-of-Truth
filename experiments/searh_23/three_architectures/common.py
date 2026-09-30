#!/usr/bin/env python3
"""Common infrastructure for the three-architectures experiment (F/S/V).

Shared, per directive §4/§6/§9 (V level 0):
  * lossless parser of the official competition format
    (⟦SYSTEM⟧ / ⟦USER⟧ / ⟦ASSISTANT⟧ / ⟦ASSISTANT · ход N⟧ markers;
     → TOOL_CALL name: {json} / ← TOOL_RESPONSE name: {json} arrows)
  * context builder preserving the FULL raw text, turn/call/result IDs,
    chronology, field paths; nothing is silently dropped
  * structural channel: only CONFIRMED mechanical violations of the
    authoritative catalog / parseable-arguments schema, evaluated on the
    TARGET response (history errors alone never flag the current move)
  * neutral suspicion extractors (value-not-in-history, failed-call-retry,
    repeated-question) for judge context — status "suspicion", never label=1
  * official-format predictions.csv writer (id,label) with atomic batch
    writes + immutable structural baseline copy + audit.jsonl

No LLM here: this module is fully deterministic and replayable.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- transport

MARKER_SPLIT = re.compile(
    r'⟦(SYSTEM|USER|ASSISTANT(?:\s*·\s*ход\s*\d+)?)⟧[^\S\n]*\n?'
)
TOOL_LINE = re.compile(
    r'→\s*TOOL_CALL\s+(?P<name>[\w.-]+)\s*:\s*(?P<args>\{.*)'
)
RESULT_LINE = re.compile(
    r'←\s*TOOL_RESPONSE\s+(?P<name>[\w.-]+)\s*:\s*(?P<payload>\{.*)'
)
CATALOG_HEADER = re.compile(r'\[AVAILABLE TOOLS\]', re.IGNORECASE)
CATALOG_ENTRY = re.compile(r'^[-*]\s+`?(?P<name>[\w.-]+)`?\s*[—–-]\s*(?P<desc>.+)$')
PARAM_LINE = re.compile(
    r'^\s{2,}(?P<name>[\w]+)\s*:\s*(?P<type>\w+)?(?P<req>!)?'
    r'(?:\s*\[\s*enum:\s*(?P<enum>[^\]]+)\s*\])?\s*[—–-]?\s*(?P<desc>.*)$'
)
SUBFIELD_LINE = re.compile(
    r'^\s*·\s+(?P<name>[\w]+)\s*:\s*(?P<type>\w+)?(?P<req>!)?'
    r'(?:\s*\[\s*enum:\s*(?P<enum>[^\]]+)\s*\])?'
)

# V0.1 (pre-registered 2026-10-01 before holdout inference): verbatim
# policy clause that gates the one-action-per-turn structural rules.
# The clause is quoted from the case's own policy text when it fires;
# without the clause the rules stay silent (domain without the policy
# is never flagged).
ONE_CALL_CLAUSE = re.compile(
    r"[^.!?]*\b(?:one tool call at a time|only make one tool call|"
    r"at most (?:make )?one tool call|one action at a time)\b[^.!?]*[.!?]",
    re.IGNORECASE,
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- dataclasses

@dataclass
class ToolCall:
    call_id: str            # c1, c2, ... unique within case
    name: str
    args_raw: str           # verbatim after the colon
    args: dict | None       # parsed JSON (None => unparseable)
    args_error: str | None  # reason if unparseable
    line_no: int            # 0-based line in the raw block
    in_target: bool         # True if inside the TARGET response


@dataclass
class ToolResult:
    result_id: str          # r1, r2, ...
    call_ref: str | None    # matching call_id if resolvable (same name,
                            # first unconsumed prior call), else None
    name: str
    payload_raw: str
    payload: dict | None
    line_no: int
    in_target: bool


@dataclass
class Turn:
    turn_id: str            # u1/a1/u2/a2...
    role: str               # user / assistant / system
    raw: str                # verbatim block body
    text: str               # non-tool lines joined (prose)
    tool_calls: list = field(default_factory=list)
    tool_results: list = field(default_factory=list)
    is_target: bool = False # the target response turn itself


@dataclass
class ParamSpec:
    name: str
    type: str = "string"          # string/integer/number/array/boolean/object
    required: bool = False        # '!' marker
    enum: list | None = None      # [enum: a|b|c]
    desc: str = ""
    subfields: list = field(default_factory=list)  # nested ParamSpec


@dataclass
class ToolSpec:
    name: str
    description: str = ""
    params: dict = field(default_factory=dict)  # param name -> ParamSpec


@dataclass
class Catalog:
    tools: dict = field(default_factory=dict)   # name -> ToolSpec
    section_found: bool = False


@dataclass
class Suspicion:
    kind: str                # value_not_in_history | failed_call_retry |
                             # repeated_question | unparseable_args_history
    detail: str
    evidence_refs: list = field(default_factory=list)  # ids/paths, never invented


@dataclass
class StructuralHit:
    reason: str              # catalog_absent | args_unparseable
    tool: str
    call_id: str
    basis: str               # reproducible basis (quoted line)


@dataclass
class CaseContext:
    case_id: str
    prompt_raw: str
    response_raw: str
    system: str              # verbatim ⟦SYSTEM⟧ block(s)
    policy_text: str         # system minus the catalog section
    catalog: Catalog
    turns: list = field(default_factory=list)   # chronology incl. target
    structural_hits: list = field(default_factory=list)
    suspicions: list = field(default_factory=list)
    parse_warnings: list = field(default_factory=list)

    # --- accessors -----------------------------------------------------
    def target(self) -> Turn:
        return self.turns[-1]

    def history_turns(self) -> list:
        return self.turns[:-1]

    def all_tool_calls(self) -> list:
        out = []
        for t in self.turns:
            out.extend(t.tool_calls)
        return out

    def all_tool_results(self) -> list:
        out = []
        for t in self.turns:
            out.extend(t.tool_results)
        return out


# ---------------------------------------------------------------- parsing

def _split_catalog(system_text: str) -> tuple[str, Catalog]:
    """Deterministically split the [AVAILABLE TOOLS] section out of the
    SYSTEM block, parsing tool entries, parameter lines (type!, [enum:..])
    and nested subfields into a real argument schema.

    Catalog format (verified on public46):
      [AVAILABLE TOOLS]
      - tool_name — description.
          param: type! [enum: a|b] — desc
              · subfield: type — desc
    The section runs to the end of the SYSTEM block; margin-level lines
    that are neither entries nor blank terminate it defensively."""
    m = CATALOG_HEADER.search(system_text)
    if not m:
        return system_text, Catalog(section_found=False)
    head = system_text[:m.start()].rstrip("\n")
    rest = system_text[m.end():]
    lines = rest.split("\n")

    tools: dict[str, ToolSpec] = {}
    current: ToolSpec | None = None
    current_param: ParamSpec | None = None
    tail_lines: list[str] = []
    in_cat = True

    for ln in lines:
        if not in_cat:
            tail_lines.append(ln)
            continue
        em = CATALOG_ENTRY.match(ln)
        if em:
            current = ToolSpec(name=em.group("name"),
                               description=em.group("desc").strip())
            tools[current.name] = current
            current_param = None
            continue
        if ln.strip() == "":
            if current is not None:
                continue          # blank inside catalog: keep scanning
            tail_lines.append(ln)
            continue
        pm = PARAM_LINE.match(ln)
        if pm and current is not None:
            spec = ParamSpec(
                name=pm.group("name"),
                type=(pm.group("type") or "string").lower(),
                required=pm.group("req") == "!",
                enum=([v.strip() for v in pm.group("enum").split("|")]
                       if pm.group("enum") else None),
                desc=(pm.group("desc") or "").strip(" —–-"))
            current.params[spec.name] = spec
            current_param = spec
            continue
        sm = SUBFIELD_LINE.match(ln)
        if sm and current_param is not None:
            current_param.subfields.append(ParamSpec(
                name=sm.group("name"),
                type=(sm.group("type") or "string").lower(),
                required=sm.group("req") == "!"))
            continue
        if ln.startswith((" ", "\t")) and current is not None:
            # continuation text of a description/param: keep as desc tail
            if current_param is not None:
                current_param.desc += " " + ln.strip()
            else:
                current.description += " " + ln.strip()
            continue
        # margin-level non-entry line: catalog over
        in_cat = False
        tail_lines.append(ln)

    tail = "\n".join(tail_lines).strip("\n")
    policy = (head + ("\n" + tail if tail else "")).strip("\n")
    return policy, Catalog(tools=tools, section_found=True)


def _parse_json_lenient(raw: str):
    raw = raw.strip()
    # response lines may carry trailing content after the JSON object;
    # use a bracket-matching scan (string-aware).
    if not raw.startswith("{"):
        return None, "not an object"
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(raw):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = raw[: i + 1]
                try:
                    return json.loads(blob), None
                except Exception as e:
                    try:
                        return json.loads(blob.replace("'", '"')), None
                    except Exception:
                        return None, f"json error: {e}"
    return None, "unbalanced braces"


def parse_case(case_id: str, prompt: str, response: str) -> CaseContext:
    """Lossless deterministic parse. Never invents content; warnings are
    recorded instead of silent fixes."""
    ctx = CaseContext(case_id=case_id, prompt_raw=prompt,
                      response_raw=response, system="", policy_text="",
                      catalog=Catalog())
    markers = list(MARKER_SPLIT.finditer(prompt))
    blocks = []
    for i, marker in enumerate(markers):
        tag = marker.group(1)
        start = marker.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(prompt)
        blocks.append((tag, prompt[start:end]))
    if not markers:
        ctx.parse_warnings.append("no markers in prompt; whole prompt as system")
        blocks = [("SYSTEM", prompt)]

    u_i = a_i = c_i = r_i = 0
    for tag, body in blocks:
        if tag == "SYSTEM":
            ctx.system = ctx.system + ("\n" if ctx.system else "") + body
            continue
        turn = Turn(turn_id="", role="", raw=body, text="")
        if tag == "USER":
            u_i += 1
            turn.turn_id = f"u{u_i}"
            turn.role = "user"
        else:
            a_i += 1
            turn.turn_id = f"a{a_i}"
            turn.role = "assistant"
        prose_lines = []
        for line_no, line in enumerate(body.split("\n")):
            cm = TOOL_LINE.search(line)
            rm = RESULT_LINE.search(line)
            if cm:
                c_i += 1
                args, err = _parse_json_lenient(cm.group("args"))
                turn.tool_calls.append(ToolCall(
                    call_id=f"c{c_i}", name=cm.group("name"),
                    args_raw=cm.group("args"), args=args, args_error=err,
                    line_no=line_no, in_target=False))
            elif rm:
                r_i += 1
                payload, err = _parse_json_lenient(rm.group("payload"))
                turn.tool_results.append(ToolResult(
                    result_id=f"r{r_i}", call_ref=None, name=rm.group("name"),
                    payload_raw=rm.group("payload"), payload=payload,
                    line_no=line_no, in_target=False))
            else:
                prose_lines.append(line)
        turn.text = "\n".join(prose_lines).strip()
        ctx.turns.append(turn)

    # ---- target response turn (appended, marked) ----
    a_i += 1
    target = Turn(turn_id=f"a{a_i}", role="assistant", raw=response,
                  text="", is_target=True)
    prose_lines = []
    for line_no, line in enumerate(response.split("\n")):
        cm = TOOL_LINE.search(line)
        rm = RESULT_LINE.search(line)
        if cm:
            c_i += 1
            args, err = _parse_json_lenient(cm.group("args"))
            tc = ToolCall(call_id=f"c{c_i}", name=cm.group("name"),
                          args_raw=cm.group("args"), args=args, args_error=err,
                          line_no=line_no, in_target=True)
            target.tool_calls.append(tc)
        elif rm:
            r_i += 1
            payload, err = _parse_json_lenient(rm.group("payload"))
            tr = ToolResult(result_id=f"r{r_i}", call_ref=None,
                            name=rm.group("name"),
                            payload_raw=rm.group("payload"),
                            payload=payload, line_no=line_no, in_target=True)
            target.tool_results.append(tr)
        else:
            prose_lines.append(line)
    target.text = "\n".join(prose_lines).strip()
    ctx.turns.append(target)

    ctx.policy_text, ctx.catalog = _split_catalog(ctx.system)

    # resolve result->call refs (same name, first unconsumed earlier call)
    consumed: set[str] = set()
    for t in ctx.turns:
        for res in t.tool_results:
            for t2 in ctx.turns:
                for call in t2.tool_calls:
                    if call.call_id in consumed:
                        continue
                    if call.name == res.name and _order(call, res, ctx):
                        res.call_ref = call.call_id
                        consumed.add(call.call_id)
                        break
                if res.call_ref:
                    break
    _structural_channel(ctx)
    _suspicion_extractors(ctx)
    return ctx


def _order(call: ToolCall, res: ToolResult, ctx: CaseContext) -> bool:
    """True if the call appears before the result in case chronology."""
    seq = []
    for t in ctx.turns:
        for c in t.tool_calls:
            seq.append(("c", c.call_id))
        for r in t.tool_results:
            seq.append(("r", r.result_id))
    try:
        return seq.index(("c", call.call_id)) < seq.index(("r", res.result_id))
    except ValueError:
        return False


# ------------------------------------------------------- structural channel

def _check_schema(call: ToolCall, tool: ToolSpec) -> list[StructuralHit]:
    """Schema violations of a TARGET call against the catalog-declared
    argument schema. Reproducible basis for every hit.
    V0.1: also required SUBFIELDS of array items / object params
    (e.g. payment_methods items must carry payment_id!/amount!)."""
    hits = []
    args = call.args or {}
    if not isinstance(args, dict):
        hits.append(StructuralHit(
            reason="schema_args_not_object", tool=call.name,
            call_id=call.call_id,
            basis=f"arguments are {type(args).__name__}, schema expects an object"))
        return hits
    for pname, spec in tool.params.items():
        if spec.required and pname not in args:
            hits.append(StructuralHit(
                reason="schema_missing_required", tool=call.name,
                call_id=call.call_id,
                basis=(f"required parameter '{pname}' ({spec.type}!) missing; "
                       f"catalog declares it for '{tool.name}'")))
    for pname, value in args.items():
        spec = tool.params.get(pname)
        if spec is None:
            continue  # unknown param: suspicion territory, not confirmed
        if spec.enum is not None and value not in spec.enum \
                and not (isinstance(value, str) and value in spec.enum):
            hits.append(StructuralHit(
                reason="schema_enum", tool=call.name, call_id=call.call_id,
                basis=(f"parameter '{pname}' value {value!r} not in enum "
                       f"{spec.enum} declared in catalog")))
        expected = spec.type
        got = _json_type_name(value)
        if expected in ("string", "integer", "number", "boolean", "array") \
                and got != expected \
                and not (expected == "number" and got == "integer") \
                and not (expected == "integer" and got == "number"
                         and float(value).is_integer()):
            hits.append(StructuralHit(
                reason="schema_type", tool=call.name, call_id=call.call_id,
                basis=(f"parameter '{pname}' expected {expected}, "
                       f"got {got} ({value!r})")))
        # V0.1 R3: required subfields of array items / declared objects
        if spec.subfields and got in ("array", "object"):
            items = value if isinstance(value, list) else [value]
            for idx, it in enumerate(items):
                if not isinstance(it, dict):
                    continue
                for sf in spec.subfields:
                    if sf.required and sf.name not in it:
                        hits.append(StructuralHit(
                            reason="schema_missing_required_subfield",
                            tool=call.name, call_id=call.call_id,
                            basis=(f"parameter '{pname}' item #{idx} misses "
                                   f"required subfield '{sf.name}' "
                                   f"({sf.type}!); catalog declares: "
                                   + ", ".join(
                                       f"{s.name}{'!' if s.required else ''}"
                                       for s in spec.subfields))))
    return hits


def _json_type_name(v) -> str:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return type(v).__name__


def _near_miss(name: str, catalog_names: set) -> str | None:
    """Closest catalog name (prefix/edit-distance) for audit transparency."""
    best, best_d = None, None
    for cn in catalog_names:
        d = _edit_distance(name.lower(), cn.lower())
        if best_d is None or d < best_d:
            best, best_d = cn, d
    if best_d is not None and best_d <= 3:
        return best
    return None


def _edit_distance(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _structural_channel(ctx: CaseContext) -> None:
    """CONFIRMED mechanical violations only, on the TARGET response.
    History anomalies become warnings/suspicions, never label=1.
    V0.1 (pre-registered 2026-10-01, before any holdout inference):
      + R1 policy_one_call_violation — target turn makes >=2 tool calls while
        the case's own policy verbatim forbids more than one per turn;
      + R2 policy_text_and_call_violation — target turn mixes prose and a
        tool call while the same verbatim clause forbids it;
        (both rules are gated on the QUOTED policy sentence; a domain whose
        policy lacks the clause is never flagged)
      + R3 schema_missing_required_subfield (inside _check_schema).
    Diagnostic effect on burned public46: TP5->TP11, FP0->FP0."""
    catalog_names = set(ctx.catalog.tools)
    for call in ctx.target().tool_calls:
        tool = ctx.catalog.tools.get(call.name)
        if catalog_names and tool is None:
            near = _near_miss(call.name, catalog_names)
            ctx.structural_hits.append(StructuralHit(
                reason="catalog_absent", tool=call.name, call_id=call.call_id,
                basis=(f"tool '{call.name}' absent from authoritative "
                       f"[AVAILABLE TOOLS] catalog ({len(catalog_names)} tools)"
                       + (f"; nearest catalog name: '{near}'" if near else ""))))
        if call.args_error is not None:
            ctx.structural_hits.append(StructuralHit(
                reason="args_unparseable", tool=call.name,
                call_id=call.call_id,
                basis=(f"arguments not parseable JSON ({call.args_error}): "
                       f"{call.args_raw[:120]}")))
        if tool is not None and call.args is not None:
            ctx.structural_hits.extend(_check_schema(call, tool))

    # ---- V0.1 R1/R2: policy-gated one-action-per-turn rules -------------
    clause_m = ONE_CALL_CLAUSE.search(ctx.policy_text) \
        if ctx.policy_text else None
    if clause_m:
        clause_quote = " ".join(clause_m.group(0).split())
        tgt = ctx.target()
        call_ids = [c.call_id for c in tgt.tool_calls]
        if len(call_ids) >= 2:
            ctx.structural_hits.append(StructuralHit(
                reason="policy_one_call_violation",
                tool=",".join(c.name for c in tgt.tool_calls),
                call_id=",".join(call_ids),
                basis=(f"target turn makes {len(call_ids)} tool calls "
                       f"({', '.join(call_ids)}) while the policy states: "
                       f"\"{clause_quote}\"")))
        elif call_ids:
            prose = re.sub(r"⟦[^⟧]*⟧", "", tgt.text).strip()
            if prose:
                ctx.structural_hits.append(StructuralHit(
                    reason="policy_text_and_call_violation",
                    tool=tgt.tool_calls[0].name, call_id=call_ids[0],
                    basis=(f"target turn mixes a text response and tool call "
                           f"{call_ids[0]} while the policy states: "
                           f"\"{clause_quote}\"")))

    # history-side anomalies -> warnings only (current-move semantics)
    for t in ctx.history_turns():
        for call in t.tool_calls:
            if catalog_names and call.name not in catalog_names:
                ctx.parse_warnings.append(
                    f"history call {call.call_id} uses non-catalog tool "
                    f"{call.name} (not a current-move error)")
            if call.args_error is not None:
                ctx.suspicions.append(Suspicion(
                    kind="unparseable_args_history",
                    detail=(f"history call {call.call_id} ({call.name}) has "
                            f"unparseable args; possibly truncated transport"),
                    evidence_refs=[call.call_id]))


# ------------------------------------------------------- suspicion extractors

_ID_TOKEN = re.compile(r'\b[A-Z0-9]{5,}\b')           # reservation ids etc.
_NUM_TOKEN = re.compile(r'\b\d+(?:[.,]\d+)?\b')


def _suspicion_extractors(ctx: CaseContext) -> None:
    """Neutral evidence for judge context. Status: suspicion, NOT error."""
    history_blob = ctx.prompt_raw
    target = ctx.target()

    # (1) salient tokens in target prose absent verbatim from history
    prose = target.text
    if prose:
        tokens = set()
        for m in _ID_TOKEN.finditer(prose):
            # mixed-case ids: also compare case-insensitively
            tokens.add(m.group(0))
        for m in _NUM_TOKEN.finditer(prose):
            if len(m.group(0)) >= 3:  # skip tiny numbers (t5, 2, etc.)
                tokens.add(m.group(0))
        absent = sorted(
            t for t in tokens
            if t not in history_blob and t.lower() not in history_blob.lower()
        )
        if absent:
            ctx.suspicions.append(Suspicion(
                kind="value_not_in_history",
                detail=("target response mentions values absent verbatim "
                        "from the full prompt history: "
                        + ", ".join(absent[:12])),
                evidence_refs=[target.turn_id]))

    # (2) failed-call retry: target repeats a call whose earlier result
    #     looks like an error
    err_results = {}
    for t in ctx.history_turns():
        for res in t.tool_results:
            if _looks_like_error(res.payload):
                err_results.setdefault(res.name, []).append(res.result_id)
    for call in target.tool_calls:
        if call.name in err_results:
            ctx.suspicions.append(Suspicion(
                kind="failed_call_retry",
                detail=(f"target repeats call '{call.name}' whose earlier "
                        f"results looked like errors "
                        f"({', '.join(err_results[call.name])}); retry may "
                        f"be legitimate — policy/task decides"),
                evidence_refs=[call.call_id] + err_results[call.name]))

    # (3) repeated question: target asks a question already asked before
    q_hist = set(_questions(ctx.history_turns()))
    q_target = _questions([target])
    for q in q_target:
        if q in q_hist:
            ctx.suspicions.append(Suspicion(
                kind="repeated_question",
                detail=(f"target re-asks an earlier question verbatim: "
                        f"'{q[:80]}'"),
                evidence_refs=[target.turn_id]))


def _looks_like_error(payload: dict | None) -> bool:
    if not isinstance(payload, dict):
        return False
    for k in ("error", "status", "code", "result"):
        v = payload.get(k)
        if isinstance(v, str) and v.lower() in (
                "error", "failed", "failure", "not_found", "denied",
                "invalid", "unavailable"):
            return True
        if isinstance(v, dict):
            inner = str(v).lower()
            if "error" in inner or "not found" in inner:
                return True
    if "error" in {str(k).lower() for k in payload}:
        return True
    return False


_Q_RE = re.compile(r'[^.?!\n]*\?')


def _questions(turns) -> list:
    out = []
    for t in turns:
        for m in _Q_RE.finditer(t.text):
            q = " ".join(m.group(0).lower().split()).strip()
            if len(q) >= 12:
                out.append(q)
    return out


# ---------------------------------------------------------------- verdicts

def structural_label(ctx: CaseContext) -> int:
    """V level 0: confirmed structural hit -> 1; else 0 (structural
    BASELINE, not a certificate of absence)."""
    return 1 if ctx.structural_hits else 0


# ---------------------------------------------------------------- IO: cases

def load_cases_csv(path: Path) -> list:
    """Official input: columns id,prompt,response (label/explanation
    ignored by the GOLD FIREWALL if present)."""
    csv.field_size_limit(10 ** 9)
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    cases = []
    for r in rows:
        cases.append({"id": r["id"], "prompt": r["prompt"],
                      "response": r["response"]})
    return cases


def load_cases_parquet(path: Path) -> list:
    import pandas as pd
    df = pd.read_parquet(path)
    cols = {c.lower(): c for c in df.columns}
    idc, pc, rc = cols["id"], cols["prompt"], cols["response"]
    return [{"id": str(r[idc]), "prompt": str(r[pc]), "response": str(r[rc])}
            for _, r in df.iterrows()]


# ---------------------------------------------------------------- IO: preds

def write_predictions(path: Path, rows: list) -> None:
    """Official format: id,label — exact ids/order/count of the input.
    Atomic write (tmp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "label"])
        for r in rows:
            w.writerow([r["id"], int(r["label"])])
    os.replace(tmp, path)


def append_audit(audit_path: Path, record: dict) -> None:
    """Atomic-ish append (line-buffered, one JSON per line)."""
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with open(audit_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def case_audit_record(ctx: CaseContext, stage: str, extra: dict | None = None) -> dict:
    rec = {
        "id": ctx.case_id,
        "stage": stage,
        "timestamp": time.time(),
        "structural_status": (
            "CONFIRMED_HIT" if ctx.structural_hits else "NO_CONFIRMED_HIT"),
        "structural_hits": [
            {"reason": h.reason, "tool": h.tool, "call_id": h.call_id,
             "basis": h.basis} for h in ctx.structural_hits],
        "suspicions": [
            {"kind": s.kind, "detail": s.detail,
             "evidence_refs": s.evidence_refs} for s in ctx.suspicions],
        "parse_warnings": ctx.parse_warnings,
        "turn_count": len(ctx.turns),
        "target_tool_calls": len(ctx.target().tool_calls),
        "prompt_sha256": sha256_text(ctx.prompt_raw),
        "response_sha256": sha256_text(ctx.response_raw),
    }
    if extra:
        rec.update(extra)
    return rec
