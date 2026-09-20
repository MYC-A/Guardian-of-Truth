"""ASP lowering v2: scoped unknowns + text-act/freshness evidence.

Difference from v1 (asp_lower.py):
- v1 had a GLOBAL any_unknown atom: one unrepresentable part of one rule, or one
  unknown flag anywhere, blocked every proof (sound but useless: 100% UNRESOLVED).
- v2 localizes unknowns per rule: an unrepresentable part or unknown condition of
  rule R blocks only violations that involve R. Global unrepresentable_notes only
  block proved_no_error (they certify incompleteness of the policy cover, not of
  a concrete violation).
- v2 accepts extra evidence facts produced by deterministic text-act analysis:
    text_report(Field, num(V))            - response text asserts a value V for field Field
    latest_value(Field, Entity, num(V))   - newest tool-response value for (Field, Entity)
  and supports two new theory condition types (all deterministically checkable):
    {"type": "text_report", "field": "balance"}          condition on speech act
    {"type": "value_is_latest", "field": "balance"}      exception: reported value == latest

Soundness notes:
- proved_error still requires a fully grounded applicable rule + performed action.
- proved_no_error still requires zero unknowns of ANY kind.
- UNRESOLVED remains the answer whenever any rule involved in the case has unknown parts
  and no other rule yields a proof.
"""
import clingo
import json
import re

def _asp_str(s):
    return '"' + str(s).replace('"', "'").replace("\n", " ")[:120] + '"'

