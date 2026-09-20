"""RuleIR-lite -> ASP lowering + Clingo solving for architectures C and D.

RuleIR-lite (transport schema, LLM-produced):
{
 "rules": [{
   "id": "R1",
   "kind": "prohibition" | "obligation",
   "action": "refund",                      # action the rule governs ("*" = any)
   "conditions": [  # all must hold for the rule to APPLY
      {"type": "arg_gt"|"arg_lt"|"arg_gte"|"arg_lte"|"arg_equals",
       "field": "amount", "value": 10000},
      {"type": "flag_true"|"flag_false", "flag": "identity_verified"}
   ],
   "exceptions": [ {"type": "flag_true", "flag": "verified_this_session"} ],
   "unrepresentable_parts": ["..."]
 }],
 "unrepresentable_notes": ["..."]
}

Verdicts (4-valued, sound):
  proved_error    : some applicable rule violated by a performed action
  proved_no_error : actions performed, zero violations, zero unknowns/unreps
  unresolved      : otherwise (missing field, unknown flag, unrepresentable part)
"""
import clingo
import json
import re


def _asp_str(s):
    return '"' + str(s).replace('"', "'").replace("\n", " ")[:120] + '"'


ASP_PROGRAM = r"""
% grounded comparison relation over actually occurring (T,N,V) triples
cmp_holds(T,N,V) :- arg(_,F,num(N)), cond(_,_,argcmp,T,F,V), T = "arg_gt", N > V.
cmp_holds(T,N,V) :- arg(_,F,num(N)), cond(_,_,argcmp,T,F,V), T = "arg_lt", N < V.
cmp_holds(T,N,V) :- arg(_,F,num(N)), cond(_,_,argcmp,T,F,V), T = "arg_gte", N >= V.
cmp_holds(T,N,V) :- arg(_,F,num(N)), cond(_,_,argcmp,T,F,V), T = "arg_lte", N <= V.
cmp_holds(T,N,V) :- arg(_,F,num(N)), cond(_,_,argcmp,T,F,V), T = "arg_equals", N = V.

cond_true_act(R,I,A) :- cond(R,I,argcmp,T,F,V), action(_,A), arg(A,F,num(N)), cmp_holds(T,N,V).
cond_false_act(R,I,A) :- cond(R,I,argcmp,T,F,V), action(_,A), arg(A,F,num(N)), not cmp_holds(T,N,V).
cond_nofield_act(R,I,A) :- cond(R,I,argcmp,T,F,V), action(_,A), not arg(A,F,num(_)), not arg(A,F,str(_)).

flag_true_c(R,I) :- cond(R,I,flag,F,"true"), flag(true,F).
flag_true_c(R,I) :- cond(R,I,flag,F,"false"), flag(false,F).
flag_unknown_c(R,I) :- cond(R,I,flag,F,_), not flag(true,F), not flag(false,F).

exc_present_e(R,I) :- exc(R,I,actpresent,T), tool_called(T).
exc_absent_e(R,I) :- exc(R,I,actabsent,T), not tool_called(T).
flag_true_e(R,I) :- exc(R,I,flag,F,"true"), flag(true,F).
flag_true_e(R,I) :- exc(R,I,flag,F,"false"), flag(false,F).
flag_unknown_e(R,I) :- exc(R,I,flag,F,_), not flag(true,F), not flag(false,F).

acts_of_rule(R,A) :- rule(R,_,ActName), action(ActName,A).
acts_of_rule(R,A) :- rule(R,_,ActName), ActName = "*", action(_,A).

cond_ok(R,A) :- cond_true_act(R,I,A), acts_of_rule(R,A).
cond_ok(R,A) :- flag_true_c(R,I), acts_of_rule(R,A).
cond_ok(R,A) :- cond_present_c(R,I), acts_of_rule(R,A).
cond_ok(R,A) :- cond_absent_c(R,I), acts_of_rule(R,A).
cond_bad(R,A) :- cond_false_act(R,I,A), acts_of_rule(R,A).
cond_bad(R,A) :- flag_unknown_c(R,I), acts_of_rule(R,A).
cond_bad(R,A) :- cond_nofield_act(R,I,A), acts_of_rule(R,A).
cond_bad(R,A) :- cond(R,I,actpresent,T), acts_of_rule(R,A), not tool_called(T).
cond_bad(R,A) :- cond(R,I,actabsent,T), acts_of_rule(R,A), tool_called(T).

exc_global(R) :- flag_true_e(R,I).
exc_global(R) :- exc_present_e(R,I).
exc_global(R) :- exc_absent_e(R,I).
exc_holds(R,A) :- exc_global(R), acts_of_rule(R,A).
cond_present_c(R,I) :- cond(R,I,actpresent,T), tool_called(T).
cond_absent_c(R,I) :- cond(R,I,actabsent,T), not tool_called(T).

any_unknown :- flag_unknown_c(R,I).
any_unknown :- flag_unknown_e(R,I).
any_unknown :- cond_nofield_act(R,I,A).
any_unknown :- unrepresentable(_).
any_unknown :- rule_unrep(_, _).

cond_bad_any(R,A) :- cond_bad(R,A).
violation(R,A) :- rule(R,"prohibition",_), acts_of_rule(R,A),
    not cond_bad_any(R,A), not exc_holds(R,A), not any_unknown.
violation(R,A) :- rule(R,"obligation",_), acts_of_rule(R,A),
    cond_bad(R,A), not exc_holds(R,A), not any_unknown.
violation(R,"omitted") :- rule(R,"requirement",Tgt), Tgt != "*", not action(Tgt,_),
    not exc_global(R), not any_unknown.

proved_error :- violation(R,A).
proved_no_error :- action(_,A), not proved_error, not any_unknown.
#show proved_error/0. #show proved_no_error/0.
#show violation/2.
"""


