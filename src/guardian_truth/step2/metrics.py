"""Step 2 scoring (section 28).

PRIMARY metric: WorldFact precision. An invented established fact is worse
than an honest UNKNOWN. Metrics are computed per arm over cases, with
separate counters for every failure category (section 36):

  wrong_effect_type      strength overclaimed vs gold
  overclaim_finality     gold REQUESTED/INITIATED, arm said EXECUTED/CONFIRMED
  wrong_entity           fact for the wrong entity id
  wrong_value            right predicate, wrong value
  wrong_time             temporal query answered from stale evidence
  stale_evidence         LATEST returned a superseded observation
  unsupported_inference  established fact not in gold at all
  wrong_result_pairing   provenance call_id does not match gold
  contract_ambiguity     oracle track: contract present but result ambiguous
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .types import EffectStrength, Truth

_STRENGTH_ORDER = ["NONE", "REQUESTED", "INITIATED", "EXECUTED", "CONFIRMED"]


def _strength_rank(strength: str) -> int:
    if strength == "OBSERVED":
        return -1
    return _STRENGTH_ORDER.index(strength) if strength in _STRENGTH_ORDER else 0


@dataclass
class CaseScore:
    case_id: str
    category: str
    arm: str
    gold_total: int = 0
    gold_established: int = 0
    established_total: int = 0          # verified + ungrounded (arms A/B/C)
    established_correct: int = 0
    unsupported_established: int = 0    # in unsupported_candidate_facts
    contradicted_established: int = 0   # in contradicted_facts
    invented_established: int = 0       # not in any gold list
    strength_exact: int = 0
    strength_overclaimed: int = 0
    strength_underclaimed: int = 0
    provenance_correct: int = 0
    temporal_total: int = 0
    temporal_correct: int = 0
    unknown_answers: int = 0
    unknown_on_unsupported: int = 0
    unsupported_probes: int = 0
    failures: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        out = {k: v for k, v in self.__dict__.items() if k != "failures"}
        out["failures"] = self.failures
        return out


def _norm_value(value: str) -> str:
    try:
        return json.dumps(json.loads(value), ensure_ascii=False)
    except (ValueError, TypeError):
        return value


def _match_fact(gold: dict, fact: dict) -> bool:
    """Match an established fact against a gold fact.

    Gold TRUE facts carry provenance; an arm fact matches when entity, value
    and (predicate OR exact provenance path+call) agree — the provenance is
    the real identity of an extractive fact, the predicate is its label.
    Unsupported/contradicted gold has no provenance: predicate+entity match.
    """
    gp = gold.get("provenance") or {}
    fp = fact.get("provenance") or {}
    entity_match = str(gold.get("entity_id")) == str(fact.get("entity_id") or fact.get("entity_value"))
    value_match = _norm_value(str(gold.get("value"))) == _norm_value(str(fact.get("value")))
    pred_match = gold.get("predicate") == fact.get("predicate")
    if gold.get("truth", "TRUE") == "TRUE":
        path_match = (bool(gp.get("json_path")) and gp.get("json_path") == fp.get("json_path")
                      and gp.get("call_id") == fp.get("call_id"))
        return entity_match and value_match and (pred_match or path_match)
    return entity_match and pred_match


def score_case(case: dict, arm_output: dict, temporal_answers: list[dict] | None = None) -> CaseScore:
    """Score one arm output against one case's gold.

    `case` is the dataset row; `arm_output` is ArmOutput.as_dict();
    `temporal_answers` is a list of {query, expected, actual}.
    """
    score = CaseScore(case_id=case["case_id"], category=case.get("category", "?"),
                      arm=arm_output["arm"])
    gold_facts = case.get("gold_facts", [])
    gold_true = [g for g in gold_facts if g.get("truth", "TRUE") == "TRUE"]
    unsupported = case.get("unsupported_candidate_facts", [])
    contradicted = case.get("contradicted_facts", [])
    score.gold_total = len(gold_true)

    established = ([v["fact"] for v in arm_output.get("verified", [])]
                   + arm_output.get("ungrounded", []))
    score.established_total = len(established)

    matched_gold_ids: set[int] = set()
    for fact in established:
        if not isinstance(fact.get("value"), str):
            fact = dict(fact, value=str(fact.get("value")))
        matched = None
        for i, gold in enumerate(gold_true):
            if _match_fact(gold, fact):
                matched = i
                break
        if matched is not None:
            matched_gold_ids.add(matched)
            score.established_correct += 1
            gold = gold_true[matched]
            gold_strength = gold.get("strength", "EXECUTED")
            arm_strength = fact.get("strength", "NONE")
            if gold_strength == arm_strength:
                score.strength_exact += 1
            elif _strength_rank(arm_strength) > _strength_rank(gold_strength):
                score.strength_overclaimed += 1
                score.failures.append({"kind": "wrong_effect_type/overclaim",
                                       "fact": _brief(fact), "gold_strength": gold_strength})
            else:
                score.strength_underclaimed += 1
            gold_prov = (gold.get("provenance") or {})
            arm_prov = (fact.get("provenance") or {})
            if (gold_prov.get("call_id") == arm_prov.get("call_id")
                    and gold_prov.get("json_path") == arm_prov.get("json_path")):
                score.provenance_correct += 1
            else:
                score.failures.append({"kind": "wrong_result_pairing/provenance",
                                       "fact": _brief(fact),
                                       "gold": {k: gold_prov.get(k) for k in ("call_id", "json_path")},
                                       "arm": {k: arm_prov.get(k) for k in ("call_id", "json_path")}})
            continue
        hit_unsupported = any(_match_fact(u, fact) for u in unsupported)
        hit_contradicted = any(_match_fact(c, fact) for c in contradicted)
        if hit_unsupported:
            score.unsupported_established += 1
            score.failures.append({"kind": "unsupported_inference", "fact": _brief(fact)})
        elif hit_contradicted:
            score.contradicted_established += 1
            score.failures.append({"kind": "overclaim_finality/contradicted",
                                   "fact": _brief(fact)})
        else:
            score.invented_established += 1
            score.failures.append({"kind": "unsupported_inference/invented",
                                   "fact": _brief(fact)})
    score.gold_established = len(matched_gold_ids)

    # temporal queries
    for item in (temporal_answers or []):
        score.temporal_total += 1
        expected = item.get("expected")
        actual = item.get("actual")
        if _norm_value(str(expected)) == _norm_value(str(actual)):
            score.temporal_correct += 1
        else:
            kind = "stale_evidence" if item.get("query") == "LATEST" else "wrong_time"
            score.failures.append({"kind": kind, "query": item.get("query"),
                                   "entity": item.get("entity"),
                                   "expected": expected, "actual": actual})
    # UNKNOWN calibration over probes: every unsupported candidate answered?
    score.unsupported_probes = len(unsupported) + len(contradicted)
    for fact in established:
        if any(_match_fact(u, fact) for u in unsupported) or \
           any(_match_fact(c, fact) for c in contradicted):
            continue
    answered = [f for f in established
                if any(_match_fact(u, f) for u in unsupported)
                or any(_match_fact(c, f) for c in contradicted)]
    score.unknown_on_unsupported = score.unsupported_probes - len(answered)
    return score


def _brief(fact: dict) -> dict:
    return {"predicate": fact.get("predicate"),
            "entity_id": fact.get("entity_id") or fact.get("entity_value"),
            "value": fact.get("value"), "strength": fact.get("strength")}


@dataclass
class Aggregate:
    arm: str
    cases: int = 0
    gold_total: int = 0
    gold_established: int = 0
    established_total: int = 0
    established_correct: int = 0
    unsupported_established: int = 0
    contradicted_established: int = 0
    invented_established: int = 0
    strength_exact: int = 0
    strength_matches: int = 0
    provenance_correct: int = 0
    provenance_matches: int = 0
    temporal_total: int = 0
    temporal_correct: int = 0
    unknown_on_unsupported: int = 0
    unsupported_probes: int = 0
    failures: list[dict] = field(default_factory=list)
    per_category: dict = field(default_factory=dict)

    @property
    def worldfact_precision(self) -> float | None:
        return (self.established_correct / self.established_total
                if self.established_total else None)

    @property
    def worldfact_recall(self) -> float | None:
        return (self.gold_established / self.gold_total
                if self.gold_total else None)

    @property
    def unsupported_effect_rate(self) -> float | None:
        bad = self.unsupported_established + self.contradicted_established + self.invented_established
        return (bad / self.established_total) if self.established_total else None

    @property
    def unknown_rate_on_unsupported(self) -> float | None:
        return (self.unknown_on_unsupported / self.unsupported_probes
                if self.unsupported_probes else None)

    def as_dict(self) -> dict:
        return {
            "arm": self.arm, "cases": self.cases,
            "gold_total": self.gold_total, "gold_established": self.gold_established,
            "established_total": self.established_total,
            "established_correct": self.established_correct,
            "unsupported_established": self.unsupported_established,
            "contradicted_established": self.contradicted_established,
            "invented_established": self.invented_established,
            "strength_exact_frac": (self.strength_exact / self.strength_matches
                                    if self.strength_matches else None),
            "provenance_correct_frac": (self.provenance_correct / self.provenance_matches
                                        if self.provenance_matches else None),
            "temporal_accuracy": (self.temporal_correct / self.temporal_total
                                  if self.temporal_total else None),
            "worldfact_precision": self.worldfact_precision,
            "worldfact_recall": self.worldfact_recall,
            "unsupported_effect_rate": self.unsupported_effect_rate,
            "unknown_rate_on_unsupported": self.unknown_rate_on_unsupported,
            "per_category": self.per_category,
            "failures": self.failures[:200],
        }


def aggregate(scores: list[CaseScore]) -> Aggregate:
    agg = Aggregate(arm=scores[0].arm if scores else "?")
    for s in scores:
        agg.cases += 1
        agg.gold_total += s.gold_total
        agg.gold_established += s.gold_established
        agg.established_total += s.established_total
        agg.established_correct += s.established_correct
        agg.unsupported_established += s.unsupported_established
        agg.contradicted_established += s.contradicted_established
        agg.invented_established += s.invented_established
        matched = s.established_correct
        agg.strength_matches += matched
        agg.strength_exact += s.strength_exact
        agg.provenance_matches += matched
        agg.provenance_correct += s.provenance_correct
        agg.temporal_total += s.temporal_total
        agg.temporal_correct += s.temporal_correct
        agg.unsupported_probes += s.unsupported_probes
        agg.unknown_on_unsupported += s.unknown_on_unsupported
        agg.failures.extend(s.failures)
        cat = s.category
        bucket = agg.per_category.setdefault(cat, {"cases": 0, "gold": 0,
                                                   "gold_est": 0, "est": 0, "est_ok": 0,
                                                   "unsupported": 0})
        bucket["cases"] += 1
        bucket["gold"] += s.gold_total
        bucket["gold_est"] += s.gold_established
        bucket["est"] += s.established_total
        bucket["est_ok"] += s.established_correct
        bucket["unsupported"] += (s.unsupported_established + s.contradicted_established
                                  + s.invented_established)
    return agg
