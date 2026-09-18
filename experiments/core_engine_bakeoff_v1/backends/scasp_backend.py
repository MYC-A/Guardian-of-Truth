"""core_engine_bakeoff_v1 — backend: s(CASP) on SWI-Prolog 9.2.9.

NeutralCoreInput -> one Prolog program -> per-interpretation world error
values via goal-directed s(CASP) queries with JUSTIFICATION TREES ->
consensus.

ARCHITECTURE (after six documented s(CASP) 1.1.4 engine findings forced the
evidence joins into the adapter — see the report's engine capability
section for the full list):
  * The ADAPTER enumerates the evidence joins as GROUND MARKER FACTS
    (mk/2: supported/absent/neither, zero/both/stale/support/refute/nonev,
    ge_N/nge_N/complete/nocomplete, sup/2, ref/1, ent/1, mut/1, row/5,
    act_hit/5).  s(CASP) 1.1.4's dual generation over fact joins does not
    terminate / errs (determinism_error in scasp_solve:stack_parents/3).
  * NATIVE s(CASP) keeps the SEMANTIC layer: the four-valued tval tables,
    condition-tree recursive folds (conjunction/disjunction), obligation
    safety (material implication over the four-valued tables), per-world
    error values, and the goal-directed justifications (scasp/2 with
    tree(Tree)) — the key differentiator this backend measures.
  * One swipl process PER QUERY: s(CASP) is not re-entrant (the second
    scasp/2 call in a session fails with the same determinism error).
  * No choice rules exist in s(CASP): interpretations are evaluated as
    separate goal-directed derivations (worlds are NOT stable models here;
    the clingo backend is the stable-models experiment).

s(CASP) constraints honored by the encoding:
  * no `;` disjunctions inside rule bodies
  * predicates under `not` are single-clause and DEFINED (negating an
    undefined predicate fails silently)
  * clauses of every predicate are contiguous
  * ground facts precede the rules referencing them
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for p in (str(REPO / "src"), str(HERE.parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

from guardian_truth.vnext.integrity import canonical as _canon
from neutral_types import (BackendResult, BackendWitness, CondNode,
                           NeutralAtom, NeutralCoreInput, PrimitiveResult,
                           WorldResult)

ACTION_KINDS = ("ACTION_ATTEMPTED", "ACTION_COMPLETED", "ACTION_FAILED")
STATE_KINDS = ("STATE_OBSERVATION", "FIELD_VALUE")
END = 10**9

SWIPL = os.environ.get("BAKEOFF_SWIPL", "/home/z/swipl-root/usr/bin/swipl")
SCASP_PL = os.environ.get(
    "BAKEOFF_SCASP",
    "/home/z/.local/share/swi-prolog/pack/scasp/prolog/scasp.pl")
LD_LIBRARY_PATH = os.environ.get(
    "BAKEOFF_SWIPL_LIBS",
    "/home/z/swipl-root/usr/lib/x86_64-linux-gnu:"
    "/home/z/swipl-root/usr/lib/swi-prolog/lib/x86_64-linux-gnu")

_TRUTH_MAP = {"t": "TRUE", "f": "FALSE", "b": "BOTH", "u": "UNKNOWN"}
_VALUES = ("t", "f", "b", "u")


# ------------------------------------------------------------ term encoding

def _atom(value: str) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _val(value) -> str:
    if isinstance(value, bool):
        return f"v(bool({'true' if value else 'false'}))"
    if isinstance(value, (int, float)):
        return f"v(num({value}))"
    if isinstance(value, str):
        return f"v(str({_atom(value)}))"
    return f"v(str({_atom(str(value))}))"


def _fid(fact_id: str) -> str:
    return "f_" + "".join(ch if ch.isalnum() else "_" for ch in fact_id)


def _resolved_key(atom: NeutralAtom, t: int) -> str:
    saved = atom.time_index
    try:
        object.__setattr__(atom, "time_index", t)
        return atom.key()
    finally:
        object.__setattr__(atom, "time_index", saved)


# ------------------------------------------------------------ template (final)

TEMPLATE = r"""
% ============ four-valued SEMANTIC tables (native s(CASP)) ================
% All evidence joins are adapter-emitted ground facts; every rule below is
% positive-Horn over those facts plus the four-valued connective tables.

negv(t, f). negv(f, t). negv(b, b). negv(u, u).
conjv(t, t, t).
conjv(t, f, f).
conjv(t, b, b).
conjv(t, u, u).
conjv(f, X, f) :- tvdom(X).
conjv(b, t, b).
conjv(b, f, f).
conjv(b, b, b).
conjv(b, u, u).
conjv(u, t, u).
conjv(u, f, f).
conjv(u, b, b).
conjv(u, u, u).
tvdom(t). tvdom(f). tvdom(b). tvdom(u).
disjv(A, B, C) :- negv(A, NA), negv(B, NB), conjv(NA, NB, NAB), negv(NAB, C).