def build_evidence_facts(events, response_analysis):
    facts = []
    for i, a in enumerate(response_analysis["actions"]):
        rid = f"a{i}"
        facts.append(f'action({_asp_str(a["name"])},{_asp_str(rid)}).')
        for k, v in (a.get("args") or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                facts.append(f'arg({_asp_str(rid)},{_asp_str(k)},num({v})).')
            else:
                facts.append(f'arg({_asp_str(rid)},{_asp_str(k)},'
                             f'str({_asp_str(json.dumps(v, ensure_ascii=False))})).')
    for f in response_analysis.get("flags", []):
        facts.append(f'flag({"true" if f["value"] else "false"},{_asp_str(f["name"])}).')
    for u in response_analysis.get("unrepresentable", []):
        facts.append(f'unrepresentable({_asp_str(u)}).')
    for t in response_analysis.get("tools_called", []):
        facts.append(f'tool_called({_asp_str(t)}).')
    return facts


def _cond_fact(rid, slot, i, c):
    t = c.get("type")
    if t in ("arg_gt", "arg_lt", "arg_gte", "arg_lte", "arg_equals"):
        return (f'{slot}({_asp_str(rid)},{i},argcmp,{_asp_str(t)},'
                f'{_asp_str(c.get("field",""))},{c.get("value", 0)}).')
    if t in ("flag_true", "flag_false"):
        want = '"true"' if t == "flag_true" else '"false"'
        return f'{slot}({_asp_str(rid)},{i},flag,{_asp_str(c.get("flag",""))},{want}).'
    if t == "action_present":
        return f'{slot}({_asp_str(rid)},{i},actpresent,{_asp_str(c.get("tool",""))}).'
    if t == "action_absent":
        cp = c.get("closure_premise") or ""
        if not cp:
            return None  # unsound without explicit closure premise
        return f'{slot}({_asp_str(rid)},{i},actabsent,{_asp_str(c.get("tool",""))}).'
    return None  # unrepresentable condition


def rule_facts(theory):
    facts = []
    for i, r in enumerate(theory.get("rules", [])):
        rid = str(r.get("id") or f"R{i+1}")
        r = dict(r, id=rid)
        kind = r.get("kind") or r.get("type") or "prohibition"
        facts.append(f'rule({_asp_str(rid)},{_asp_str(kind)},{_asp_str(r.get("action",""))}).')
        for ci, c in enumerate(r.get("conditions", [])):
            f = _cond_fact(rid, "cond", ci, c)
            if f is None:
                facts.append(f'rule_unrep({_asp_str(rid)},{_asp_str("cond:" + str(c))[:110]}).')
            else:
                facts.append(f)
        for ei, c in enumerate(r.get("exceptions", [])):
            f = _cond_fact(rid, "exc", ei, c)
            if f is None:
                facts.append(f'rule_unrep({_asp_str(rid)},{_asp_str("exc:" + str(c))[:110]}).')
            else:
                facts.append(f)
        for u in r.get("unrepresentable_parts", []) or []:
            facts.append(f'rule_unrep({_asp_str(rid)},{_asp_str(u)}).')
    for u in theory.get("unrepresentable_notes", []) or []:
        facts.append(f'unrepresentable({_asp_str(u)}).')
    return facts


def solve(facts, timeout=20):
    prg = "\n".join(facts) + "\n" + ASP_PROGRAM
    out = {"proved_error": False, "proved_no_error": False,
           "violations": [], "error": None}
    try:
        ctl = clingo.Control(["--stats=0"])
        ctl.add("base", [], prg)
        ctl.ground([("base", [])])
        with ctl.solve(yield_=True) as it:
            model = next(iter(it), None)
            if model is None:
                out["error"] = "no model"
                return out
            for sym in model.symbols(shown=True):
                name = str(sym.name)
                if name == "proved_error":
                    out["proved_error"] = True
                elif name == "proved_no_error":
                    out["proved_no_error"] = True
                elif name == "violation" and len(sym.arguments) == 2:
                    out["violations"].append([str(sym.arguments[0]).strip('"'),
                                              str(sym.arguments[1]).strip('"')])
    except Exception as e:
        out["error"] = str(e)[:300]
    return out


def analyze_response(events, prompt, response):
    """Deterministic extraction of assistant tool calls in target response +
    boolean-named flags from history tool responses (trusted JSON fields)."""
    actions = []
    for m in re.finditer(r"→\s*TOOL_CALL\s*([A-Za-z_][\w.]*)\s*:\s*", response):
        name = m.group(1)
        args = {}
        rest = response[m.end():]
        try:
            dec = json.JSONDecoder()
            obj, _ = dec.raw_decode(rest.lstrip())
            if isinstance(obj, dict):
                args = obj
        except Exception:
            pass
        actions.append({"name": name, "args": args, "span": (m.start(), m.end())})
    flags = []
    for e in events:
        if e.kind != "tool_response" or e.payload is None:
            continue

        def scan(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if isinstance(v, bool):
                        flags.append({"name": k, "value": v, "ts_idx": e.idx})
                    else:
                        scan(v)
            elif isinstance(o, list):
                for x in o:
                    scan(x)
        scan(e.payload)
    return {"actions": actions, "flags": flags, "unrepresentable": []}
