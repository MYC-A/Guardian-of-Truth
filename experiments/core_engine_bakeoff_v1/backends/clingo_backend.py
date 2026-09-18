"""core_engine_bakeoff_v1 — backend: CLINGO (ASP, Potassco).

NeutralCoreInput -> one ASP program (generic template + data facts) -> clingo
(Python API, in-process) -> stable models = interpretation worlds -> per-model
world error values -> consensus.

Native capabilities used (no Python re-implementation of engine internals):
  * joins over fact relations
  * arithmetic comparisons (<, <=, >, >=) for numeric state
  * aggregates: #max (latest evidence position), #count (cardinality)
  * RECURSIVE rules: condition trees fold bottom-up through conjunction /
    disjunction tables (native recursion, no per-node Python evaluation)
  * default negation guarded by EXPLICIT premises (hist_complete,
    known_actors) so ASP's closed world can NEVER silently turn UNKNOWN
    into FALSE
  * choice rule `1 { active(I) : interp(I) } 1` -> one stable model per
    admissible interpretation (worlds)
  * brave/cautious consequences computed from the model set (union /
    intersection — exactly the enumeration semantics of clingo's brave and
    cautious modes) and CHECKED against the consensus status: the
    equivalence is tested per scenario, not assumed

Four-valued evidence is explicit: every query Q derives tval(Q, V) from
support/refute evidence (sup/ref with originating fact ids, feeding
witnesses); absence of a fact is refutation only under the absence-proof
rule.  The adapter is a translation layer only: facts, query descriptors,
obligation records and condition-tree nodes are ground data.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
for p in (str(REPO / "src"), str(HERE.parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import clingo

from neutral_types import (BackendResult, BackendWitness, CondNode,
                           NeutralAtom, NeutralCoreInput, PrimitiveResult,
                           WorldResult)

ACTION_KINDS = ("ACTION_ATTEMPTED", "ACTION_COMPLETED", "ACTION_FAILED")
STATE_KINDS = ("STATE_OBSERVATION", "FIELD_VALUE")

TRUTH_VALUES = ("TRUE", "FALSE", "BOTH", "UNKNOWN")
END = 10**9

_ASP_TRUTH = {"true": "TRUE", "false": "FALSE", "both": "BOTH", "unk": "UNKNOWN"}


def _asp_truth(symbol: str) -> str:
    """Map clingo lowercase truth constants to the neutral truth names."""
    return _ASP_TRUTH.get(symbol, symbol)


# ------------------------------------------------------------ value encoding

def _term(value) -> str:
    if isinstance(value, bool):
        return f"bool({1 if value else 0})"
    if isinstance(value, (int, float)):
        return f"num({value})"
    if isinstance(value, str):
        return f'str("{_esc(value)}")'
    return f'json("{_esc(str(value))}")'


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _sym(value: str) -> str:
    return f'"{_esc(str(value))}"'


# ------------------------------------------------------------ ASP template

TEMPLATE = r"""
% ================= generic four-valued evidence core (v1) =================
% value tags: num(N) | str(S) | bool(B);  truth: true false both unk

% value-domain grounding (facts with free variables are unsafe in ASP)
valsrc(V) :- sval(_, V).
valsrc(V) :- q_state(_, _, _, V, _).
valsrc(V) :- q_state_hist(_, _, _, V, _).
valsrc(V) :- q_cmp(_, _, _, _, V, _).
vmatch(V, V) :- valsrc(V).
vtype(num(X), num(Y)) :- valsrc(num(X)), valsrc(num(Y)).
vtype(str(X), str(Y)) :- valsrc(str(X)), valsrc(str(Y)).
vtype(bool(X), bool(Y)) :- valsrc(bool(X)), valsrc(bool(Y)).

% ---- four-valued connective tables
neg(true, false). neg(false, true). neg(both, both). neg(unk, unk).
conj(true, true, true).
conj(true, false, false).
conj(true, both, both).
conj(true, unk, unk).
tvdom(true). tvdom(false). tvdom(both). tvdom(unk).
conj(false, X, false) :- tvdom(X).
conj(both, true, both).
conj(both, false, false).
conj(both, both, both).
conj(both, unk, both).
conj(unk, true, unk).
conj(unk, false, false).
conj(unk, both, both).
conj(unk, unk, unk).
disj(A, B, C) :- neg(A, NA), neg(B, NB), conj(NA, NB, NAB), neg(NAB, C).

% ---- entity matching (wildcard * matches every mentioned entity)
ent(E) :- attempt_fact(_, _, E, _, _).
ent(E) :- completed_fact(_, _, E, _, _).
ent(E) :- failed_fact(_, _, E, _, _).
ent(E) :- state_fact(_, _, E, _, _).
ent(E) :- effect_fact(_, _, E, _, _, _).
entmatch(E, E) :- ent(E).
entmatch("*", E) :- ent(E).