% ---- query evaluation over adapter markers (mk/2)
tval(Q, t) :- q_attempted(Q, _, _, _, _), mk(Q, supported).
tval(Q, f) :- q_attempted(Q, _, _, _, _), mk(Q, absent).
tval(Q, u) :- q_attempted(Q, _, _, _, _), mk(Q, neither).
tval(Q, t) :- q_completed(Q, _, _, _, _), mk(Q, supported).
tval(Q, u) :- q_completed(Q, _, _, _, _), mk(Q, neither).
tval(Q, u) :- q_state(Q, _, _, _, _), mk(Q, zero).
tval(Q, b) :- q_state(Q, _, _, _, _), mk(Q, both).
tval(Q, u) :- q_state(Q, _, _, _, _), mk(Q, stale).
tval(Q, f) :- q_state(Q, _, _, _, _), mk(Q, refute).
tval(Q, t) :- q_state(Q, _, _, _, _), mk(Q, support).
tval(Q, u) :- q_state(Q, _, _, _, _), mk(Q, nonev).
tval(Q, t) :- q_state_hist(Q, _, _, _, _), mk(Q, support).
tval(Q, u) :- q_state_hist(Q, _, _, _, _), mk(Q, nonev).
tval(Q, u) :- q_cmp(Q, _, _, _, _, _), mk(Q, zero).
tval(Q, b) :- q_cmp(Q, _, _, _, _, _), mk(Q, both).
tval(Q, u) :- q_cmp(Q, _, _, _, _, _), mk(Q, stale).
tval(Q, f) :- q_cmp(Q, _, _, _, _, _), mk(Q, refute).
tval(Q, t) :- q_cmp(Q, _, _, _, _, _), mk(Q, support).
tval(Q, u) :- q_cmp(Q, _, _, _, _, _), mk(Q, nonev).

% ---- condition trees: recursive native folds
% (tvdom binding: s(CASP) instantiates unbound variables in positive body
% literals over the whole term universe, producing spurious answers; the
% value domain is bound explicitly before every tval lookup)
cval(N, V) :- cnode(N, leaf), cleaf(N, Q, 0), tvdom(V), tval(Q, V).
cval(N, V) :- cnode(N, leaf), cleaf(N, Q, 1), tvdom(W), tval(Q, W), negv(W, V).
cval(N, V) :- cnode(N, negnode), cnot(N, M), cval(M, W), negv(W, V).
cval(N, V) :- cnode(N, all, Kids), fold_conj(Kids, V).
cval(N, V) :- cnode(N, any, Kids), fold_disj(Kids, V).
fold_conj([], t).
fold_conj([K|Rest], V) :- cval(K, V1), fold_conj(Rest, V2), conjv(V1, V2, V).
fold_disj([], f).
fold_disj([K|Rest], V) :- cval(K, V1), fold_disj(Rest, V2), disjv(V1, V2, V).

% ---- obligations: antecedent fold, safety, world error
antv(O, V) :- obl(O, _, _, _), obl_root(O, N), cval(N, V).
tvv(O, t) :- obl(O, _, _, _), obl_target_inv(O).
tvv(O, V) :- obl(O, _, _, _), obl_target_q(O, Q), tvdom(V), tval(Q, V).
%   FORBID: saf = NOT(ant AND target);  REQUIRE: saf = NOT(ant AND NOT target)
saf(O, V) :- obl(O, _, _, _), obl_kind(O, forbid), antv(O, A), tvv(O, T),
             conjv(A, T, C), negv(C, V).
saf(O, V) :- obl(O, _, _, _), obl_kind(O, require), antv(O, A), tvv(O, T),
             negv(T, NT), conjv(A, NT, C), negv(C, V).

% ---- per-interpretation world error values (goal-directed; no choice
%      rules in s(CASP))
wfalse(I) :- interp(I), saf(O, f), obl(O, I, _, _).
wboth(I) :- interp(I), saf(O, b), obl(O, I, _, _).
wunk1(I) :- interp(I), saf(O, u), obl(O, I, _, _).
wunk2(I) :- interp(I), marker(I, _).
has_obl(I) :- obl(_, I, _, _).
werr(I, t) :- wfalse(I).
werr(I, b) :- interp(I), wboth(I), nq(I).
werr(I, u) :- interp(I), nq(I), nb(I), wunk1(I).
werr(I, u) :- interp(I), nq(I), nb(I), wunk2(I).
werr(I, f) :- interp(I), nq(I), nb(I), nu(I), nv(I), has_obl(I).
werr(I, f) :- interp(I), nq(I), nb(I), nu(I), nv(I), no_obl(I).
% single-clause DEFINED helpers for the negations above
nq(I) :- interp(I), not wfalse(I).
nb(I) :- interp(I), not wboth(I).
nu(I) :- interp(I), not wunk1(I).
nv(I) :- interp(I), not wunk2(I).
no_obl(I) :- interp(I), not has_obl(I).
"""

RUNNER = r"""
% ===================== single-query runner (plain Prolog) =================
% s(CASP) 1.1.4 is NOT re-entrant: the second scasp/2 call in one session
% fails.  One query per process; the Python side drives the sequence.
:- use_module(library(http/json)).