ASP_PROGRAM = r"""
% ---------- grounded comparisons over actually occurring arg values ----------
cmp_holds(T,N,V) :- arg(_,F,num(N)), cond(_,_,argcmp,T,F,V), T = "arg_gt", N > V.
cmp_holds(T,N,V) :- arg(_,F,num(N)), cond(_,_,argcmp,T,F,V), T = "arg_lt", N < V.
cmp_holds(T,N,V) :- arg(_,F,num(N)), cond(_,_,argcmp,T,F,V), T = "arg_gte", N >= V.
cmp_holds(T,N,V) :- arg(_,F,num(N)), cond(_,_,argcmp,T,F,V), T = "arg_lte", N <= V.
cmp_holds(T,N,V) :- arg(_,F,num(N)), cond(_,_,argcmp,T,F,V), T = "arg_equals", N = V.

cond_true_act(R,I,A) :- cond(R,I,argcmp,T,F,V), action(_,A), arg(A,F,num(N)), cmp_holds(T,N,V).
cond_false_act(R,I,A) :- cond(R,I,argcmp,T,F,V), action(_,A), arg(A,F,num(N)), not cmp_holds(T,N,V).
cond_nofield_act(R,I,A) :- cond(R,I,argcmp,T,F,V), action(_,A), not arg(A,F,num(_)), not arg(A,F,str(_)).

% ---------- flags ----------
flag_true_c(R,I) :- cond(R,I,flag,F,"true"), flag(true,F).
flag_true_c(R,I) :- cond(R,I,flag,F,"false"), flag(false,F).
flag_unknown_c(R,I) :- cond(R,I,flag,F,_), not flag(true,F), not flag(false,F).
flag_true_e(R,I) :- exc(R,I,flag,F,"true"), flag(true,F).
flag_true_e(R,I) :- exc(R,I,flag,F,"false"), flag(false,F).
flag_unknown_e(R,I) :- exc(R,I,flag,F,_), not flag(true,F), not flag(false,F).

% ---------- action-present / absent ----------
exc_present_e(R,I) :- exc(R,I,actpresent,T), tool_called(T).
exc_absent_e(R,I) :- exc(R,I,actabsent,T), not tool_called(T).
cond_present_c(R,I) :- cond(R,I,actpresent,T), tool_called(T).
cond_absent_c(R,I) :- cond(R,I,actabsent,T), not tool_called(T).

% ---------- text acts & freshness (v2, deterministic evidence) ----------
cond_present_c(R,I) :- cond(R,I,textrep,F), text_report(F,_).
cond_absent_c(R,I)  :- cond(R,I,textrep,F), not text_report(F,_).
% value_is_latest exception holds iff EVERY reported value for F equals the
% latest tool value for F (any relevant entity). Violation of universality:
fresh_violated(F) :- text_report(F,N1), not latest_value(F,_,N1).
exc_global_fresh(R) :- exc(R,I,fresh,F), text_report(F,_), not fresh_violated(F).
% stale = reported value differs from the latest tool value for that field
stale_report(F) :- text_report(F,N1), latest_value(F,_,N2), N1 != N2.

% ---------- rule/action binding ----------
acts_of_rule(R,A) :- rule(R,_,ActName), action(ActName,A).
acts_of_rule(R,A) :- rule(R,_,ActName), ActName = "*", action(_,A).
% speech acts are first-class: a text report IS the action a "*" speech rule governs
acts_of_rule(R,"speech") :- rule(R,_,ActName), ActName = "*", text_report(_, _).

% ---------- condition satisfaction ----------
cond_ok(R,A) :- cond_true_act(R,I,A), acts_of_rule(R,A).
cond_ok(R,A) :- flag_true_c(R,I), acts_of_rule(R,A).
cond_ok(R,A) :- cond_present_c(R,I), acts_of_rule(R,A).
cond_ok(R,A) :- cond_absent_c(R,I), acts_of_rule(R,A).
cond_bad(R,A) :- cond_false_act(R,I,A), acts_of_rule(R,A).
cond_bad(R,A) :- cond(R,I,actpresent,T), acts_of_rule(R,A), not tool_called(T).
cond_bad(R,A) :- cond(R,I,actabsent,T), acts_of_rule(R,A), tool_called(T).
cond_bad(R,A) :- cond(R,I,textrep,F), acts_of_rule(R,A), not text_report(F,_).
% freshness exception kills stale-based violations:
exc_holds(R,A) :- exc_global_fresh(R), acts_of_rule(R,A).
exc_holds(R,A) :- flag_true_e(R,I), acts_of_rule(R,A).
exc_holds(R,A) :- exc_present_e(R,I), acts_of_rule(R,A).
exc_holds(R,A) :- exc_absent_e(R,I), acts_of_rule(R,A).

% ---------- v2: SCOPED unknowns ----------
rule_unknown(R) :- rule_unrep(R, _).
rule_unknown(R) :- flag_unknown_c(R,I).
rule_unknown(R) :- flag_unknown_e(R,I).
rule_unknown(R) :- cond_nofield_act(R,I,A), acts_of_rule(R,A).
global_unknown :- unrepresentable(_).

% ---------- violations ----------
cond_bad_any(R,A) :- cond_bad(R,A).
violation(R,A) :- rule(R,"prohibition",_), acts_of_rule(R,A),
    not cond_bad_any(R,A), not exc_holds(R,A), not rule_unknown(R).
violation(R,A) :- rule(R,"obligation",_), acts_of_rule(R,A),
    cond_bad(R,A), not exc_holds(R,A), not rule_unknown(R).
violation(R,"omitted") :- rule(R,"requirement",Tgt), Tgt != "*", not action(Tgt,_),
    not tool_called(Tgt), not exc_global(R), not rule_unknown(R).
% NOTE: tool_called(Tgt) guard = soundness fix: if the required tool was already
% called in HISTORY, a text-only response does not commit an omission (e.g. the
% agent reports from the fresh result it just fetched). A true omission requires
% the tool to be absent from the whole trajectory.
exc_global(R) :- flag_true_e(R,I).
exc_global(R) :- exc_present_e(R,I).
exc_global(R) :- exc_absent_e(R,I).

% stale reports: freshness exception silent only when report matches latest; otherwise
% any prohibition bound to that speech act via textrep condition is violated.
violation(R,A) :- rule(R,"prohibition",_), acts_of_rule(R,A),
    cond(R,I,textrep,F), stale_report(F), not rule_unknown(R), not exc_holds(R,A).

% ---------- verdicts ----------
proved_error :- violation(R,A).
speech_action :- text_report(_, _).
proved_no_error :- action(_,A), not proved_error, not any_unknown_u.
proved_no_error :- speech_action, not proved_error, not any_unknown_u.
% vacuous rules: the governed action was neither performed (response) nor called
% (history), and speech rules saw no text act -> they cannot be violated here,
% so their internal unknowns must not block the no-error certificate.
rule_vacuous(R) :- rule(R,_,ActName), ActName != "*",
    not action(ActName,_), not tool_called(ActName).
rule_vacuous(R) :- rule(R,_,ActName), ActName = "*",
    not action(_,_), not text_report(_,_).
any_unknown_u :- rule_unknown(R), not rule_vacuous(R).
any_unknown_u :- global_unknown.
#show proved_error/0. #show proved_no_error/0.
#show violation/2.
#show stale_report/1.
#show rule_unknown/1.
"""