% ---- mutation positions (attempted actions; observations are pure reads)
mut(I) :- attempt_fact(_, _, _, _, I).
mut(I) :- completed_fact(_, _, _, _, I).
mut(I) :- failed_fact(_, _, _, _, I).

% ---- trusted state rows (observations + effects, with values)
row(F, E, P, V, I) :- state_fact(F, _, E, P, I), sval(F, V).
row(F, E, P, V, I) :- effect_fact(F, _, E, P, I, _), sval(F, V).

% ============================ query evaluation =============================

% ---- generic four-valued completion for evidence-based queries
tval(Q, true) :- q_attempted(Q, _, _, _, _), sup(Q, _), not ref(Q).
tval(Q, false) :- q_attempted(Q, _, _, _, _), ref(Q), not sup(Q, _).
tval(Q, both) :- q_attempted(Q, _, _, _, _), sup(Q, _), ref(Q).
tval(Q, unk) :- q_attempted(Q, _, _, _, _), not sup(Q, _), not ref(Q).
tval(Q, true) :- q_completed(Q, _, _, _, _), sup(Q, _), not ref(Q).
tval(Q, false) :- q_completed(Q, _, _, _, _), ref(Q), not sup(Q, _).
tval(Q, both) :- q_completed(Q, _, _, _, _), sup(Q, _), ref(Q).
tval(Q, unk) :- q_completed(Q, _, _, _, _), not sup(Q, _), not ref(Q).

% ---- attempted(A, E, Actor, <= T)
sup(Q, F) :- q_attempted(Q, A, E, Act, T), attempt_fact(F, A, E2, Act, I),
             entmatch(E, E2), I <= T.
sup(Q, F) :- q_attempted(Q, A, E, Act, T), completed_fact(F, A, E2, Act, I),
             entmatch(E, E2), I <= T.
sup(Q, F) :- q_attempted(Q, A, E, Act, T), failed_fact(F, A, E2, Act, I),
             entmatch(E, E2), I <= T.
% absence refutation ONLY under the explicit premises
ref(Q) :- q_attempted(Q, A, E, Act, T), hist_complete, known_actors,
          not has_attempt_support(Q, A, E, Act, T).
has_attempt_support(Q, A, E, Act, T) :- q_attempted(Q, A, E, Act, T),
          attempt_fact(F, A, E2, Act, I), entmatch(E, E2), I <= T.
has_attempt_support(Q, A, E, Act, T) :- q_attempted(Q, A, E, Act, T),
          completed_fact(F, A, E2, Act, I), entmatch(E, E2), I <= T.
has_attempt_support(Q, A, E, Act, T) :- q_attempted(Q, A, E, Act, T),
          failed_fact(F, A, E2, Act, I), entmatch(E, E2), I <= T.

% ---- completed(A, E, Actor, <= T): completed facts, or trusted effects
%      whose call was an attempt of the same action.  Open world: no
%      refutation path at all.
sup(Q, F) :- q_completed(Q, A, E, Act, T), completed_fact(F, A, E2, Act, I),
             entmatch(E, E2), I <= T.
sup(Q, F) :- q_completed(Q, A, E, Act, T), effect_fact(F, _, E2, P, I, C),
             attempt_call(F2, A, E3, Act, _, C), entmatch(E, E2),
             entmatch(E, E3), I <= T.

% ---- row gathering for current-state queries (state / comparison)
gather(Q, E, P, T) :- q_state(Q, E, P, _, T).
gather(Q, E, P, T) :- q_cmp(Q, E, P, _, _, T).
qrow(Q, F, I) :- gather(Q, E, P, T), row(F, E, P, _, I), I <= T.
has_qrow(Q) :- qrow(Q, _, _).
qmax(Q, M) :- has_qrow(Q), M = #max { I : qrow(Q, _, I) }.
lrow(Q, F) :- qrow(Q, F, I), qmax(Q, I).
later_mut(Q) :- gather(Q, _, _, T), has_qrow(Q), qmax(Q, M),
                mut(J), M < J, J <= T.

% ---- state (LATEST, conservative)
lsup(Q, F) :- q_state(Q, E, P, V, _), lrow(Q, F), row(F, E, P, V2, _),
              vmatch(V, V2).
lref(Q, F) :- q_state(Q, E, P, V, _), lrow(Q, F), row(F, E, P, V2, _),
              vtype(V, V2), not vmatch(V, V2).