one_query(OutPath, Goal, Kind, Key) :-
    setup_call_cleanup(
        open(OutPath, write, Out),
        ( catch((scasp(Goal, [tree(T)]),
                 with_output_to(string(S),
                                write_term(T, [max_depth(7), quoted(false)])),
                 json_write(Out, json{kind:Kind, key:Key, ok:true, tree:S}),
                 nl(Out)),
               Err,
               ( message_to_string(Err, Msg),
                 json_write(Out, json{kind:Kind, key:Key, ok:false,
                                      error:Msg}), nl(Out) )) ),
        close(Out)),
    halt.

% compute per-interpretation world error values with PLAIN Prolog over the
% scasp-derivable safety values: the fold is stratified negation (sound),
% and s(CASP) 1.1.4's goal-directed negation over the recursive semantic
% layer (wfalse/1 etc.) does not terminate correctly.  saf/2 values are
% enumerated by the same tabling scasp uses for its answers.
worlds(OutPath) :-
    setup_call_cleanup(
        open(OutPath, write, Out),
        ( forall(interp(I),
                 ( findall(V, ( obl(O, I, _, _), saf(O, V) ), Vs),
                   ( marker(I, _) -> Mk = [u] ; Mk = [] ),
                   append(Vs, Mk, All),
                   ( member(f, All) -> Ev = t
                   ; member(b, All) -> Ev = b
                   ; member(u, All) -> Ev = u
                   ; All == [] -> Ev = f
                   ; Ev = f ),
                   json_write(Out, json{kind:world, interp:I, value:Ev}),
                   nl(Out) )) ),
        close(Out)),
    halt.

% enumerate a POSITIVE predicate with plain findall (support listing)
enum(OutPath, sup) :-
    setup_call_cleanup(
        open(OutPath, write, Out),
        ( forall(sup(Q, F),
                 ( json_write(Out, json{kind:sup, q:Q, fact:F}), nl(Out) )) ),
        close(Out)),
    halt.
enum(OutPath, ref) :-
    setup_call_cleanup(
        open(OutPath, write, Out),
        ( forall(ref(Q),
                 ( json_write(Out, json{kind:ref, q:Q}), nl(Out) )) ),
        close(Out)),
    halt.