def build_evidence_facts(events, response_analysis, text_acts=None, latest=None):
    """v1-compatible facts + optional v2 text-act facts.
    text_acts: {"reports": [(field, value)...]}
    latest:    [(field, entity, value)...]"""
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
    if text_acts:
        for rep in text_acts.get("reports", []):
            field, val = rep[0], rep[1]  # (field, value) or (field, value, entity)
            if isinstance(val, (int, float)):
                facts.append(f'text_report({_asp_str(field)},num({val})).')
            else:
                facts.append(f'text_report({_asp_str(field)},str({_asp_str(str(val))})).')
    if latest:
        for field, ent, val in latest:
            facts.append(f'latest_value({_asp_str(field)},{_asp_str(ent)},num({val})).')
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
            return None
        return f'{slot}({_asp_str(rid)},{i},actabsent,{_asp_str(c.get("tool",""))}).'
    if t == "text_report":
        return f'{slot}({_asp_str(rid)},{i},textrep,{_asp_str(c.get("field",""))}).'
    if t == "value_is_latest":
        return f'{slot}({_asp_str(rid)},{i},fresh,{_asp_str(c.get("field",""))}).'
    return None


def _repair_condition(c):
    """Deterministic schema repair for common LLM key drift (sound: only accepts
    unambiguous synonyms; never invents values). Returns repaired copy or None."""
    c = dict(c)
    t = c.get("type")
    if t in ("action_present", "action_absent") and not c.get("tool"):
        for alias in ("action", "tool_name", "name"):
            if c.get(alias):
                c["tool"] = c[alias]
                break
    if t in ("flag_true", "flag_false") and not c.get("flag"):
        for alias in ("name", "field", "flag_name"):
            if c.get(alias):
                c["flag"] = c[alias]
                break
    if t in ("arg_gt", "arg_lt", "arg_gte", "arg_lte", "arg_equals"):
        if not c.get("field"):
            for alias in ("arg", "arg_name", "name"):
                if c.get(alias):
                    c["field"] = c[alias]
                    break
        if "value" not in c:
            for alias in ("threshold", "val"):
                if isinstance(c.get(alias), (int, float)):
                    c["value"] = c[alias]
                    break
    # text_report / value_is_latest drift: "field" is usually present; accept "name"
    if t in ("text_report", "value_is_latest") and not c.get("field"):
        if c.get("name"):
            c["field"] = c["name"]
    return c


def rule_facts(theory):
    facts = []
    for i, r in enumerate(theory.get("rules", [])):
        rid = str(r.get("id") or f"R{i+1}")
        r = dict(r, id=rid)
        kind = r.get("kind") or r.get("type") or "prohibition"
        facts.append(f'rule({_asp_str(rid)},{_asp_str(kind)},{_asp_str(r.get("action",""))}).')
        for ci, c0 in enumerate(r.get("conditions", [])):
            c = _repair_condition(c0)
            f = _cond_fact(rid, "cond", ci, c)
            if f is None:
                facts.append(f'rule_unrep({_asp_str(rid)},{_asp_str("cond:" + str(c))[:110]}).')
            else:
                facts.append(f)
        for ei, c0 in enumerate(r.get("exceptions", [])):
            c = _repair_condition(c0)
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
           "violations": [], "stale": [], "unknown_rules": [], "error": None}
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
                elif name == "stale_report" and len(sym.arguments) == 1:
                    out["stale"].append(str(sym.arguments[0]).strip('"'))
                elif name == "rule_unknown" and len(sym.arguments) == 1:
                    out["unknown_rules"].append(str(sym.arguments[0]).strip('"'))
    except Exception as e:
        out["error"] = str(e)[:300]
    return out


# ---------------- deterministic text-act analysis ----------------