lsboth(Q) :- lsup(Q, _), lref(Q, _).
tval(Q, unk) :- q_state(Q, _, _, _, _), not has_qrow(Q).
tval(Q, both) :- q_state(Q, _, _, _, _), lsboth(Q).
tval(Q, unk) :- q_state(Q, _, _, _, _), has_qrow(Q), not lsboth(Q),
                    later_mut(Q).
tval(Q, false) :- q_state(Q, _, _, _, _), has_qrow(Q), not lsboth(Q),
                  not later_mut(Q), lref(Q, _), not lsup(Q, _).
tval(Q, true) :- q_state(Q, _, _, _, _), has_qrow(Q), not lsboth(Q),
                 not later_mut(Q), lsup(Q, _), not lref(Q, _).
tval(Q, unk) :- q_state(Q, _, _, _, _), has_qrow(Q), not lsboth(Q),
                    not later_mut(Q), not lsup(Q, _), not lref(Q, _).

% ---- state_hist (PAST existential: never false)
tval(Q, true) :- q_state_hist(Q, E, P, V, _), row(F, E, P, V2, _),
                 vmatch(V, V2).
tval(Q, unk) :- q_state_hist(Q, _, _, _, _), not hist_matched(Q).
hist_matched(Q) :- q_state_hist(Q, E, P, V, _), row(F, E, P, V2, _),
                   vmatch(V, V2).

% ---- comparison over the CURRENT state value (LATEST + staleness)
cmp_holds(eq, V, V) :- valsrc(V).
cmp_holds(ne, V1, V2) :- vtype(V1, V2), V1 != V2.
cmp_holds(lt, num(A), num(B)) :- valsrc(num(A)), valsrc(num(B)), A < B.
cmp_holds(le, num(A), num(B)) :- valsrc(num(A)), valsrc(num(B)), A <= B.
cmp_holds(gt, num(A), num(B)) :- valsrc(num(A)), valsrc(num(B)), A > B.
cmp_holds(ge, num(A), num(B)) :- valsrc(num(A)), valsrc(num(B)), A >= B.
cmp_type(eq, V1, V2) :- vtype(V1, V2).
cmp_type(ne, V1, V2) :- vtype(V1, V2).
cmp_type(lt, num(X), num(Y)) :- valsrc(num(X)), valsrc(num(Y)).
cmp_type(le, num(X), num(Y)) :- valsrc(num(X)), valsrc(num(Y)).
cmp_type(gt, num(X), num(Y)) :- valsrc(num(X)), valsrc(num(Y)).
cmp_type(ge, num(X), num(Y)) :- valsrc(num(X)), valsrc(num(Y)).
csup(Q, F) :- q_cmp(Q, E, P, Op, Rhs, _), lrow(Q, F), row(F, E, P, V2, _),
              cmp_holds(Op, V2, Rhs).
cref(Q, F) :- q_cmp(Q, E, P, Op, Rhs, _), lrow(Q, F), row(F, E, P, V2, _),
              cmp_type(Op, V2, Rhs), not cmp_holds(Op, V2, Rhs).
csboth(Q) :- csup(Q, _), cref(Q, _).
tval(Q, unk) :- q_cmp(Q, _, _, _, _, _), not has_qrow(Q).
tval(Q, both) :- q_cmp(Q, _, _, _, _, _), csboth(Q).
tval(Q, unk) :- q_cmp(Q, _, _, _, _, _), has_qrow(Q), not csboth(Q),
                    later_mut(Q).
tval(Q, false) :- q_cmp(Q, _, _, _, _, _), has_qrow(Q), not csboth(Q),
                  not later_mut(Q), cref(Q, _), not csup(Q, _).
tval(Q, true) :- q_cmp(Q, _, _, _, _, _), has_qrow(Q), not csboth(Q),
                 not later_mut(Q), csup(Q, _), not cref(Q, _).
tval(Q, unk) :- q_cmp(Q, _, _, _, _, _), has_qrow(Q), not csboth(Q),
                    not later_mut(Q), not csup(Q, _), not cref(Q, _).

% ---- cardinality (distinct event positions of matching action facts)
carddom(N) :- q_card(_, _, _, _, _, N, _).
cardc(C) :- ccount(_, C).
card_holds(at_least, C, N) :- carddom(N), cardc(C), C >= N.
card_holds(at_most, C, N) :- carddom(N), cardc(C), C <= N.
card_holds(exactly, C, N) :- carddom(N), cardc(C), C == N.
cidx(Q, I) :- q_card(Q, A, E, Act, _, _, T), attempt_fact(F, A, E2, Act, I),
              entmatch(E, E2), I <= T.