"""


# ------------------------------------------------------- program generation

class _Program:
    def __init__(self):
        self.data: list[str] = []
        self.queries: dict[str, str] = {}
        self.query_atoms: dict[str, NeutralAtom] = {}
        self.query_times: dict[str, int] = {}
        self.rules: list[str] = []          # generated RULE lines (not facts)

    def line(self, text: str) -> None:
        self.data.append(text)

    def rule(self, text: str) -> None:
        self.rules.append(text)

    def query_id(self, atom: NeutralAtom, resolved_t: int) -> str:
        t = resolved_t if atom.time_index == -1 else atom.time_index
        key = _resolved_key(atom, t)
        if key in self.queries.values():
            return next(q for q, k in self.queries.items() if k == key)
        qid = f"q{len(self.queries)}"
        self.queries[qid] = key
        self.query_atoms[qid] = atom
        self.query_times[qid] = t
        if atom.kind == "attempted":
            self.line(f"q_attempted({qid}, {_atom(atom.actor)}, {_atom(atom.entity)}, "
                      f"{_atom(atom.action)}, {t}).")
        elif atom.kind == "completed":
            self.line(f"q_completed({qid}, {_atom(atom.actor)}, {_atom(atom.entity)}, "
                      f"{_atom(atom.action)}, {t}).")
        elif atom.kind == "state":
            self.line(f"q_state({qid}, {_atom(atom.entity)}, {_atom(atom.predicate)}, "
                      f"{_val(atom.expected)}, {t}).")
        elif atom.kind == "state_hist":
            self.line(f"q_state_hist({qid}, {_atom(atom.entity)}, {_atom(atom.predicate)}, "
                      f"{_val(atom.expected)}, {t}).")
        elif atom.kind == "comparison":
            c = atom.comparison
            op = {"EQ": "eq", "NE": "ne", "LT": "lt", "LE": "le",
                  "GT": "gt", "GE": "ge"}[c.op]
            self.line(f"q_cmp({qid}, {_atom(atom.entity)}, {_atom(c.predicate)}, "
                      f"{op}, {_val(c.rhs_literal)}, {t}).")
        elif atom.kind == "cardinality":
            c = atom.cardinality
            op = {"AT_LEAST": "at_least", "AT_MOST": "at_most",
                  "EXACTLY": "exactly"}[c.op]
            self.line(f"q_card({qid}, {_atom(atom.actor)}, {_atom(atom.entity)}, "
                      f"{_atom(c.subject)}, {op}, {c.count}, {t}).")
            self._emit_card_rules(qid, atom)
        else:
            raise ValueError(f"atom kind {atom.kind}")
        return qid

    def _emit_card_rules(self, qid: str, atom: NeutralAtom):
        """Cardinality tval rules over POSITIVE adapter markers (mk/2)."""
        c = atom.cardinality
        count = c.count
        n1 = count + 1
        if c.op == "AT_LEAST":
            self.rule(f"tval({qid}, t) :- mk({qid}, ge_{count}).")
            self.rule(f"tval({qid}, f) :- mk({qid}, complete), "
                      f"mk({qid}, nge_{count}).")
            self.rule(f"tval({qid}, u) :- mk({qid}, nocomplete), "
                      f"mk({qid}, nge_{count}).")
        elif c.op == "AT_MOST":
            self.rule(f"tval({qid}, t) :- mk({qid}, complete), "
                      f"mk({qid}, nge_{n1}).")
            self.rule(f"tval({qid}, f) :- mk({qid}, ge_{n1}).")
            self.rule(f"tval({qid}, u) :- mk({qid}, nocomplete).")
        else:  # EXACTLY
            self.rule(f"tval({qid}, t) :- mk({qid}, complete), "
                      f"mk({qid}, ge_{count}), mk({qid}, nge_{n1}).")
            self.rule(f"tval({qid}, f) :- mk({qid}, complete), "
                      f"mk({qid}, ge_{n1}).")
            self.rule(f"tval({qid}, f) :- mk({qid}, complete), "
                      f"mk({qid}, nge_{count}).")
            self.rule(f"tval({qid}, u) :- mk({qid}, nocomplete).")



def _emit_facts(ci: NeutralCoreInput, prog: _Program) -> None:
    for f in ci.facts:
        fid = _fid(f.fact_id)
        actor, entity, pred = _atom(f.actor), _atom(f.entity), _atom(f.predicate)
        if f.kind == "ACTION_ATTEMPTED":
            prog.line(f"attempt({fid}, {actor}, {entity}, {pred}, "
                      f"{_atom(f.call_id or '')}, {f.event_index}).")
        elif f.kind == "ACTION_COMPLETED":
            prog.line(f"completed({fid}, {actor}, {entity}, {pred}, "
                      f"{_atom(f.call_id or '')}, {f.event_index}).")
        elif f.kind == "ACTION_FAILED":
            prog.line(f"failed({fid}, {actor}, {entity}, {pred}, "
                      f"{_atom(f.call_id or '')}, {f.event_index}).")
        elif f.kind in STATE_KINDS:
            prog.line(f"obs_row({fid}, {actor}, {entity}, {pred}, "
                      f"{_val(f.value)}, {f.event_index}).")
        elif f.kind == "EFFECT":
            prog.line(f"eff_row({fid}, {actor}, {entity}, {pred}, "
                      f"{_val(f.value)}, {f.event_index}).")
        else:
            prog.line(f"inert_row({fid}, {_atom(f.kind)}, {actor}, {entity}, "
                      f"{pred}, {f.event_index}).")
    # input projections as ground facts (translation layer)
    entities = {f.entity for f in ci.facts if f.entity != "*"}
    for entity in sorted(entities):
        prog.line(f"ent({_atom(entity)}).")
    for f in ci.facts:
        if f.kind in ACTION_KINDS:
            prog.line(f"act_hit({_fid(f.fact_id)}, {_atom(f.actor)}, "
                      f"{_atom(f.entity)}, {_atom(f.predicate)}, {f.event_index}).")
            prog.line(f"mut({f.event_index}).")
    for f in ci.facts:
        if f.kind in STATE_KINDS or f.kind == "EFFECT":
            prog.line(f"row({_fid(f.fact_id)}, {_atom(f.entity)}, "
                      f"{_atom(f.predicate)}, {_val(f.value)}, {f.event_index}).")
    if ci.history_complete:
        prog.line("hist_complete.")
    if all(f.actor not in ("", "unknown") for f in ci.facts):
        prog.line("known_actors.")
    for interp in ci.interpretations:
        prog.line(f"interp({_atom(interp.interp_id)}).")
        for marker in interp.unresolved:
            prog.line(f"marker({_atom(interp.interp_id)}, {_atom(marker)}).")


class _TreeEmitter:
    def __init__(self, prog: _Program):
        self.prog = prog
        self.counter = 0

    def node(self, tree: CondNode | None, negate: bool, bound: int) -> str:
        return self._emit(tree, negate, bound)

    def _emit(self, node: CondNode, negate: bool, bound: int) -> str:
        self.counter += 1
        nid = f"n{self.counter}"
        if node.atom is not None:
            qid = self.prog.query_id(node.atom, bound)
            self.prog.line(f"cnode({nid}, leaf).")
            self.prog.line(f"cleaf({nid}, {qid}, 0).")
            return self._wrap(nid, negate)
        if node.not_ is not None:
            child = self._emit(node.not_, False, bound)
            if negate:
                return child          # not(not X) == X
            self.counter += 1
            pid = f"n{self.counter}"
            self.prog.line(f"cnode({pid}, negnode).")
            self.prog.line(f"cnot({pid}, {child}).")
            return pid
        kind = "all" if node.all_ is not None else "any"
        children = node.all_ if node.all_ is not None else node.any_
        child_ids = [self._emit(child, False, bound) for child in children]
        kids = "[" + ",".join(child_ids) + "]"
        self.prog.line(f"cnode({nid}, {kind}, {kids}).")
        return self._wrap(nid, negate)

    def _wrap(self, nid: str, negate: bool) -> str:
        if not negate:
            return nid
        self.counter += 1
        pid = f"n{self.counter}"
        self.prog.line(f"cnode({pid}, negnode).")
        self.prog.line(f"cnot({pid}, {nid}).")
        return pid


def _build_rule_tree(rule, bound: int, emitter: _TreeEmitter) -> str | None:
    parts: list[str] = []
    if rule.conditions is not None:
        parts.append(emitter.node(rule.conditions, False, bound))
    for exc in rule.exceptions:
        parts.append(emitter.node(exc, True, bound))
    if rule.temporal in ("BEFORE", "UNTIL"):
        anchor = NeutralAtom(f"anchor:{rule.temporal_anchor_action}", "attempted",
                             action=rule.temporal_anchor_action,
                             entity=rule.temporal_anchor_entity,
                             actor="assistant", time_index=-1)
        parts.append(emitter.node(CondNode(atom=anchor), True, bound))
    elif rule.temporal == "AFTER":
        anchor = NeutralAtom(f"anchor:{rule.temporal_anchor_action}", "attempted",
                             action=rule.temporal_anchor_action,
                             entity=rule.temporal_anchor_entity,
                             actor="assistant", time_index=-1)
        parts.append(emitter.node(CondNode(atom=anchor), False, bound))
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    emitter.counter += 1
    root = f"n{emitter.counter}"
    kids = "[" + ",".join(parts) + "]"
    emitter.prog.line(f"cnode({root}, all, {kids}).")
    return root


def _effect_bound(ci: NeutralCoreInput, fact) -> int:
    bound = fact.event_index
    for other in ci.facts:
        if other.call_id and fact.call_id and other.call_id == fact.call_id \
                and other.event_index > bound:
            bound = other.event_index
    return bound


def _emit_obligations(ci: NeutralCoreInput, prog: _Program,
                      emitter: _TreeEmitter) -> list[tuple]:
    emitted = []
    max_t = max((f.event_index for f in ci.facts), default=0)
    for interp in ci.interpretations:
        for rule in interp.rules:
            if rule.modality == "FORBID":
                targets = [f for f in ci.facts
                           if f.region == "target" and f.kind in ACTION_KINDS
                           and f.predicate == rule.action
                           and (rule.entity == "*" or f.entity == rule.entity)
                           and f.actor == rule.actor]
                if not targets:
                    continue        # vacuously satisfied (S4)
                for f in targets:
                    oid = f"o{len(emitted)}"
                    bound = f.event_index - 1      # just before the gate (S4)
                    root = _build_rule_tree(rule, bound, emitter)
                    prog.line(f"obl({oid}, {_atom(interp.interp_id)}, "
                              f"{_atom(rule.rule_id)}, {_atom(f.fact_id)}).")
                    prog.line(f"obl_kind({oid}, forbid).")
                    if root is not None:
                        prog.line(f"obl_root({oid}, {root}).")
                    else:
                        prog.line(f"antv({oid}, t).")
                    if rule.target_level == "ATTEMPT":
                        prog.line(f"obl_target_inv({oid}).")
                    else:
                        qid = prog.query_id(
                            NeutralAtom(f"c:{rule.rule_id}:{f.fact_id}", "completed",
                                        action=rule.action, entity=f.entity,
                                        actor=rule.actor, time_index=END),
                            _effect_bound(ci, f))
                        prog.line(f"obl_target_q({oid}, {qid}).")
                    emitted.append((oid, interp.interp_id, rule.rule_id, f.fact_id))
            else:
                oid = f"o{len(emitted)}"
                root = _build_rule_tree(rule, max_t, emitter)
                atom = (NeutralAtom(f"r:{rule.rule_id}", "attempted",
                                    action=rule.action, entity=rule.entity,
                                    actor=rule.actor, time_index=END)
                        if rule.target_level == "ATTEMPT" else
                        NeutralAtom(f"rc:{rule.rule_id}", "completed",
                                    action=rule.action, entity=rule.entity,
                                    actor=rule.actor, time_index=END))
                qid = prog.query_id(atom, max_t)
                prog.line(f"obl({oid}, {_atom(interp.interp_id)}, "
                          f"{_atom(rule.rule_id)}, exist).")
                prog.line(f"obl_kind({oid}, require).")
                prog.line(f"obl_target_q({oid}, {qid}).")
                if root is not None:
                    prog.line(f"obl_root({oid}, {root}).")
                else:
                    prog.line(f"antv({oid}, t).")
                emitted.append((oid, interp.interp_id, rule.rule_id, "exist"))
    return emitted


# -------------------------------------------------- adapter evidence joins

def _same_type(a_json: str, b_json: str) -> bool:
    try:
        return type(json.loads(a_json)) is type(json.loads(b_json))
    except (ValueError, TypeError):
        return False


def _cmp_typed(op: str, a_json: str, b_json: str) -> bool:
    try:
        a, b = json.loads(a_json), json.loads(b_json)
    except (ValueError, TypeError):
        return False
    if op in ("EQ", "NE"):
        return type(a) is type(b)
    return (isinstance(a, (int, float)) and not isinstance(a, bool)
            and isinstance(b, (int, float)) and not isinstance(b, bool))


def _cmp_holds(op: str, a_json: str, b_json: str) -> bool:
    if not _cmp_typed(op, a_json, b_json):
        return False
    a, b = json.loads(a_json), json.loads(b_json)
    return {"EQ": lambda: a == b, "NE": lambda: a != b,
            "LT": lambda: a < b, "LE": lambda: a <= b,
            "GT": lambda: a > b, "GE": lambda: a >= b}[op]()


def _enumerate_evidence(ci: NeutralCoreInput, prog: _Program) -> None:
    """Adapter-side evidence joins (S2) -> ground marker facts mk/2 (+ sup,
    ref).  s(CASP) 1.1.4's dual generation cannot evaluate fact joins under
    its negation transformation (six documented engine findings)."""
    action_facts = [f for f in ci.facts if f.kind in ACTION_KINDS]
    state_facts = [f for f in ci.facts if f.kind in STATE_KINDS or f.kind == "EFFECT"]
    known_actors = all(f.actor not in ("", "unknown") for f in ci.facts)
    mut_positions = sorted({f.event_index for f in ci.facts
                            if f.kind in ACTION_KINDS})
    for qid, atom in list(prog.query_atoms.items()):
        t = prog.query_times.get(qid, atom.time_index)
        if atom.kind == "attempted":
            support = [f for f in action_facts
                       if f.predicate == atom.action and f.actor == atom.actor
                       and (atom.entity == "*" or f.entity == atom.entity)
                       and f.event_index <= t]
            if support:
                prog.line(f"mk({qid}, supported).")
                for f in dict.fromkeys(support):
                    prog.line(f"sup({qid}, {_fid(f.fact_id)}).")
            elif ci.history_complete and known_actors:
                prog.line(f"mk({qid}, absent).")
                prog.line(f"ref({qid}).")
            else:
                prog.line(f"mk({qid}, neither).")
        elif atom.kind == "completed":
            support = [f for f in ci.facts if f.kind == "ACTION_COMPLETED"
                       and f.predicate == atom.action and f.actor == atom.actor
                       and (atom.entity == "*" or f.entity == atom.entity)
                       and f.event_index <= t]
            for eff in ci.facts:
                if eff.kind != "EFFECT" or eff.event_index > t:
                    continue
                if atom.entity != "*" and eff.entity != atom.entity:
                    continue
                for other in action_facts:
                    if (other.call_id and other.call_id == eff.call_id
                            and other.predicate == atom.action
                            and other.actor == atom.actor
                            and other.event_index <= t):
                        support.append(eff)
                        break
            if support:
                prog.line(f"mk({qid}, supported).")
                for f in dict.fromkeys(support):
                    prog.line(f"sup({qid}, {_fid(f.fact_id)}).")
            else:
                prog.line(f"mk({qid}, neither).")
        elif atom.kind in ("state", "state_hist", "comparison"):
            pred = (atom.comparison.predicate if atom.kind == "comparison"
                    else atom.predicate)
            rows = [(f.event_index, _canon(f.value).decode("utf-8"))
                    for f in state_facts
                    if f.predicate == pred
                    and (atom.entity == "*" or f.entity == atom.entity)
                    and f.event_index <= t]
            if atom.kind == "state_hist":
                expected = _canon(atom.expected).decode("utf-8")
                if any(v == expected for _, v in rows):
                    prog.line(f"mk({qid}, support).")
                else:
                    prog.line(f"mk({qid}, nonev).")
                continue
            if not rows:
                prog.line(f"mk({qid}, zero).")
                continue
            latest = max(r[0] for r in rows)
            latest_rows = [r for r in rows if r[0] == latest]
            if atom.kind == "state":
                expected = _canon(atom.expected).decode("utf-8")
                up = [r for r in latest_rows if r[1] == expected]
                ref = [r for r in latest_rows if _same_type(r[1], expected)
                       and r[1] != expected]
            else:
                c = atom.comparison
                rhs = _canon(c.rhs_literal).decode("utf-8")
                up = [r for r in latest_rows if _cmp_holds(c.op, r[1], rhs)]
                ref = [r for r in latest_rows
                       if _cmp_typed(c.op, r[1], rhs)
                       and not _cmp_holds(c.op, r[1], rhs)]
            stale = any(latest < m <= t for m in mut_positions)
            if up and ref:
                prog.line(f"mk({qid}, both).")
            elif stale:
                prog.line(f"mk({qid}, stale).")
            elif up:
                prog.line(f"mk({qid}, support).")
            elif ref:
                prog.line(f"mk({qid}, refute).")
            else:
                prog.line(f"mk({qid}, nonev).")
        elif atom.kind == "cardinality":
            c = atom.cardinality
            matching = sorted({f.event_index for f in action_facts
                               if f.predicate == c.subject
                               and (atom.entity == "*" or f.entity == atom.entity)
                               and f.event_index <= t})
            for k in (c.count, c.count + 1):
                if len(matching) >= k:
                    prog.line(f"mk({qid}, ge_{k}).")
                else:
                    prog.line(f"mk({qid}, nge_{k}).")
            if ci.history_complete:
                prog.line(f"mk({qid}, complete).")
            else:
                prog.line(f"mk({qid}, nocomplete).")


# ------------------------------------------------------------------ running

class _ScaspSession:
    """One program file; one swipl process PER QUERY (s(CASP) 1.1.4 is not
    re-entrant: only the first scasp/2 call in a session works)."""

    def __init__(self, program_text: str, timeout_s: int = 45):
        self._td = tempfile.TemporaryDirectory(prefix="bakeoff_scasp_")
        self.dir = Path(self._td.name)
        (self.dir / "program.pl").write_text(program_text, encoding="utf-8")
        self.timeout_s = timeout_s
        self.env = dict(os.environ)
        self.env["LD_LIBRARY_PATH"] = (LD_LIBRARY_PATH + ":"
                                       + self.env.get("LD_LIBRARY_PATH", ""))

    def close(self):
        self._td.cleanup()

    def _safe_name(self, key: str) -> str:
        return "".join(ch if ch.isalnum() else "_" for ch in key)[:80]

    def query(self, goal: str, kind: str, key: str) -> dict:
        out_path = self.dir / f"out_{self._safe_name(key)}.json"
        runner = f"one_query('{out_path}', {goal}, {kind}, '{key}')"
        try:
            subprocess.run(
                [SWIPL, "-q", "-t", "halt", "-g", runner, "-s",
                 str(self.dir / "program.pl")],
                capture_output=True, text=True, timeout=self.timeout_s,
                env=self.env, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return {"kind": kind, "key": key, "ok": False, "error": "timeout"}
        if out_path.exists():
            text = out_path.read_text(encoding="utf-8").strip()
            if text:
                try:
                    return json.loads(text)
                except ValueError:
                    return {"kind": kind, "key": key, "ok": False,
                            "error": "bad-json"}
        return {"kind": kind, "key": key, "ok": False, "error": "no-output"}

    def worlds(self) -> list[tuple[str, str]]:
        out_path = self.dir / "worlds.jsonl"
        runner = f"worlds('{out_path}')"
        try:
            subprocess.run(
                [SWIPL, "-q", "-t", "halt", "-g", runner, "-s",
                 str(self.dir / "program.pl")],
                capture_output=True, text=True, timeout=self.timeout_s,
                env=self.env, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return []
        rows: list[tuple[str, str]] = []
        if out_path.exists():
            for line in out_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        row = json.loads(line)
                        rows.append((row["interp"], row["value"]))
                    except (ValueError, KeyError):
                        pass
        return rows

    def enum(self, which: str) -> list[dict]:
        out_path = self.dir / f"enum_{which}.jsonl"
        runner = f"enum('{out_path}', {which})"
        try:
            subprocess.run(
                [SWIPL, "-q", "-t", "halt", "-g", runner, "-s",
                 str(self.dir / "program.pl")],
                capture_output=True, text=True, timeout=self.timeout_s,
                env=self.env, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return []
        rows = []
        if out_path.exists():
            for line in out_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        pass
        return rows


DYNAMIC_DECLS = """:- dynamic([ent/1, mut/1, row/5, act_hit/5, attempt/6,
           completed/6, failed/6, obs_row/6, eff_row/6, inert_row/6,
           interp/1, marker/2, obl/4, obl_kind/2, obl_root/2,
           obl_target_q/2, obl_target_inv/1, antv/2, q_attempted/5,
           q_completed/5, q_state/5, q_state_hist/5, q_cmp/6, q_card/7,
           mk/2, sup/2, ref/1, cnode/2, cnode/3, cleaf/3, cnot/2,
           hist_complete/0, known_actors/0]).