FIELD_LEXICON = {
    "balance": ["balance", "баланс", "остаток"],
    "price": ["price", "цена", "стоимость"],
    "amount": ["amount", "сумма"],
    "eta": ["eta", "arrival time", "время прибытия"],
}


LX_TEXTACT_EXAMPLES = [
    {
        "text": "The top-up is done. Your current balance on ACC-100241 is 8000 RUB.",
        "extractions": [
            {"extraction_class": "value_assertion",
             "extraction_text": "Your current balance on ACC-100241 is 8000 RUB",
             "attributes": {"field": "balance", "entity": "ACC-100241", "value": "8000"}},
        ],
    },
    {
        "text": "Ваш тариф: Стандарт, стоимость 350 руб/мес. Номер заказа ORD-778812 оформлен.",
        "extractions": [
            {"extraction_class": "value_assertion",
             "extraction_text": "стоимость 350 руб/мес",
             "attributes": {"field": "price", "entity": "", "value": "350"}},
        ],
    },
]


def analyze_text_acts_lx(response):
    """LangExtract-based value assertions: source-grounded (field, value, entity)
    bindings with verbatim char alignment. Returns {"reports": [(field, value, entity)]}.
    Falls back to None on any failure (caller decides)."""
    try:
        from common import langextract_runner as LR
        import langextract as lx
        examples = [lx.data.ExampleData(
            text=ex["text"],
            extractions=[lx.data.Extraction(**x) for x in ex["extractions"]])
            for ex in LX_TEXTACT_EXAMPLES]
        els = LR.extract(
            response,
            "Extract every assertion where the text states a concrete value for a "
            "named field (balance, price, amount, eta, date, count). Bind the field "
            "name, the exact value and the entity (account/order/phone id) it belongs to.",
            examples)
    except Exception:
        return None
    reports = []
    for e in els:
        if e.get("class") != "value_assertion":
            continue
        if not e.get("aligned_text"):
            continue  # unanchored -> not evidence
        attrs = e.get("attributes") or {}
        f = attrs.get("field")
        v = attrs.get("value")
        if not f or v is None:
            continue
        try:
            vf = float(str(v).replace(",", ".").replace(" ", ""))
        except (ValueError, TypeError):
            continue
        reports.append((str(f), int(vf) if vf == int(vf) else vf,
                        str(attrs.get("entity") or "")))
    return {"reports": reports}


def analyze_text_acts(response, latest_values=None):
    """Deterministic fallback (lexical binding, BRITTLE: identifier numbers can
    be mis-bound to fields - documented failure mode). Prefer analyze_text_acts_lx."""
    reports = []
    text = response
    low = text.lower()
    for field, kws in FIELD_LEXICON.items():
        for kw in kws:
            for m in re.finditer(re.escape(kw), low):
                lo = max(0, m.start() - 60)
                hi = min(len(text), m.end() + 80)
                window = text[lo:hi]
                nums = re.findall(r"(?<![\w.])(\d+(?:[.,]\d+)?)(?![\w])", window)
                if nums:
                    try:
                        v = float(nums[0].replace(",", "."))
                        reports.append((field, int(v) if v == int(v) else v))
                    except ValueError:
                        pass
                    break
    out = {"reports": reports}
    # latest values from tool responses
    latest = []
    if latest_values:
        latest = latest_values
    return out, latest


def latest_tool_values(events):
    """(field, entity, value) for numeric fields in tool responses; latest per (field,entity)."""
    from common import timeline as T
    best = {}
    for e in T.tool_responses(events):
        if e.payload is None:
            continue
        def scan(obj, ent):
            if isinstance(obj, dict):
                ent2 = obj.get("account") or obj.get("id") or obj.get("order_id") or ent
                for k, v in obj.items():
                    if isinstance(v, bool):
                        continue
                    if isinstance(v, (int, float)):
                        yield (str(k), str(ent2), v)
                    elif isinstance(v, dict):
                        yield from scan(v, ent2)
                    elif isinstance(v, list):
                        for x in v:
                            if isinstance(x, (dict,)):
                                yield from scan(x, ent2)
        for tup in scan(e.payload, "*"):
            key = (tup[0], tup[1])
            best[key] = tup  # events are in chronological order; last wins
    return [(f, ent, v) for (f, ent), (f2, ent2, v) in best.items()]