cidx(Q, I) :- q_card(Q, A, E, Act, _, _, T), completed_fact(F, A, E2, Act, I),
              entmatch(E, E2), I <= T.
cidx(Q, I) :- q_card(Q, A, E, Act, _, _, T), failed_fact(F, A, E2, Act, I),
              entmatch(E, E2), I <= T.
ccount(Q, C) :- q_card(Q, _, _, _, _, _, _), C = #count { I : cidx(Q, I) }.
tval(Q, true) :- q_card(Q, _, _, _, Op, N, _), ccount(Q, C),
                 card_holds(Op, C, N), hist_complete.
tval(Q, false) :- q_card(Q, _, _, _, Op, N, _), ccount(Q, C), hist_complete,
                  not card_holds(Op, C, N).
tval(Q, true) :- q_card(Q, _, _, _, at_least, N, _), ccount(Q, C),
                 C >= N, not hist_complete.
tval(Q, unk) :- q_card(Q, _, _, _, at_least, N, _), ccount(Q, C),
                    C < N, not hist_complete.
tval(Q, unk) :- q_card(Q, _, _, _, at_most, _, _), not hist_complete.
tval(Q, unk) :- q_card(Q, _, _, _, exactly, _, _), not hist_complete.

% ==================== condition trees (recursive native fold) ==============

cval(N, V) :- cnode(N, leaf), cleaf(N, Q, 0), tval(Q, V).
cval(N, V) :- cnode(N, leaf), cleaf(N, Q, 1), tval(Q, W), neg(W, V).
cval(N, V) :- cnode(N, negnode), cnot(N, M), cval(M, W), neg(W, V).

% conjunction fold over ordered children (recursion)
fold(N, 0, V) :- cchild(N, 0, M), cval(M, V).
fold(N, P, V) :- cchild(N, P, M), fold(N, P1, V1), P = P1 + 1,
                 cval(M, V2), conj(V1, V2, V).
cval(N, V) :- cnode(N, all), lastchild(N, P), fold(N, P, V).
% disjunction fold over ordered children (recursion)
foldo(N, 0, V) :- cchild(N, 0, M), cval(M, V).
foldo(N, P, V) :- cchild(N, P, M), foldo(N, P1, V1), P = P1 + 1,
                  cval(M, V2), disj(V1, V2, V).
cval(N, V) :- cnode(N, any), lastchild(N, P), foldo(N, P, V).

% ===================== obligations, worlds, consensus ======================

1 { active(I) : interp(I) } 1.

antv(O, V) :- obl(O, _, _, _), obl_root(O, N), cval(N, V).
antv(O, true) :- obl(O, _, _, _), not obl_root(O, _).

% target atom value
tvv(O, true) :- obl(O, _, _, _), obl_target_inv(O).
tvv(O, V) :- obl(O, _, _, _), obl_target_q(O, Q), tval(Q, V).

% safety = NOT(antecedent AND NOT-required):
%   FORBID (required = NOT target):   saf = NOT(ant AND target)
%   REQUIRE (required = target):      saf = NOT(ant AND NOT target)
saf(O, V) :- obl(O, _, _, _), obl_kind(O, forbid), antv(O, A), tvv(O, T),
             conj(A, T, C), neg(C, V).
saf(O, V) :- obl(O, _, _, _), obl_kind(O, require), antv(O, A), tvv(O, T),
             neg(T, NT), conj(A, NT, C), neg(C, V).

wfalse(I) :- active(I), saf(O, false), obl(O, I, _, _).
wboth(I) :- active(I), saf(O, both), obl(O, I, _, _).
wunk1(I) :- active(I), saf(O, unk), obl(O, I, _, _).
wunk2(I) :- active(I), marker(I, _).
has_obl(I) :- active(I), obl(_, I, _, _).
werr(I, true) :- active(I), wfalse(I).
werr(I, both) :- active(I), wboth(I), not wfalse(I).
werr(I, unk) :- active(I), not wfalse(I), not wboth(I), wunk1(I).
werr(I, unk) :- active(I), not wfalse(I), not wboth(I), wunk2(I).
werr(I, false) :- active(I), not wfalse(I), not wboth(I), not wunk1(I),
                  not wunk2(I), has_obl(I).
werr(I, false) :- active(I), not wfalse(I), not wboth(I), not wunk1(I),
                  not wunk2(I), not has_obl(I).
