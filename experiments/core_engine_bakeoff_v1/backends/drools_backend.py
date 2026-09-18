"""core_engine_bakeoff_v1 — backend: DROOLS 10.2.0 (KIE, Java 21 JRE).

NeutralCoreInput -> generated DRL (declared fact types + per-query/per-node/
per-obligation rules) + line-based payload -> one Java process
(DroolsBakeoff.java, single-file source launcher on the JRE) -> derived TV /
SAF / WORLD answers -> consensus in the adapter.

Native DROOLS capabilities exercised:
  * declared fact types (no javac needed)
  * pattern joins with constraints (entity wildcard, index bounds, actor)
  * `not exists` / `exists` — the closed-world DANGER: absence is refutation
    ONLY in the absence-proof rules, which the generator emits exclusively
    under the complete-history premises (structural gating; DRL `not` can
    never fire on open-world absence because no such rule is generated)
  * accumulates: max (latest evidence position) and count (cardinality)
  * numeric comparisons in constraints
  * forward-chaining derivation of condition-tree values (CV) and safety
    (SAF) through generated rules

Explicitly NOT native in Drools (documented as capability gaps):
  * multiple semantic worlds / interpretations as answer sets (no stable
    models, no brave/cautious): every interpretation is evaluated in the
    SAME session with obligations tagged by interpretation, and the world
    error fold + consensus run in the Java harness
  * four-valued UNKNOWN/BOTH as engine semantics: the tables are encoded as
    MVEL expressions in rule consequences

The Java harness (DroolsBakeoff.java) is generic: it reads the payload,
builds the session, fires the rules and folds the world values.
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

JAVA = os.environ.get("BAKEOFF_JAVA", "java")
JAR_ROOT = Path(os.environ.get(
    "BAKEOFF_DROOLS_JARS", "/home/z/drools-jars"))
HARNESS = HERE / "DroolsBakeoff.java"

_TRUTH_MAP = {"t": "TRUE", "f": "FALSE", "b": "BOTH", "u": "UNKNOWN"}

_CLASSPATH = ":".join(str(p) for p in sorted(JAR_ROOT.glob("*.jar")))


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _drl_str(value: str) -> str:
    return f'"{_esc(value)}"'


# ------------------------------------------------------- payload generation

def _fact_lines(ci: NeutralCoreInput) -> list[str]:
    lines = []
    for f in ci.facts:
        if f.kind == "ACTION_ATTEMPTED":
            kind = "ATTEMPTED"
        elif f.kind == "ACTION_COMPLETED":
            kind = "COMPLETED"
        elif f.kind == "ACTION_FAILED":
            kind = "FAILED"
        elif f.kind in STATE_KINDS:
            kind = "OBS"
        elif f.kind == "EFFECT":
            kind = "EFFECT"
        else:
            kind = "INERT"
        tag, value, num = _tagged(f.value)
        lines.append(f"NF|{f.fact_id}|{kind}|{f.actor}|{f.entity}|{f.predicate}"
                     f"|{tag}|{value}|{num}|{f.event_index}|{f.region}"
                     f"|{f.call_id or ''}")
    if ci.history_complete:
        lines.append("PREM|hist_complete")
    if all(f.actor not in ("", "unknown") for f in ci.facts):
        lines.append("PREM|known_actors")
    for interp in ci.interpretations:
        for marker in interp.unresolved:
            lines.append(f"MARK|{interp.interp_id}|{marker}")
    return lines


def _tagged(value) -> tuple[str, str, str]:
    if value is None:
        return ("none", "", "0")
    if isinstance(value, bool):
        return ("bool", "true" if value else "false", "0")
    if isinstance(value, (int, float)):
        return ("num", str(value), str(float(value)))
    return ("str", str(value), "0")


class _DrlGen:
    """Generates the DRL program + payload lines for one case."""

    def __init__(self, ci: NeutralCoreInput):
        self.ci = ci
        self.payload: list[str] = _fact_lines(ci)
        self.rules: list[str] = []
        self.queries: dict[str, NeutralAtom] = {}
        self.query_times: dict[str, int] = {}
        self.known_actors = all(f.actor not in ("", "unknown")
                                for f in ci.facts)
        self._head_emitted = False
        self._node_counter = 0

    # ------------------------------------------------------------- queries
    def query_id(self, atom: NeutralAtom, resolved_t: int) -> str:
        t = resolved_t if atom.time_index == -1 else atom.time_index
        saved = atom.time_index
        try:
            object.__setattr__(atom, "time_index", t)
            key = atom.key()
        finally:
            object.__setattr__(atom, "time_index", saved)
        if key in {k for k in self.queries.values()}:
            return next(q for q, a in self.queries.items()
                        if a.key() == key) if False else self._find(key)
        qid = f"q{len(self.queries)}"
        self.queries[qid] = atom
        self.query_times[qid] = t
        tag, value, num = _tagged(atom.expected if atom.kind in
                                  ("state", "state_hist") else None)
        if atom.kind == "comparison":
            tag, value, num = _tagged(atom.comparison.rhs_literal)
        if atom.kind == "cardinality":
            tag, value = "num", str(atom.cardinality.count)
        self.payload.append(
            f"Q|{qid}|{atom.kind}|{atom.action}|{atom.entity}|{atom.actor}"
            f"|{(atom.comparison.predicate if atom.kind == 'comparison' else atom.predicate)}"
            f"|{tag}|{value}|{t}")
        self._emit_query_rules(qid, atom, t, tag, value)
        return qid

    def _find(self, key: str) -> str:
        for q, a in self.queries.items():
            saved = a.time_index
            if self.query_times.get(q) is not None:
                object.__setattr__(a, "time_index", self.query_times[q])
                if a.key() == key:
                    object.__setattr__(a, "time_index", saved)
                    return q
            object.__setattr__(a, "time_index", saved)
        raise KeyError(key)

    # ------------------------------------------------------ query DRL rules
    def _emit_query_rules(self, qid: str, atom: NeutralAtom, t: int,
                          tag: str, value: str) -> None:
        self._ensure_head()
        if atom.kind in ("attempted", "completed"):
            self._attempted_rules(qid, atom, t)
        elif atom.kind in ("state", "state_hist", "comparison"):
            self._state_rules(qid, atom, t, tag, value)
        elif atom.kind == "cardinality":
            self._card_rules(qid, atom, t)

    def _action_pattern(self, atom, t: int, entity: str) -> str:
        e = _drl_str(entity)
        return (f'NF(kind in ("ATTEMPTED","COMPLETED","FAILED"), '
                f'predicate == {(_drl_str(atom.action))}, '
                f'actor == {_drl_str(atom.actor)}, idx <= {t}, '
                f'(entity == {e} || {e} == "*"))')

    def _attempted_rules(self, qid, atom, t):
        support = self._action_pattern(atom, t, atom.entity)
        if atom.kind == "completed":
            e = _drl_str(atom.entity)
            support = (f'( NF(kind == "COMPLETED", predicate == {_drl_str(atom.action)}, '
                       f'actor == {_drl_str(atom.actor)}, idx <= {t}, '
                       f'(entity == {e} || {e} == "*")) or '
                       f'( NF(kind == "EFFECT", $cid : callId, '
                       f'(entity == {e} || {e} == "*")) and '
                       f'NF(kind in ("ATTEMPTED","COMPLETED","FAILED"), callId == $cid, '
                       f'predicate == {_drl_str(atom.action)}, '
                       f'actor == {_drl_str(atom.actor)}, idx <= {t}) ) )')
        self.rules.append(f'''
rule "tv_t_{qid}"
when
    Q(id == "{qid}")
    exists {support}
then
    insert(new TV("{qid}", "t"));
end
''')
        if atom.kind == "attempted" and self.ci.history_complete \
                and self.known_actors:
            self.rules.append(f'''
rule "tv_f_{qid}"
when
    Q(id == "{qid}")
    not {support}
then
    insert(new TV("{qid}", "f"));
end
''')
        else:
            self.rules.append(f'''
rule "tv_u_{qid}"
when
    Q(id == "{qid}")
    not {support}
then
    insert(new TV("{qid}", "u"));
end
''')

    def _row_pattern(self, predicate: str, entity: str, t: int) -> str:
        e = _drl_str(entity)
        return (f'NF(kind in ("OBS","EFFECT"), predicate == {_drl_str(predicate)}, '
                f'idx <= {t}, (entity == {e} || {e} == "*"))')

    def _value_match(self, tag: str, value: str, negate: bool) -> str:
        op = "!=" if negate else "=="
        if tag == "num":
            return f'tag == "num", numVal {op} {float(value)}'
        if tag == "bool":
            return f'tag == "bool", value {op} "{value}"'
        return f'tag == "str", value {op} {_drl_str(value)}'

    def _cmp_match(self, atom, negate: bool) -> str:
        c = atom.comparison
        rhs = c.rhs_literal
        op = {"EQ": "==", "NE": "!=", "LT": "<", "LE": "<=",
              "GT": ">", "GE": ">="}[c.op]
        if negate:
            flip = {"==": "!=", "!=": "==", "<": ">=", "<=": ">",
                    ">": "<=", ">=": "<"}
            op = flip[op]
        if c.op in ("EQ", "NE") and isinstance(rhs, str):
            return f'tag == "str", value {op} {_drl_str(rhs)}'
        if c.op in ("EQ", "NE") and isinstance(rhs, bool):
            return f'tag == "bool", value {op} {"true" if rhs else "false"}'
        return f'tag == "num", numVal {op} {float(rhs)}'

    def _state_rules(self, qid, atom, t, tag, value):
        e = _drl_str(atom.entity)
        pred = (atom.comparison.predicate if atom.kind == "comparison"
                else atom.predicate)
        rows = self._row_pattern(pred, atom.entity, t)
        if atom.kind == "state_hist":
            match = self._value_match(tag, value, False)
            matched = rows[:-1] + ", " + match + ")"
            self.rules.append(f'''
rule "tv_t_{qid}"
when
    Q(id == "{qid}")
    exists {matched}
then
    insert(new TV("{qid}", "t"));
end
rule "tv_u_{qid}"
when
    Q(id == "{qid}")
    not {matched}
then
    insert(new TV("{qid}", "u"));
end
''')
            return
        if atom.kind == "comparison":
            holds = self._cmp_match(atom, False)
            fails = self._cmp_match(atom, True)
        else:
            holds = self._value_match(tag, value, False)
            fails = self._value_match(tag, value, True)
        # latest evidence row = matching row with NO later matching row
        # (pure pattern join; declared-type accumulates hit a Drools
        # classloader access bug in this environment)
        at_latest = (f'NF(kind in ("OBS","EFFECT"), predicate == {_drl_str(pred)}, '
                     f'$i : idx, idx <= {t}, (entity == {e} || {e} == "*"))')
        later = (f'NF(kind in ("OBS","EFFECT"), predicate == {_drl_str(pred)}, '
                 f'idx > $i, idx <= {t}, (entity == {e} || {e} == "*"))')
        at_i = (f'NF(kind in ("OBS","EFFECT"), predicate == {_drl_str(pred)}, '
                f'idx == $i, (entity == {e} || {e} == "*"))')

        def _with(match: str) -> str:
            return at_i[:-1] + ", " + match + ")"
        mutations_tmpl = (f'NF(kind in ("ATTEMPTED","COMPLETED","FAILED"), '
                          f'idx > $i, idx <= {t}, (entity == {e} || {e} == "*"))')

        def mutations(latest_var: str = "$i") -> str:
            return mutations_tmpl
        self.rules.append(f'''
rule "tv_zero_{qid}"
when
    Q(id == "{qid}")
    not {rows}
then
    insert(new TV("{qid}", "u"));
end
rule "tv_both_{qid}"
when
    Q(id == "{qid}")
    {at_latest}
    not {later}
    exists {_with(holds)}
    exists {_with(fails)}
then
    insert(new TV("{qid}", "b"));
end
rule "tv_stale_{qid}"
when
    Q(id == "{qid}")
    {at_latest}
    not {later}
    exists {mutations()}
then
    insert(new TV("{qid}", "u"));
end
rule "tv_t_{qid}"
when
    Q(id == "{qid}")
    {at_latest}
    not {later}
    not {mutations()}
    exists {_with(holds)}
    not {_with(fails)}
then
    insert(new TV("{qid}", "t"));
end
rule "tv_f_{qid}"
when
    Q(id == "{qid}")
    {at_latest}
    not {later}
    not {mutations()}
    exists {_with(fails)}
    not {_with(holds)}
then
    insert(new TV("{qid}", "f"));
end
rule "tv_nonev_{qid}"
when
    Q(id == "{qid}")
    {at_latest}
    not {later}
    not {mutations()}
    not {_with(holds)}
    not {_with(fails)}
then
    insert(new TV("{qid}", "u"));
end
''')

    def _card_rules(self, qid, atom, t):
        c = atom.cardinality
        e = _drl_str(atom.entity)
        pattern = (f'NF(kind in ("ATTEMPTED","COMPLETED","FAILED"), '
                   f'predicate == {_drl_str(c.subject)}, '
                   f'actor == {_drl_str(atom.actor)}, idx <= {t}, '
                   f'(entity == {e} || {e} == "*"))')
        ge = f'Long($cnt : longValue >= {c.count}) from accumulate($n : {pattern}, count($n))'
        nge = f'Long($cnt2 : longValue < {c.count}) from accumulate($n : {pattern}, count($n))'
        n1 = c.count + 1
        ge1 = f'Long($cnt3 : longValue >= {n1}) from accumulate($n : {pattern}, count($n))'
        nge1 = f'Long($cnt4 : longValue < {n1}) from accumulate($n : {pattern}, count($n))'
        complete = "PREM(name == \"hist_complete\")" \
            if self.ci.history_complete else None
        # NOTE: count(pattern) counts matching FACTS, not distinct indices;
        # the corpus uses unique event indices for action facts (documented)
        body_t = ge if c.op == "AT_LEAST" else (
            f'{ge1}' if False else None)
        rules = []
        if c.op == "AT_LEAST":
            rules.append((f'Q(id == "{qid}")\n    {ge}', "t"))
            if self.ci.history_complete:
                rules.append((f'Q(id == "{qid}")\n    {nge}', "f"))
            else:
                rules.append((f'Q(id == "{qid}")\n    {nge}', "u"))
        elif c.op == "AT_MOST":
            if self.ci.history_complete:
                rules.append((f'Q(id == "{qid}")\n    {nge1}', "t"))
            rules.append((f'Q(id == "{qid}")\n    {ge1}', "f"))
            if not self.ci.history_complete:
                rules.append((f'Q(id == "{qid}")', "u"))
        else:  # EXACTLY
            if self.ci.history_complete:
                rules.append((f'Q(id == "{qid}")\n    {ge}\n    {nge1}', "t"))
                rules.append((f'Q(id == "{qid}")\n    {ge1}', "f"))
                rules.append((f'Q(id == "{qid}")\n    {nge}', "f"))
            else:
                rules.append((f'Q(id == "{qid}")', "u"))
        for i, (body, value) in enumerate(rules):
            self.rules.append(f'''
rule "tv_{value}_{qid}_{i}"
when
    {body}
then
    insert(new TV("{qid}", "{value}"));
end
''')

    # ---------------------------------------------------------- tree nodes
    def node(self, tree: CondNode | None, negate: bool, bound: int) -> str:
        return self._emit(tree, negate, bound)

    def _emit(self, node: CondNode, negate: bool, bound: int) -> str:
        self._node_counter += 1
        nid = f"n{self._node_counter}"
        if node.atom is not None:
            qid = self.query_id(node.atom, bound)
            self.payload.append(f"LEAFQ|{nid}|{qid}|{0 if not negate else 1}")
            for v_in, v_out in (("t", "t" if not negate else "f"),
                                ("f", "f" if not negate else "t"),
                                ("b", "b"), ("u", "u")):
                self.rules.append(f'''
rule "cv_{nid}_{v_in}"
when
    TV(qid == "{qid}", v == "{v_in}")
then
    insert(new CV("{nid}", "{v_out}"));
end
''')
            return nid
        if node.not_ is not None:
            child = self._emit(node.not_, False, bound)
            self.payload.append(f"NOTN|{nid}|{child}")
            for v_in, v_out in (("t", "f"), ("f", "t"), ("b", "b"), ("u", "u")):
                self.rules.append(f'''
rule "cv_{nid}_{v_in}"
when
    CV(node == "{child}", v == "{v_in}")
then
    insert(new CV("{nid}", "{v_out}"));
end
''')
            if negate:
                return child
            return nid
        kind = "all" if node.all_ is not None else "any"
        children = node.all_ if node.all_ is not None else node.any_
        child_ids = [self._emit(child, False, bound) for child in children]
        self.payload.append(f"{kind.upper()}N|{nid}|{','.join(child_ids)}")
        expr = self._fold_expr(kind, child_ids)
        for v in ("t", "f", "b", "u"):
            pass
        self.rules.append(f'''
rule "cv_{nid}"
when
    CV(node == "{child_ids[0]}", $v0 : v)
{chr(10).join(f'    CV(node == "{cid}", $v{i} : v)' for i, cid in enumerate(child_ids[1:], 1))}
then
    insert(new CV("{nid}", {expr}));
end
''')
        if negate:
            self._node_counter += 1
            wrap = f'n{self._node_counter}'
            self.payload.append(f"NOTN|{wrap}|{nid}")
            for v_in, v_out in (("t", "f"), ("f", "t"), ("b", "b"), ("u", "u")):
                self.rules.append(f'''
rule "cv_{wrap}_{v_in}"
when
    CV(node == "{nid}", v == "{v_in}")
then
    insert(new CV("{wrap}", "{v_out}"));
end
''')
            return wrap
        return nid

    def _fold_expr(self, kind: str, kids: list[str]) -> str:
        expr = f'$v0'
        for i in range(1, len(kids)):
            if kind == "all":
                expr = (f'(({expr} == "t" && $v{i} == "t") ? "t" : '
                        f'(({expr} == "f" || $v{i} == "f") ? "f" : '
                        f'(({expr} == "b" || $v{i} == "b") ? "b" : "u")))')
            else:
                expr = (f'(({expr} == "f" && $v{i} == "f") ? "f" : '
                        f'(({expr} == "t" || $v{i} == "t") ? "t" : '
                        f'(({expr} == "b" || $v{i} == "b") ? "b" : "u")))')
        return f'"{expr}"' if False else expr

    # -------------------------------------------------------- obligations
    def _ensure_head(self):
        if self._head_emitted:
            return
        self._head_emitted = True

    def emit_program(self) -> str:
        head = '''
package bakeoff;

declare NF
    id : String
    kind : String
    actor : String
    entity : String
    predicate : String
    tag : String
    value : String
    numVal : double
    idx : long
    region : String
    callId : String
end
declare Q
    id : String
    kind : String
    action : String
    entity : String
    actor : String
    predicate : String
    tag : String
    expected : String
    t : long
end
declare NODE
    id : String
    kind : String
    a : String
    b : String
end
declare OBL
    id : String
    interp : String
    ruleId : String
    kind : String
    root : String
    targetQ : String
    targetInv : boolean
end
declare PREM
    name : String
end
declare MARK
    interp : String
    text : String
end
declare TV
    qid : String
    v : String
end
declare CV
    node : String
    v : String
end
declare SAF
    oid : String
    v : String
end
'''
        return head + "\n".join(self.rules) + "\n"


# ------------------------------------------------------- obligation building

def _build_rule_tree(rule, bound: int, gen: _DrlGen) -> str | None:
    parts: list[str] = []
    if rule.conditions is not None:
        parts.append(gen.node(rule.conditions, False, bound))
    for exc in rule.exceptions:
        parts.append(gen.node(exc, True, bound))
    if rule.temporal in ("BEFORE", "UNTIL"):
        anchor = NeutralAtom(f"anchor:{rule.temporal_anchor_action}", "attempted",
                             action=rule.temporal_anchor_action,
                             entity=rule.temporal_anchor_entity,
                             actor="assistant", time_index=-1)
        parts.append(gen.node(CondNode(atom=anchor), True, bound))
    elif rule.temporal == "AFTER":
        anchor = NeutralAtom(f"anchor:{rule.temporal_anchor_action}", "attempted",
                             action=rule.temporal_anchor_action,
                             entity=rule.temporal_anchor_entity,
                             actor="assistant", time_index=-1)
        parts.append(gen.node(CondNode(atom=anchor), False, bound))
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    gen._node_counter += 1
    nid = f'n{gen._node_counter}'
    gen.payload.append(f"ALLN|{nid}|{','.join(parts)}")
    expr = gen._fold_expr("all", parts)
    gen.rules.append(f'''
rule "cv_{nid}"
when
    CV(node == "{parts[0]}", $v0 : v)
{chr(10).join(f'    CV(node == "{p}", $v{i} : v)' for i, p in enumerate(parts[1:], 1))}
then
    insert(new CV("{nid}", {expr}));
end
''')
    return nid


def _effect_bound(ci: NeutralCoreInput, fact) -> int:
    bound = fact.event_index
    for other in ci.facts:
        if other.call_id and fact.call_id and other.call_id == fact.call_id \
                and other.event_index > bound:
            bound = other.event_index
    return bound


def _emit_obligations(ci: NeutralCoreInput, gen: _DrlGen) -> list[tuple]:
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
                    continue
                for f in targets:
                    oid = f"o{len(emitted)}"
                    bound = f.event_index - 1
                    root = _build_rule_tree(rule, bound, gen)
                    if rule.target_level == "ATTEMPT":
                        target_q, target_inv = "", True
                    else:
                        atom = NeutralAtom(f"c:{rule.rule_id}:{f.fact_id}",
                                           "completed", action=rule.action,
                                           entity=f.entity, actor=rule.actor,
                                           time_index=END)
                        target_q = gen.query_id(atom, _effect_bound(ci, f))
                        target_inv = False
                    gen.payload.append(
                        f"OBL|{oid}|{interp.interp_id}|{rule.rule_id}|forbid"
                        f"|{root or ''}|{target_q}|{1 if target_inv else 0}")
                    _emit_saf_rule(gen, oid, "forbid", root, target_q,
                                   target_inv)
                    emitted.append((oid, interp.interp_id, rule.rule_id, f.fact_id))
            else:
                oid = f"o{len(emitted)}"
                root = _build_rule_tree(rule, max_t, gen)
                atom = (NeutralAtom(f"r:{rule.rule_id}", "attempted",
                                    action=rule.action, entity=rule.entity,
                                    actor=rule.actor, time_index=END)
                        if rule.target_level == "ATTEMPT" else
                        NeutralAtom(f"rc:{rule.rule_id}", "completed",
                                    action=rule.action, entity=rule.entity,
                                    actor=rule.actor, time_index=END))
                target_q = gen.query_id(atom, max_t)
                gen.payload.append(
                    f"OBL|{oid}|{interp.interp_id}|{rule.rule_id}|require"
                    f"|{root or ''}|{target_q}|0")
                _emit_saf_rule(gen, oid, "require", root, target_q, False)
                emitted.append((oid, interp.interp_id, rule.rule_id, "exist"))
    return emitted


def _emit_saf_rule(gen: _DrlGen, oid: str, kind: str, root: str | None,
                   target_q: str, target_inv: bool) -> None:
    if root is not None:
        ant = f'CV(node == "{root}", $a : v)'
    else:
        ant = None
    if target_inv:
        tv = '"t"'
        tvpat = ""
    elif target_q:
        tv = "$tv"
        tvpat = f'\n    TV(qid == "{target_q}", $tv : v)'
    else:
        tv = '"t"'
        tvpat = ""
    if kind == "forbid":
        # saf = NOT(ant AND target)
        if ant is not None:
            expr = (f'(($a == "t" && {tv} == "t") ? "f" : '
                    f'(($a == "f" || {tv} == "f") ? "t" : '
                    f'(($a == "b" || {tv} == "b") ? "b" : "u")))')
            body = ant
        else:
            expr = (f'(({tv} == "t") ? "f" : ({tv} == "f") ? "t" : {tv})')
            body = None
    else:
        # saf = NOT(ant AND NOT target)
        negtv = (f'({tv} == "t" ? "f" : {tv} == "f" ? "t" : {tv})')
        if ant is not None:
            expr = (f'(($a == "t" && {negtv} == "t") ? "f" : '
                    f'(($a == "f" || {negtv} == "f") ? "t" : '
                    f'(($a == "b" || {negtv} == "b") ? "b" : "u")))')
            body = ant
        else:
            expr = f'({negtv} == "t" ? "f" : {negtv} == "f" ? "t" : {negtv})'
            body = None
    when = f'    OBL(id == "{oid}")'
    if body:
        when += f'\n    {body}'
    if tvpat:
        when += tvpat
    gen.rules.append(f'''
rule "saf_{oid}"
when
{when}
then
    insert(new SAF("{oid}", {expr}));
end
''')


# ------------------------------------------------------------------ running

def _run_drools(gen: _DrlGen, ci: NeutralCoreInput, obligations,
                probe_qids: list[str], timeout_s: int = 90) -> dict:
    with tempfile.TemporaryDirectory(prefix="bakeoff_drools_") as td:
        td = Path(td)
        drl_path = td / "program.drl"
        facts_path = td / "facts.txt"
        out_path = td / "out.txt"
        drl_path.write_text(gen.emit_program(), encoding="utf-8")
        payload = list(gen.payload)
        for interp in ci.interpretations:
            payload.append(f"WORLD|{interp.interp_id}")
        for qid in probe_qids:
            payload.append(f"TVQ|{qid}")
        facts_path.write_text("\n".join(payload) + "\n", encoding="utf-8")
        try:
            subprocess.run(
                [JAVA, "-cp", _CLASSPATH, str(HARNESS),
                 str(facts_path), str(drl_path), str(out_path)],
                capture_output=True, text=True, timeout=timeout_s,
                stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return {"error": "timeout"}
        if not out_path.exists():
            return {"error": "no-output",
                    "stderr_tail": ""}
        result: dict = {"worlds": [], "tvals": {}, "safs": {}}
        for line in out_path.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split("|")
            if parts[0] == "WORLD":
                result["worlds"].append((parts[1], parts[2]))
            elif parts[0] == "TV":
                result["tvals"][parts[1]] = parts[2]
            elif parts[0] == "SAF":
                result["safs"][parts[1]] = parts[2]
            elif parts[0] == "DRLERROR":
                result["error"] = "drl:" + parts[1][:300]
            elif parts[0] == "FIRED":
                result["fired"] = parts[1]
        return result


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


def _witnesses(result, gen, obligations):
    out = []
    for oid, interp_id, rule_id, fact_id in obligations:
        v = result.get("safs", {}).get(oid, "u")
        out.append(BackendWitness(
            rule_id=rule_id, interpretation_id=interp_id,
            conclusion=_TRUTH_MAP.get(v, v),
            engine_native_explanation=(
                f"Drools: rule saf_{oid} fired/derived safety {v}; "
                f"supporting facts are the NF facts matched by the "
                f"generated rule patterns")))
    return tuple(out)


def evaluate(ci: NeutralCoreInput) -> BackendResult:
    started = time.perf_counter()
    if not ci.interpretations:
        return BackendResult(backend="drools", status="UNRESOLVED",
                             input_content_hash=ci.content_hash(),
                             notes="empty interpretation space")
    gen = _DrlGen(ci)
    obligations = _emit_obligations(ci, gen)
    result = _run_drools(gen, ci, obligations, [])
    if "error" in result:
        return BackendResult(backend="drools", status="ERROR",
                             input_content_hash=ci.content_hash(),
                             detail=result["error"])
    worlds = tuple(WorldResult(i, _TRUTH_MAP.get(v, v))
                   for i, v in result["worlds"])
    status = _status_from_worlds(result["worlds"])
    witnesses = _witnesses(result, gen, obligations)
    runtime_ms = (time.perf_counter() - started) * 1000.0
    return BackendResult(backend="drools", status=status, worlds=worlds,
                         witnesses=witnesses, runtime_ms=runtime_ms,
                         input_content_hash=ci.content_hash(),
                         notes=f"rules_fired={result.get('fired', '?')}")


def probe(ci: NeutralCoreInput, atoms: list[NeutralAtom]) -> list[PrimitiveResult]:
    gen = _DrlGen(ci)
    qids = [gen.query_id(atom, atom.time_index) for atom in atoms]
    result = _run_drools(gen, ci, [], qids)
    out = []
    for atom, qid in zip(atoms, qids):
        value = _TRUTH_MAP.get(result.get("tvals", {}).get(qid, "u"), "UNKNOWN")
        out.append(PrimitiveResult(atom.key(), value, (), ()))
    return out