"""


def _program_text(ci: NeutralCoreInput, prog: _Program) -> str:
    # FACTS (incl. adapter markers) BEFORE RULES: s(CASP) 1.1.4 mis-handles
    # ground facts that appear after the rules referencing them.
    # dynamic declarations: data predicates are emitted per-case; a kind
    # that is absent must not make the plain-Prolog runner crash with an
    # existence error.
    parts = [f":- use_module('{SCASP_PL}').", DYNAMIC_DECLS]
    parts.append("\n".join(prog.data))
    parts.append(TEMPLATE)
    if prog.rules:
        parts.append(":- discontiguous(tval/2).")
        parts.append("\n".join(prog.rules))
    parts.append(RUNNER)
    return "\n".join(parts) + "\n"


def _status_from_worlds(worlds: list[tuple[str, str]]) -> str:
    if not worlds:
        return "UNRESOLVED"
    values = [w[1] for w in worlds]
    if "b" in values:
        return "INCONSISTENT"
    if "u" in values:
        return "UNRESOLVED"
    if all(v == "t" for v in values):
        return "PROVED_ERROR"
    if all(v == "f" for v in values):
        return "PROVED_NO_ERROR"
    return "UNRESOLVED"


def evaluate(ci: NeutralCoreInput) -> BackendResult:
    started = time.perf_counter()
    if not ci.interpretations:
        return BackendResult(backend="scasp", status="UNRESOLVED",
                             input_content_hash=ci.content_hash(),
                             notes="empty interpretation space")
    prog = _Program()
    _emit_facts(ci, prog)
    emitter = _TreeEmitter(prog)
    obligations = _emit_obligations(ci, prog, emitter)
    _enumerate_evidence(ci, prog)
    text = _program_text(ci, prog)
    session = _ScaspSession(text)
    try:
        # world error values: plain-Prolog stratified fold over the
        # scasp-derivable saf/2 values (see RUNNER worlds/1)
        worlds: list[tuple[str, str]] = session.worlds()
        errors: list[str] = []

        saf_values: dict[str, str] = {}
        trees: dict[str, str] = {}
        for oid, *_ in obligations:
            for v in _VALUES:
                row = session.query(f"saf({oid}, {v})", "saf", f"{oid}:{v}")
                if row.get("ok"):
                    saf_values[oid] = v
                    trees[oid] = row.get("tree", "")[:4000]
                    break

        sup_map: dict[str, list[str]] = {}
        for row in session.enum("sup"):
            sup_map.setdefault(row["q"], []).append(row["fact"])
        ref_set = {row["q"] for row in session.enum("ref")}

        status = _status_from_worlds(worlds)
        world_results = tuple(WorldResult(i, _TRUTH_MAP.get(v, v))
                              for i, v in worlds)
        witnesses = _witnesses(saf_values, trees, sup_map, ref_set, prog,
                               obligations)
        runtime_ms = (time.perf_counter() - started) * 1000.0
        notes = []
        if errors:
            notes.append(f"query_errors={len(errors)}")
        notes.append(f"queries={len(ci.interpretations) * 4 + len(obligations) * 4}")
        return BackendResult(backend="scasp", status=status,
                             worlds=world_results, witnesses=witnesses,
                             runtime_ms=runtime_ms,
                             input_content_hash=ci.content_hash(),
                             notes="; ".join(notes))
    finally:
        session.close()


def probe(ci: NeutralCoreInput, atoms: list[NeutralAtom]) -> list[PrimitiveResult]:
    prog = _Program()
    _emit_facts(ci, prog)
    qid_of = {}
    for atom in atoms:
        qid_of[atom] = prog.query_id(atom, atom.time_index)
    _enumerate_evidence(ci, prog)
    text = _program_text(ci, prog)
    session = _ScaspSession(text)
    try:
        sup_map: dict[str, list[str]] = {}
        for row in session.enum("sup"):
            sup_map.setdefault(row["q"], []).append(row["fact"])
        ref_set = {row["q"] for row in session.enum("ref")}
        out = []
        for atom in atoms:
            qid = qid_of[atom]
            value = "u"
            for v in _VALUES:
                row = session.query(f"tval({qid}, {v})", "tval", f"{qid}:{v}")
                if row.get("ok"):
                    value = v
                    break
            out.append(PrimitiveResult(
                atom.key(), _TRUTH_MAP.get(value, "UNKNOWN"),
                tuple(dict.fromkeys(sup_map.get(qid, []))),
                ("absence-proof",) if qid in ref_set else ()))
        return out
    finally:
        session.close()


def _witnesses(saf_values, trees, sup_map, ref_set, prog, obligations):
    out = []
    for oid, interp_id, rule_id, fact_id in obligations:
        v = saf_values.get(oid, "u")
        conclusion = _TRUTH_MAP.get(v, "UNKNOWN")
        leaf_qs = _leaf_queries(prog, oid)
        sups, refs, unks = [], [], []
        for qid in leaf_qs:
            sups.extend(sup_map.get(qid, []))
            if qid in ref_set:
                refs.append("absence-proof")
            tree = trees.get(oid, "") or ""
            if "u(" in tree or "not_" in tree:
                unks.append(prog.queries.get(qid, qid))
        out.append(BackendWitness(
            rule_id=rule_id, interpretation_id=interp_id, conclusion=conclusion,
            supporting_fact_ids=tuple(dict.fromkeys(sups))[:8],
            refuting_fact_ids=tuple(dict.fromkeys(refs))[:8],
            unknown_dependencies=tuple(dict.fromkeys(unks))[:8],
            engine_native_explanation=("s(CASP) justification tree: "
                                       + trees.get(oid, "")[:600])
            if trees.get(oid) else f"s(CASP) derivation for {oid}"))
    return tuple(out)


def _leaf_queries(prog: _Program, oid: str) -> list[str]:
    root = None
    for line in prog.data:
        if line.startswith(f"obl_root({oid},"):
            root = line[len(f"obl_root({oid}, "):-2]
    if root is None:
        return []
    children: dict[str, list[str]] = {}
    leaves: dict[str, str] = {}
    nots: dict[str, str] = {}
    for line in prog.data:
        if line.startswith("cnode("):
            rest = line[6:-2]
            parts = [p.strip() for p in rest.split(",", 2)]
            nid, kind = parts[0], parts[1]
            if kind in ("all", "any"):
                kids = parts[2].strip("[]").split(",")
                children[nid] = [k.strip() for k in kids if k.strip()]
        elif line.startswith("cleaf("):
            rest = line[6:-2]
            nid, qid, neg = [p.strip() for p in rest.split(",")]
            leaves[nid] = qid
        elif line.startswith("cnot("):
            rest = line[5:-2]
            nid, cid = [p.strip() for p in rest.split(",")]
            nots[nid] = cid
    out = []

    def visit(node):
        if node in leaves:
            out.append(leaves[node])
        elif node in nots:
            visit(nots[node])
        elif node in children:
            for child in children[node]:
                visit(child)

    visit(root)
    return out