"""


# ------------------------------------------------------- program generation

class _Program:
    def __init__(self):
        self.data: list[str] = []
        self.queries: dict[str, str] = {}     # qid -> canonical atom key
        self.query_atoms: dict[str, NeutralAtom] = {}

    def line(self, text: str) -> None:
        self.data.append(text)

    def query_id(self, atom: NeutralAtom, resolved_t: int) -> str:
        t = resolved_t if atom.time_index == -1 else atom.time_index
        key = _resolved_key(atom, t)
        if key in self.queries:
            return next(q for q, k in self.queries.items() if k == key)
        qid = f"q{len(self.queries)}"
        self.queries[qid] = key
        self.query_atoms[qid] = atom
        if atom.kind == "attempted":
            self.line(f"q_attempted({qid}, {_sym(atom.actor)}, {_sym(atom.entity)}, "
                      f"{_sym(atom.action)}, {t}).")
        elif atom.kind == "completed":
            self.line(f"q_completed({qid}, {_sym(atom.actor)}, {_sym(atom.entity)}, "
                      f"{_sym(atom.action)}, {t}).")
        elif atom.kind == "state":
            self.line(f"q_state({qid}, {_sym(atom.entity)}, {_sym(atom.predicate)}, "
                      f"{_term(atom.expected)}, {t}).")
        elif atom.kind == "state_hist":
            self.line(f"q_state_hist({qid}, {_sym(atom.entity)}, {_sym(atom.predicate)}, "
                      f"{_term(atom.expected)}, {t}).")
        elif atom.kind == "comparison":
            c = atom.comparison
            op = {"EQ": "eq", "NE": "ne", "LT": "lt", "LE": "le",
                  "GT": "gt", "GE": "ge"}[c.op]
            self.line(f"q_cmp({qid}, {_sym(atom.entity)}, {_sym(c.predicate)}, "
                      f"{op}, {_term(c.rhs_literal)}, {t}).")
        elif atom.kind == "cardinality":
            c = atom.cardinality
            op = {"AT_LEAST": "at_least", "AT_MOST": "at_most",
                  "EXACTLY": "exactly"}[c.op]
            self.line(f"q_card({qid}, {_sym(atom.actor)}, {_sym(atom.entity)}, "
                      f"{_sym(atom.cardinality.subject)}, {op}, {c.count}, {t}).")
        else:
            raise ValueError(f"atom kind {atom.kind}")
        return qid


def _resolved_key(atom: NeutralAtom, t: int) -> str:
    saved = atom.time_index
    try:
        object.__setattr__(atom, "time_index", t)
        return atom.key()
    finally:
        object.__setattr__(atom, "time_index", saved)


def _fid(fact_id: str) -> str:
    out = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in fact_id)
    return out or "f"


def _emit_facts(ci: NeutralCoreInput, prog: _Program) -> None:
    for f in ci.facts:
        fid = _fid(f.fact_id)
        actor, entity, pred = _sym(f.actor), _sym(f.entity), _sym(f.predicate)
        if f.kind == "ACTION_ATTEMPTED":
            prog.line(f"attempt_fact({fid}, {actor}, {entity}, {pred}, {f.event_index}).")
            if f.call_id:
                prog.line(f"attempt_call({fid}, {actor}, {entity}, {pred}, "
                          f"{f.event_index}, {_sym(f.call_id)}).")
        elif f.kind == "ACTION_COMPLETED":
            prog.line(f"completed_fact({fid}, {actor}, {entity}, {pred}, {f.event_index}).")
            if f.call_id:
                prog.line(f"attempt_call({fid}, {actor}, {entity}, {pred}, "
                          f"{f.event_index}, {_sym(f.call_id)}).")
        elif f.kind == "ACTION_FAILED":
            prog.line(f"failed_fact({fid}, {actor}, {entity}, {pred}, {f.event_index}).")
            if f.call_id:
                prog.line(f"attempt_call({fid}, {actor}, {entity}, {pred}, "
                          f"{f.event_index}, {_sym(f.call_id)}).")
        elif f.kind in STATE_KINDS:
            prog.line(f"state_fact({fid}, {actor}, {entity}, {pred}, {f.event_index}).")
            prog.line(f"sval({fid}, {_term(f.value)}).")
        elif f.kind == "EFFECT":
            prog.line(f"effect_fact({fid}, {actor}, {entity}, {pred}, "
                      f"{f.event_index}, {_sym(f.call_id or '')}).")
            prog.line(f"sval({fid}, {_term(f.value)}).")
        else:
            # CLAIM / ENTITY / RELATION: carried as inert rows (S3) — never
            # evidence, but present so the engine actually scales over them
            prog.line(f"inert({fid}, {_sym(f.kind)}, {actor}, {entity}, {pred}, "
                      f"{f.event_index}).")
    if ci.history_complete:
        prog.line("hist_complete.")
    if all(f.actor not in ("", "unknown") for f in ci.facts):
        prog.line("known_actors.")
    for interp in ci.interpretations:
        prog.line(f"interp({_sym(interp.interp_id)}).")
        for marker in interp.unresolved:
            prog.line(f"marker({_sym(interp.interp_id)}, {_sym(marker)}).")


class _TreeEmitter:
    """Emits condition-tree nodes with leaves resolved to queries at the
    obligation's evaluation bound."""

    def __init__(self, prog: _Program):
        self.prog = prog
        self.counter = 0

    def node(self, tree: CondNode | None, negate_outer: bool, bound: int) -> str:
        if tree is None:
            tree = CondNode(atom=None, all_=(CondNode(atom=None),))  # unreachable
        return self._emit(tree, negate_outer, bound)

    def _emit(self, node: CondNode, negate: bool, bound: int) -> str:
        self.counter += 1
        nid = f"n{self.counter}"
        if node.atom is not None:
            qid = self.prog.query_id(node.atom, bound)
            # leaf with polarity; wrap in a not-node when negated
            self.prog.line(f"cnode({nid}, leaf).")
            self.prog.line(f"cleaf({nid}, {qid}, 0).")
            if negate:
                self.counter += 1
                pid = f"n{self.counter}"
                self.prog.line(f"cnode({pid}, negnode).")
                self.prog.line(f"cnot({pid}, {nid}).")
                return pid
            return nid
        if node.not_ is not None:
            child = self._emit(node.not_, False, bound)
            if negate:
                # not(not X) == X
                return child
            self.counter += 1
            pid = f"n{self.counter}"
            self.prog.line(f"cnode({pid}, negnode).")
            self.prog.line(f"cnot({pid}, {child}).")
            return pid
        kind = "all" if node.all_ is not None else "any"
        children = node.all_ if node.all_ is not None else node.any_
        child_ids = [self._emit(child, False, bound) for child in children]
        self.prog.line(f"cnode({nid}, {kind}).")
        for pos, cid in enumerate(child_ids):
            self.prog.line(f"cchild({nid}, {pos}, {cid}).")
        self.prog.line(f"lastchild({nid}, {len(child_ids) - 1}).")
        if negate:
            self.counter += 1
            pid = f"n{self.counter}"
            self.prog.line(f"cnode({pid}, negnode).")
            self.prog.line(f"cnot({pid}, {nid}).")
            return pid
        return nid


def _build_rule_tree(rule, bound: int, emitter: _TreeEmitter) -> str | None:
    """Root condition node for a rule: AND(conditions, NOT(exc_1..),
    temporal gate).  Exceptions are compiled as negated conjuncts (the
    incumbent's UNLESS -> negated condition convention)."""
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
    emitter.prog.line(f"cnode({root}, all).")
    for pos, cid in enumerate(parts):
        emitter.prog.line(f"cchild({root}, {pos}, {cid}).")
    emitter.prog.line(f"lastchild({root}, {len(parts) - 1}).")
    return root


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
                    prog.line(f"obl({oid}, {_sym(interp.interp_id)}, "
                              f"{_sym(rule.rule_id)}, {_sym(f.fact_id)}).")
                    prog.line(f"obl_kind({oid}, forbid).")
                    if root is not None:
                        prog.line(f"obl_root({oid}, {root}).")
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
            else:   # REQUIRE
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
                prog.line(f"obl({oid}, {_sym(interp.interp_id)}, {_sym(rule.rule_id)}, "
                          f"exist).")
                prog.line(f"obl_kind({oid}, require).")
                prog.line(f"obl_target_q({oid}, {qid}).")
                if root is not None:
                    prog.line(f"obl_root({oid}, {root}).")
                emitted.append((oid, interp.interp_id, rule.rule_id, "exist"))
    return emitted


def _effect_bound(ci: NeutralCoreInput, fact) -> int:
    """Latest neutral index covered by the attempt fact's call unit (the
    completion evidence lives in the same call's result/effect)."""
    bound = fact.event_index
    for other in ci.facts:
        if other.call_id and fact.call_id and other.call_id == fact.call_id \
                and other.event_index > bound:
            bound = other.event_index
        if other.kind == "EFFECT" and other.predicate == fact.predicate \
                and other.entity == fact.entity and other.call_id is None:
            continue
    return bound


# ------------------------------------------------------------------ solving

def _run_program(program_text: str):
    control = clingo.Control(["-t", "2", "-n", "0", "--stats"])   # -n 0: enumerate ALL models
    control.add("base", [], program_text)
    control.ground([("base", [])])
    models = []
    control.solve(on_model=lambda model: models.append(model.symbols(atoms=True)))
    return control, models


def evaluate(ci: NeutralCoreInput) -> BackendResult:
    started = time.perf_counter()
    if not ci.interpretations:
        return BackendResult(backend="clingo", status="UNRESOLVED",
                             input_content_hash=ci.content_hash(),
                             notes="empty interpretation space")
    prog = _Program()
    _emit_facts(ci, prog)
    emitter = _TreeEmitter(prog)
    obligations = _emit_obligations(ci, prog, emitter)
    program_text = TEMPLATE + "\n" + "\n".join(prog.data) + "\n"

    try:
        _control, models = _run_program(program_text)
    except Exception as error:                       # pragma: no cover
        return BackendResult(backend="clingo", status="ERROR",
                             input_content_hash=ci.content_hash(),
                             detail=f"{type(error).__name__}: {error}")

    if not models:
        return BackendResult(backend="clingo", status="ERROR",
                             input_content_hash=ci.content_hash(),
                             detail="no stable models")

    # per-model world verdicts + tval snapshot (world-independent)
    worlds: list[WorldResult] = []
    tval_by_model: list[dict[str, str]] = []
    saf_by_model: list[dict[str, str]] = []
    for model in models:
        werr: dict[str, str] = {}
        tvals: dict[str, str] = {}
        safs: dict[str, str] = {}
        for atom in model:
            name = atom.name
            if name == "werr" and len(atom.arguments) == 2:
                werr[str(atom.arguments[0]).strip('"')] = _asp_truth(str(atom.arguments[1]))
            elif name == "tval" and len(atom.arguments) == 2:
                tvals[str(atom.arguments[0])] = _asp_truth(str(atom.arguments[1]))
            elif name == "saf" and len(atom.arguments) == 2:
                safs[str(atom.arguments[0])] = _asp_truth(str(atom.arguments[1]))
        tval_by_model.append(tvals)
        saf_by_model.append(safs)
        for interp_id, value in werr.items():
            worlds.append(WorldResult(interp_id, value))

    status = _consensus(worlds)

    # brave/cautious equivalence check (tested, not assumed)
    cautious_true = all(any(w.interp_id == wid and w.error_value == "TRUE"
                            for w in worlds) for wid in {w.interp_id for w in worlds})
    cautious_false = all(w.error_value == "FALSE" for w in worlds)
    brave_both = any(w.error_value == "BOTH" for w in worlds)
    any_unk = any(w.error_value == "UNKNOWN" for w in worlds)
    any_true = any(w.error_value == "TRUE" for w in worlds)
    any_false = any(w.error_value == "FALSE" for w in worlds)
    if brave_both:
        brave_cautious_status = "INCONSISTENT"
    elif cautious_true and not any_false:
        brave_cautious_status = "PROVED_ERROR"
    elif cautious_false and not any_true:
        brave_cautious_status = "PROVED_NO_ERROR"
    elif any_unk or (any_true and any_false):
        brave_cautious_status = "UNRESOLVED"
    elif not worlds:
        brave_cautious_status = "UNRESOLVED"
    else:
        brave_cautious_status = "UNRESOLVED"
    equiv = "brave/cautious-vs-consensus:" + (
        "EQUIVALENT" if brave_cautious_status == status else
        f"MISMATCH(consensus={status},b/c={brave_cautious_status})")

    witnesses = _witnesses(models, prog, obligations)
    runtime_ms = (time.perf_counter() - started) * 1000.0
    return BackendResult(backend="clingo", status=status, worlds=tuple(worlds),
                         witnesses=witnesses, runtime_ms=runtime_ms,
                         input_content_hash=ci.content_hash(),
                         notes=f"models={len(models)}; {equiv}")


def probe(ci: NeutralCoreInput, atoms: list[NeutralAtom]) -> list[PrimitiveResult]:
    started = time.perf_counter()
    prog = _Program()
    _emit_facts(ci, prog)
    qids = []
    for atom in atoms:
        qids.append(prog.query_id(atom, atom.time_index))
    program_text = TEMPLATE + "\n" + "\n".join(prog.data) + "\n"
    _control, models = _run_program(program_text)
    results = []
    if models:
        # tval is world-independent: verify identical across models
        tvals: dict[str, str] = {}
        consistent = True
        for model in models:
            current = {}
            for atom in model:
                if atom.name == "tval" and len(atom.arguments) == 2:
                    current[str(atom.arguments[0])] = _asp_truth(str(atom.arguments[1]))
            if not tvals:
                tvals = current
            elif current != tvals:
                consistent = False
        supports = _support_map(models)
        for qid in qids:
            value = tvals.get(qid, "UNKNOWN")
            sup, ref = supports.get(qid, ((), ()))
            results.append(PrimitiveResult(prog.queries[qid], value,
                                           tuple(sup), tuple(ref)))
        if not consistent:
            results.append(PrimitiveResult("tval_consistency", "FALSE", (), ()))
    else:
        for qid in qids:
            results.append(PrimitiveResult(prog.queries[qid], "UNKNOWN", (), ()))
    _ = started
    return results


def _support_map(models) -> dict[str, tuple[tuple, tuple]]:
    """sup/ref fact ids per query, read from the first model."""
    out: dict[str, tuple] = {}
    if not models:
        return out
    sup: dict[str, list] = {}
    ref: dict[str, list] = {}
    for atom in models[0]:
        if atom.name == "sup" and len(atom.arguments) == 2:
            qid = str(atom.arguments[0])
            sup.setdefault(qid, []).append(_clean(str(atom.arguments[1])))
        elif atom.name == "ref" and len(atom.arguments) in (1, 2):
            qid = str(atom.arguments[0])
            ref.setdefault(qid, []).append(
                _clean(str(atom.arguments[1])) if len(atom.arguments) == 2 else "")
    for qid in set(sup) | set(ref):
        out[qid] = (tuple(dict.fromkeys(sup.get(qid, []))),
                    tuple(dict.fromkeys(ref.get(qid, []))))
    return out


def _clean(text: str) -> str:
    return text.strip('"')


def _consensus(worlds: list[WorldResult]) -> str:
    if not worlds:
        return "UNRESOLVED"
    values = [w.error_value for w in worlds]
    if "BOTH" in values:
        return "INCONSISTENT"
    if "UNKNOWN" in values:
        return "UNRESOLVED"
    if all(v == "TRUE" for v in values):
        return "PROVED_ERROR"
    if all(v == "FALSE" for v in values):
        return "PROVED_NO_ERROR"
    return "UNRESOLVED"


def _witnesses(models, prog: _Program, obligations) -> tuple:
    if not models:
        return ()
    model = models[0]
    safs: dict[str, str] = {}
    tvals: dict[str, str] = {}
    for atom in model:
        if atom.name == "saf" and len(atom.arguments) == 2:
            safs[str(atom.arguments[0])] = str(atom.arguments[1])
        elif atom.name == "tval" and len(atom.arguments) == 2:
            tvals[str(atom.arguments[0])] = str(atom.arguments[1])
    supports = _support_map(models)
    out = []
    for oid, interp_id, rule_id, fact_id in obligations:
        conclusion = safs.get(oid, "UNKNOWN")
        leaf_queries = _leaf_queries_of(prog, oid)
        sups, refs, unks = [], [], []
        for qid in leaf_queries:
            s, r = supports.get(qid, ((), ()))
            sups.extend(s)
            refs.extend(r)
            if tvals.get(qid, "UNKNOWN") in ("UNKNOWN", "BOTH"):
                unks.append(prog.queries.get(qid, qid))
        out.append(BackendWitness(
            rule_id=rule_id, interpretation_id=interp_id, conclusion=conclusion,
            supporting_fact_ids=tuple(dict.fromkeys(sups))[:8],
            refuting_fact_ids=tuple(dict.fromkeys(refs))[:8],
            unknown_dependencies=tuple(dict.fromkeys(unks))[:8],
            engine_native_explanation=f"clingo stable model: obligation {oid} "
                                      f"safety={conclusion}"))
    return tuple(out)


def _leaf_queries_of(prog: _Program, oid: str) -> list[str]:
    """Query ids referenced by the obligation's condition tree (structural
    scan of the emitted program lines)."""
    lines = prog.data
    root = None
    for line in lines:
        if line.startswith(f"obl_root({oid},"):
            root = line[len(f"obl_root({oid}, "):-2]
    if root is None:
        return []
    children: dict[str, list[str]] = {}
    leaves: dict[str, str] = {}
    nots: dict[str, str] = {}
    for line in lines:
        if line.startswith("cchild("):
            rest = line[8:-2]
            nid, pos, cid = [part.strip() for part in rest.split(",")]
            children.setdefault(nid, [None] * 10)
            children[nid][int(pos)] = cid
        elif line.startswith("cleaf("):
            rest = line[6:-2]
            nid, qid, neg = [part.strip() for part in rest.split(",")]
            leaves[nid] = qid
        elif line.startswith("cnot("):
            rest = line[5:-2]
            nid, cid = [part.strip() for part in rest.split(",")]
            nots[nid] = cid
    out = []

    def visit(node):
        if node in leaves:
            out.append(leaves[node])
        elif node in nots:
            visit(nots[node])
        elif node in children:
            for child in children[node]:
                if child:
                    visit(child)

    visit(root)
    return out
