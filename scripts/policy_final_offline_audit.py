"""POLICY FINAL CYCLE - Stage A offline complementarity audit.

User spec sections 21-28 and 63-65: using ONLY the sealed predictions and
frozen gold of the PSB causal corpus (44 cases) and the GRS Stage A corpus
(56 cases) - no new LLM calls, no new parsing - measure:

  * per-pair complementarity (both / A-only / B-only / both wrong)
  * validity cross-tabs
  * behavioral agreement and WRONG AGREEMENT (agree but both wrong)
  * the deterministic FLATTENABILITY witness on predicted PSB graphs
    (FLATTENABLE / NON_FLATTENABLE / INVALID) with a gold cross-check
  * deterministic composition strategies over frozen outputs:
      HP1  PSB validity fallback (invalid PSB -> H0, else PSB)
      HP2a H0 primary + capacity witness switch (NON_FLATTENABLE -> PSB)
      HP2b H0 primary + capacity witness RETAIN ({H0, PSB})
      HP3  retain disagreement (invalid PSB -> H0; agree -> H0; else both)
      HG3  the HP3 pattern over H0 + GRS alternatives
  * set-valued metrics (gold-in-set, all-correct, singleton rate, mean set
    size, definitive coverage/accuracy, unsafe definitive, wrong agreement)
  * selection efficiency (oracle union recoverable vs actually recovered,
    router-caused regressions)

Routing signals (witness, agreement) are computed from predictions and the
supplied atom_catalog ONLY (never gold); gold is joined only for scoring.
The gold-surface agreement numbers are additionally reported as clearly
marked diagnostics.

Deterministic: no LLM, no network, no wall-clock.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))

from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal  # noqa: E402
from guardian_truth.vnext import policy_v3_benchmark as v3  # noqa: E402
from guardian_truth.vnext import policy_psb as psb  # noqa: E402
from guardian_truth.vnext import policy_grs as grs  # noqa: E402
from guardian_truth.vnext import policy_psb_causal_benchmark as psb_corpus  # noqa: E402
from guardian_truth.vnext import policy_grs_causal_benchmark as grs_corpus  # noqa: E402

OUT = ROOT / 'outputs' / 'vnext'
PSB_PREFIX = 'policy_psb_causal_v1'
GRS_PREFIX = 'policy_grs_stage_a_v1'
AUDIT_PATH = OUT / 'policy_final_v1_offline_audit.json'

# fields that must be shared by every program of a set for a single flat
# H0 structure to losslessly represent the whole set (target_clauses excepted)
_MERGE_FIELDS = ("modality", "relation", "condition_literals", "condition_mode",
                 "exception_literals", "exception_mode", "temporal", "actor",
                 "regulated_kind", "facet", "identity", "provenance",
                 "quantification")

_SURFACE_CAP = 10  # 2^10 = 1024 worlds max per case on the catalog surface


# ------------------------------------------------------------------- loading

def _load_psb():
    """Verify and load the sealed PSB artifacts (runner-hash supersession
    excepted, exactly like the disclosed post-hoc rescore)."""
    freeze = json.loads((OUT / f'{PSB_PREFIX}_freeze.json').read_text(encoding='utf-8'))
    bench = json.loads((OUT / f'{PSB_PREFIX}_benchmark.json').read_text(encoding='utf-8'))
    if freeze['benchmark_sha256'] != file_digest(OUT / f'{PSB_PREFIX}_benchmark.json'):
        raise ValueError('psb benchmark storage hash mismatch')
    if freeze['case_ids'] != [row['case_id'] for row in bench['cases']]:
        raise ValueError('psb frozen case identity mismatch')
    cases = []
    for row in bench['cases']:
        cases.append(psb_corpus.PolicyPSBCase(
            case_id=row['case_id'], cohort=row['cohort'], family=row['family'],
            style=row['style'], policy=row['policy'],
            atom_catalog=tuple(row['atom_catalog']),
            gold_graph=row['gold_graph'],
            admissible_program_sets=tuple(tuple(dict(p) for p in s)
                                          for s in row['admissible_program_sets']),
            worlds=tuple(dict(w) for w in row['worlds']),
            axes=tuple(row.get('axes', ())),
            h0_representable=row['h0_representable']))
    if freeze['gold_graph_sha256'] != digest(
            {case.case_id: case.gold_graph for case in cases}):
        raise ValueError('psb gold graphs changed after freeze')
    rows_by_arm = {}
    for arm in ('h0', 'psb'):
        rows = json.loads((OUT / f'{PSB_PREFIX}_{arm}_predictions.json')
                          .read_text(encoding='utf-8'))
        seal = json.loads((OUT / f'{PSB_PREFIX}_{arm}_prediction_seal.json')
                          .read_text(encoding='utf-8'))
        expected = prediction_seal(rows, [case.case_id for case in cases],
                                   architecture_commit=freeze['architecture_commit'],
                                   configuration_sha256=digest(freeze))
        if seal != expected:
            raise ValueError(f'psb {arm} prediction seal invalid')
        rows_by_arm[arm] = {row['case_id']: row for row in rows}
    return freeze, cases, rows_by_arm


def _load_grs():
    """Verify and load the sealed GRS Stage A artifacts (gold identity via
    deterministic corpus regeneration, like the independent revalidator)."""
    freeze = json.loads((OUT / f'{GRS_PREFIX}_freeze.json').read_text(encoding='utf-8'))
    bench = json.loads((OUT / f'{GRS_PREFIX}_benchmark.json').read_text(encoding='utf-8'))
    if freeze['benchmark_sha256'] != file_digest(OUT / f'{GRS_PREFIX}_benchmark.json'):
        raise ValueError('grs benchmark storage hash mismatch')
    cases = grs_corpus.build_grs_stage_a_benchmark()
    if freeze['case_ids'] != [case.case_id for case in cases]:
        raise ValueError('grs frozen case identity mismatch')
    if freeze['gold_dsl_sha256'] != digest(
            {case.case_id: case.gold_dsl for case in cases}):
        raise ValueError('grs gold dsl changed after freeze')
    if freeze['gold_inventory_sha256'] != digest(
            {case.case_id: case.oracle_inventory for case in cases}):
        raise ValueError('grs gold inventory changed after freeze')
    by_id = {row['case_id']: row for row in bench['cases']}
    if set(by_id) != {case.case_id for case in cases}:
        raise ValueError('grs stored benchmark case mismatch')
    rows_by_arm = {}
    for arm in ('a0', 'a1'):
        rows = json.loads((OUT / f'{GRS_PREFIX}_{arm}_predictions.json')
                          .read_text(encoding='utf-8'))
        seal = json.loads((OUT / f'{GRS_PREFIX}_{arm}_prediction_seal.json')
                          .read_text(encoding='utf-8'))
        expected = prediction_seal(rows, [case.case_id for case in cases],
                                   architecture_commit=freeze['architecture_commit'],
                                   configuration_sha256=digest(freeze))
        if seal != expected:
            raise ValueError(f'grs {arm} prediction seal invalid')
        rows_by_arm[arm] = {row['case_id']: row for row in rows}
    return freeze, cases, rows_by_arm, by_id


# ------------------------------------------------------- witness + surfaces

def flattenability_witness(programs, surface=None):
    """Deterministic representation-capacity witness for a COMPILED program
    set (the meaning of one predicted PSB graph, or one GRS alternative).

    FLATTENABLE      a single flat v3 structure losslessly represents the
                     set: all non-clause fields shared (a merge candidate
                     exists) AND the merged program is behaviorally
                     equivalent to the composed set on the check surface.
                     The behavioral check is REQUIRED: separate REQUIREMENT
                     clauses are separate obligations (composed VIOLATION
                     unless each is done), while a merged multi-clause
                     REQUIREMENT is satisfied by ANY clause - not
                     losslessly representable.
    NON_FLATTENABLE  no single flat structure can hold the set (per-clause
                     modality / actor / condition / exception / scope /
                     temporal / qualifier divergence, behavioral
                     merge-divergence, or an empty set which the flat
                     schema cannot express).

    surface: iterable of fact sets (gold-free catalog surface in routing
    use). When None, only the structural check runs (diagnostic mode).
    """
    if not programs:
        return "NON_FLATTENABLE", None
    if len(programs) == 1:
        return "FLATTENABLE", dict(programs[0])
    base = dict(programs[0])
    for program in programs[1:]:
        for field in _MERGE_FIELDS:
            if program.get(field) != base.get(field):
                return "NON_FLATTENABLE", None
    clauses = [list(clause) for program in programs
               for clause in program["target_clauses"]]
    base["target_clauses"] = sorted(clauses)
    if surface is not None:
        for facts in surface:
            if _flat_verdict(base, facts) != _set_verdict(programs, facts):
                return "NON_FLATTENABLE", None
    return "FLATTENABLE", base


def catalog_worlds(atom_catalog):
    """Gold-free behavioral check surface: every subset of the non-distractor
    catalog atoms (the catalog is model input, never gold). Deterministic
    order; capped at _SURFACE_CAP atoms (largest catalogs disclosed)."""
    atoms = sorted({a for a in atom_catalog if not a.startswith("distractor:")})
    capped = len(atoms) > _SURFACE_CAP
    if capped:
        atoms = atoms[:_SURFACE_CAP]
    n = len(atoms)
    worlds = []
    for mask in range(1 << n):
        facts = frozenset(atoms[i] for i in range(n) if mask >> i & 1)
        worlds.append(facts)
    return worlds, capped


def _flat_verdict(program, facts):
    return v3.evaluate_v3_program(program, facts)


def _set_verdict(programs, facts):
    return psb.composed_verdict(programs, facts)


def agree_flat_set(flat_program, program_set, surface):
    """Does one flat H0 meaning agree with one program-set meaning on every
    world of the surface?"""
    for facts in surface:
        if _flat_verdict(flat_program, facts) != _set_verdict(program_set, facts):
            return False
    return True


def agree_set_set(set_a, set_b, surface):
    for facts in surface:
        if _set_verdict(set_a, facts) != _set_verdict(set_b, facts):
            return False
    return True


# ------------------------------------------------------------ arm recompute

def _h0_meaning(row):
    prediction = row['prediction']
    if prediction is None:
        return None
    try:
        return [v3.compile_v3_structure(dict(prediction))]
    except (v3.StructureInvalid, ValueError, TypeError):
        return None


def _psb_meaning(row):
    prediction = row['prediction']
    if prediction is None:
        return None
    try:
        programs, _ = psb.compile_psb_graph(dict(prediction),
                                            permission_gate=False)
        return programs
    except (psb.PSBInvalid, ValueError, TypeError):
        return None


def _grs_meaning(row, inventory):
    prediction = row['prediction']
    if prediction is None or not isinstance(prediction.get('dsl'), str):
        return None
    try:
        alternatives, _dropped = grs.compile_dsl(prediction['dsl'], inventory)
        return alternatives
    except (grs.GRSInvalid, ValueError, TypeError):
        return None


def _meaning_correct(meaning, case, is_grs):
    if meaning is None:
        return False
    if is_grs:
        return grs.grs_score_prediction(meaning, case.worlds,
                                        case.admissible_program_sets)[0]
    return psb.score_program_set(meaning, case.worlds,
                                 case.admissible_program_sets)[0]


def _meaning_verdicts(meaning, surface, is_grs):
    """Verdict function of a meaning over the surface. GRS meanings carry
    alternatives (a list of program sets); returns the list of per-alternative
    verdict tuples for agreement logic."""
    if meaning is None:
        return None
    if is_grs:
        return [tuple(_set_verdict(alt, facts) for facts in surface)
                for alt in meaning]
    return tuple(_set_verdict(meaning, facts) for facts in surface)


# ------------------------------------------------------------- set metrics

def _unsafe_permission(meaning, case, is_grs):
    """The meaning asserts PERMITTED on some gold world where PERMITTED is
    not acceptable."""
    if meaning is None:
        return False
    worlds = case.worlds
    if is_grs:
        correct, per_world = grs.grs_score_prediction(
            meaning, case.worlds, case.admissible_program_sets)
        for w in per_world or []:
            verdicts = w.get('verdicts') or [w.get('verdict')]
            if any(v == 'PERMITTED' for v in verdicts) \
                    and 'PERMITTED' not in w.get('acceptable', []):
                return True
        return False
    correct, per_world = psb.score_program_set(
        meaning, case.worlds, case.admissible_program_sets)
    for w in per_world or []:
        if w.get('verdict') == 'PERMITTED' \
                and 'PERMITTED' not in w.get('acceptable', []):
            return True
    return False


def set_valued_metrics(records):
    """records: list of dicts with keys
    set (list of meanings, None = invalid meaning placeholder excluded),
    valid_flags, correct_flags, agree_all (definitive), unsafe_flags,
    h0_correct."""
    n = len(records)
    out = {}
    gold_in = sum(1 for r in records if any(r['correct_flags']))
    all_correct = sum(1 for r in records if r['correct_flags']
                      and all(r['correct_flags']))
    singleton = sum(1 for r in records if len(r['meanings']) == 1)
    definitive = sum(1 for r in records if r['definitive'])
    def_correct = sum(1 for r in records if r['definitive']
                      and any(r['correct_flags']))
    def_wrong = definitive - def_correct
    unsafe_def = sum(1 for r in records if r['definitive']
                     and any(r['unsafe_flags']))
    wrong_agreement = sum(1 for r in records if r['definitive']
                          and not any(r['correct_flags']))
    h0_correct = sum(1 for r in records if r['h0_correct'])
    h0_regress = sum(1 for r in records if r['h0_correct']
                     and not any(r['correct_flags']))
    out.update({
        'n': n,
        'gold_in_retained_set': gold_in,
        'gold_in_retained_set_rate': round(gold_in / n, 4),
        'all_retained_correct': all_correct,
        'all_retained_correct_rate': round(all_correct / n, 4),
        'singleton_rate': round(singleton / n, 4),
        'mean_set_size': round(sum(len(r['meanings']) for r in records) / n, 4),
        'definitive_coverage': round(definitive / n, 4),
        'definitive_count': definitive,
        'definitive_accuracy': round(def_correct / definitive, 4) if definitive else None,
        'definitive_wrong': def_wrong,
        'unsafe_definitive_rate': round(unsafe_def / n, 4),
        'wrong_agreement': wrong_agreement,
        'h0_baseline_correct': h0_correct,
        'h0_correct_regression': h0_regress,
        'h0_correct_regression_rate': round(h0_regress / h0_correct, 4) if h0_correct else None,
    })
    return out


def singleton_metrics(records):
    """records: list of dicts with chosen_correct, chosen_valid, h0_correct."""
    n = len(records)
    correct = sum(1 for r in records if r['chosen_correct'])
    valid = sum(1 for r in records if r['chosen_valid'])
    h0_correct = sum(1 for r in records if r['h0_correct'])
    corrections = sum(1 for r in records if r['h0_correct'] is False
                      and r['chosen_correct'])
    regressions = sum(1 for r in records if r['h0_correct']
                      and not r['chosen_correct'])
    return {
        'n': n, 'correct': correct, 'accuracy': round(correct / n, 4),
        'validity': round(valid / n, 4),
        'h0_baseline_correct': h0_correct,
        'corrections_vs_h0': corrections,
        'regressions_vs_h0': regressions,
        'regression_rate_of_h0_correct': round(regressions / h0_correct, 4)
        if h0_correct else None,
        'correction_precision': round(corrections / (corrections + regressions), 4)
        if corrections + regressions else None,
    }


# ----------------------------------------------------------------- analysis

def audit_psb(freeze, cases, rows_by_arm):
    n = len(cases)
    per_case = {}
    both = h0_only = psb_only = both_wrong = 0
    both_valid = h0_valid_n = psb_valid_n = 0
    agree_gold = disagree_gold = wrong_agree_gold = 0
    agree_cat = disagree_cat = wrong_agree_cat = 0
    witness_counts = {'FLATTENABLE': 0, 'NON_FLATTENABLE': 0, 'INVALID': 0}
    witness_gold_match = witness_gold_mismatch = 0
    behavioral_selfcheck_failures = 0
    unsafe_h0 = unsafe_psb = 0
    union_correct = 0

    for case in cases:
        h0_meaning = _h0_meaning(rows_by_arm['h0'][case.case_id])
        psb_meaning = _psb_meaning(rows_by_arm['psb'][case.case_id])
        h0_valid = h0_meaning is not None
        psb_valid = psb_meaning is not None
        h0_correct = _meaning_correct(h0_meaning, case, is_grs=False)
        psb_correct = _meaning_correct(psb_meaning, case, is_grs=False)
        both_valid += h0_valid and psb_valid
        h0_valid_n += h0_valid
        psb_valid_n += psb_valid
        both += h0_correct and psb_correct
        h0_only += h0_correct and not psb_correct
        psb_only += psb_correct and not h0_correct
        both_wrong += not h0_correct and not psb_correct
        union_correct += h0_correct or psb_correct
        unsafe_h0 += _unsafe_permission(h0_meaning, case, False)
        unsafe_psb += _unsafe_permission(psb_meaning, case, False)

        surface, capped = catalog_worlds(case.atom_catalog)
        # witness on the predicted PSB meaning (routing mode: catalog surface)
        if not psb_valid:
            witness = 'INVALID'
            merged = None
        else:
            witness, merged = flattenability_witness(psb_meaning, surface)
        witness_counts[witness] += 1

        # gold cross-check of the witness implementation (on GOLD graphs,
        # against the frozen h0_representable flags - behavioral surface)
        gold_programs, _ = psb.compile_psb_graph(case.gold_graph,
                                                 permission_gate=False)
        gold_surface = [frozenset(w['facts']) for w in case.worlds]
        gold_witness, gold_merged = flattenability_witness(gold_programs,
                                                           gold_surface)
        if gold_witness == ('NON_FLATTENABLE' if not case.h0_representable
                            else 'FLATTENABLE'):
            witness_gold_match += 1
        else:
            witness_gold_mismatch += 1

        # agreement (routing signal: catalog surface; diagnostic: gold surface)
        if h0_valid and psb_valid:
            if agree_flat_set(h0_meaning[0], psb_meaning,
                              [frozenset(w['facts']) for w in case.worlds]):
                agree_gold += 1
                if not h0_correct and not psb_correct:
                    wrong_agree_gold += 1
            else:
                disagree_gold += 1
            if agree_flat_set(h0_meaning[0], psb_meaning, surface):
                agree_cat += 1
                if not h0_correct and not psb_correct:
                    wrong_agree_cat += 1
            else:
                disagree_cat += 1

        per_case[case.case_id] = {
            'h0_valid': h0_valid, 'psb_valid': psb_valid,
            'h0_correct': h0_correct, 'psb_correct': psb_correct,
            'witness': witness, 'h0_representable_gold': case.h0_representable,
            'cohort': case.cohort, 'family': case.family,
        }

    complementarity = {
        'n': n,
        'both_correct': both, 'h0_only_correct': h0_only,
        'psb_only_correct': psb_only, 'both_wrong': both_wrong,
        'oracle_union_correct': union_correct,
        'oracle_union_rate': round(union_correct / n, 4),
        'validity': {'h0': h0_valid_n, 'psb': psb_valid_n,
                     'both_valid': both_valid},
        'agreement_gold_surface': {
            'agree': agree_gold, 'disagree': disagree_gold,
            'wrong_agreement': wrong_agree_gold,
            'note': 'diagnostic only (gold worlds); not usable for routing'},
        'agreement_catalog_surface': {
            'agree': agree_cat, 'disagree': disagree_cat,
            'wrong_agreement': wrong_agree_cat,
            'note': 'gold-free routing signal (atom_catalog subsets)'},
        'unsafe_permission': {'h0': unsafe_h0, 'psb': unsafe_psb},
        'witness_on_predictions': witness_counts,
        'witness_behavioral_selfcheck_failures': behavioral_selfcheck_failures,
        'witness_gold_crosscheck': {
            'match': witness_gold_match, 'mismatch': witness_gold_mismatch},
    }
    return complementarity, per_case


def evaluate_strategies_psb(cases, rows_by_arm, per_case):
    """HP1 / HP2a / HP2b / HP3 over frozen outputs; routing signals are
    gold-free (validity, witness, catalog-surface agreement)."""
    hp1, hp2a, hp2b, hp3 = [], [], [], []
    for case in cases:
        h0_meaning = _h0_meaning(rows_by_arm['h0'][case.case_id])
        psb_meaning = _psb_meaning(rows_by_arm['psb'][case.case_id])
        h0_valid = h0_meaning is not None
        psb_valid = psb_meaning is not None
        h0_correct = _meaning_correct(h0_meaning, case, False)
        surface, _ = catalog_worlds(case.atom_catalog)

        # HP1: validity fallback
        if psb_valid:
            chosen, chosen_valid = psb_meaning, True
        else:
            chosen, chosen_valid = h0_meaning, h0_valid
        hp1.append({'chosen_correct': _meaning_correct(chosen, case, False),
                    'chosen_valid': chosen_valid, 'h0_correct': h0_correct})

        # witness (routing mode: gold-free catalog surface)
        if not psb_valid:
            witness = 'INVALID'
        else:
            witness, _ = flattenability_witness(psb_meaning, surface)

        # HP2a: H0 primary, witness switch
        if psb_valid and witness == 'NON_FLATTENABLE':
            chosen, chosen_valid = psb_meaning, True
        else:
            chosen, chosen_valid = h0_meaning, h0_valid
        hp2a.append({'chosen_correct': _meaning_correct(chosen, case, False),
                     'chosen_valid': chosen_valid, 'h0_correct': h0_correct})

        # HP2b: H0 primary, witness retain
        if psb_valid and witness == 'NON_FLATTENABLE' and h0_valid:
            meanings = [h0_meaning, psb_meaning]
        elif psb_valid and witness == 'NON_FLATTENABLE':
            meanings = [psb_meaning]
        else:
            meanings = [h0_meaning] if h0_valid else []
        hp2b.append(_set_record(meanings, case, h0_correct, surface))

        # HP3: retain disagreement
        if not psb_valid:
            meanings = [h0_meaning] if h0_valid else []
        elif not h0_valid:
            meanings = [psb_meaning]
        elif agree_flat_set(h0_meaning[0], psb_meaning, surface):
            meanings = [h0_meaning]
        else:
            meanings = [h0_meaning, psb_meaning]
        hp3.append(_set_record(meanings, case, h0_correct, surface))

    return {
        'HP1_psb_validity_fallback': singleton_metrics(hp1),
        'HP2a_h0_primary_witness_switch': singleton_metrics(hp2a),
        'HP2b_h0_primary_witness_retain': set_valued_metrics(hp2b),
        'HP3_retain_disagreement': set_valued_metrics(hp3),
    }


def _set_record(meanings, case, h0_correct, surface):
    """Build one set-valued record from concrete meanings (never None)."""
    if not meanings:
        return {'meanings': [], 'correct_flags': [], 'unsafe_flags': [],
                'definitive': False, 'h0_correct': h0_correct,
                'unresolved': True}
    correct_flags = [_meaning_correct(m, case, False) for m in meanings]
    unsafe_flags = [_unsafe_permission(m, case, False) for m in meanings]
    definitive = True
    for i in range(len(meanings)):
        for j in range(i + 1, len(meanings)):
            if not agree_set_set(meanings[i], meanings[j], surface):
                definitive = False
    return {'meanings': meanings, 'correct_flags': correct_flags,
            'unsafe_flags': unsafe_flags, 'definitive': definitive,
            'h0_correct': h0_correct, 'unresolved': False}


def audit_grs(freeze, cases, rows_by_arm, bench_by_id):
    n = len(cases)
    both = h0_only = grs_only = both_wrong = 0
    both_valid = h0_valid_n = grs_valid_n = 0
    agree_cat = disagree_cat = wrong_agree_cat = 0
    unsafe_h0 = unsafe_grs = 0
    union_correct = 0
    multi_alt = 0
    per_case = {}
    for case in cases:
        h0_meaning = _h0_meaning(rows_by_arm['a0'][case.case_id])
        inventory = case.oracle_inventory
        grs_meaning = _grs_meaning(rows_by_arm['a1'][case.case_id], inventory)
        h0_valid = h0_meaning is not None
        grs_valid = grs_meaning is not None and len(grs_meaning) > 0
        grs_definitive = grs_valid and len(grs_meaning) == 1
        multi_alt += grs_valid and len(grs_meaning) > 1
        h0_correct = _meaning_correct(h0_meaning, case, False)
        grs_correct = _meaning_correct(grs_meaning, case, True)
        both_valid += h0_valid and grs_valid
        h0_valid_n += h0_valid
        grs_valid_n += grs_valid
        both += h0_correct and grs_correct
        h0_only += h0_correct and not grs_correct
        grs_only += grs_correct and not h0_correct
        both_wrong += not h0_correct and not grs_correct
        union_correct += h0_correct or grs_correct
        unsafe_h0 += _unsafe_permission(h0_meaning, case, False)
        unsafe_grs += _unsafe_permission(grs_meaning, case, True)
        surface, _ = catalog_worlds(case.atom_catalog)
        if h0_valid and grs_definitive:
            if agree_flat_set(h0_meaning[0], grs_meaning[0], surface):
                agree_cat += 1
                if not h0_correct and not grs_correct:
                    wrong_agree_cat += 1
            else:
                disagree_cat += 1
        per_case[case.case_id] = {
            'h0_valid': h0_valid, 'grs_valid': grs_valid,
            'grs_alternatives': len(grs_meaning) if grs_meaning else 0,
            'h0_correct': h0_correct, 'grs_correct': grs_correct,
            'cohort': case.cohort,
        }
    return {
        'n': n,
        'both_correct': both, 'h0_only_correct': h0_only,
        'grs_only_correct': grs_only, 'both_wrong': both_wrong,
        'oracle_union_correct': union_correct,
        'oracle_union_rate': round(union_correct / n, 4),
        'validity': {'h0': h0_valid_n, 'grs': grs_valid_n,
                     'both_valid': both_valid},
        'grs_multi_alternative_cases': multi_alt,
        'agreement_catalog_surface': {
            'comparable': agree_cat + disagree_cat,
            'agree': agree_cat, 'disagree': disagree_cat,
            'wrong_agreement': wrong_agree_cat,
            'note': 'gold-free routing signal; only GRS-definitive cases '
                    'are comparable'},
        'unsafe_permission': {'h0': unsafe_h0, 'grs': unsafe_grs},
    }, per_case


def _entries_agree(m_a, g_a, m_b, g_b, surface):
    """Behavioral agreement between two retained meanings. A GRS meaning is
    the full alternatives list (its own local ambiguity); it agrees with
    another meaning only when EVERY alternative agrees."""
    if not g_a and not g_b:
        return agree_set_set(m_a, m_b, surface)
    if g_a and not g_b:
        return all(agree_set_set(alt, m_b, surface) for alt in m_a)
    if g_b and not g_a:
        return all(agree_set_set(m_a, alt, surface) for alt in m_b)
    return all(agree_set_set(a, b, surface) for a in m_a for b in m_b)


def evaluate_strategy_hg3(cases, rows_by_arm):
    """H0 + GRS retained alternatives (HG3): GRS invalid -> H0; H0 invalid ->
    the GRS meaning (all its alternatives); single-alternative agreement ->
    H0; disagreement or local ONE_OF ambiguity -> retain both meanings."""
    records = []
    for case in cases:
        h0_meaning = _h0_meaning(rows_by_arm['a0'][case.case_id])
        grs_meaning = _grs_meaning(rows_by_arm['a1'][case.case_id],
                                   case.oracle_inventory)
        h0_valid = h0_meaning is not None
        grs_valid = grs_meaning is not None and len(grs_meaning) > 0
        h0_correct = _meaning_correct(h0_meaning, case, False)
        surface, _ = catalog_worlds(case.atom_catalog)
        # entries: (meaning, is_grs); a GRS meaning stays ONE entry carrying
        # all its alternatives (conjunction semantics preserved)
        if not grs_valid:
            entries = [(h0_meaning, False)] if h0_valid else []
        elif not h0_valid:
            entries = [(grs_meaning, True)]
        elif len(grs_meaning) == 1 and agree_flat_set(
                h0_meaning[0], grs_meaning[0], surface):
            entries = [(h0_meaning, False)]
        else:
            entries = [(h0_meaning, False), (grs_meaning, True)]
        if not entries:
            records.append({'meanings': [], 'correct_flags': [],
                            'unsafe_flags': [], 'definitive': False,
                            'h0_correct': h0_correct, 'unresolved': True})
            continue
        correct_flags = [_meaning_correct(m, case, g) for m, g in entries]
        unsafe_flags = [_unsafe_permission(m, case, g) for m, g in entries]
        definitive = all(_entries_agree(entries[i][0], entries[i][1],
                                        entries[j][0], entries[j][1], surface)
                         for i in range(len(entries))
                         for j in range(i + 1, len(entries)))
        records.append({'meanings': [m for m, _ in entries],
                        'correct_flags': correct_flags,
                        'unsafe_flags': unsafe_flags, 'definitive': definitive,
                        'h0_correct': h0_correct, 'unresolved': False})
    return set_valued_metrics(records)


def main() -> int:
    psb_freeze, psb_cases, psb_rows = _load_psb()
    grs_freeze, grs_cases, grs_rows, grs_bench = _load_grs()

    psb_comp, psb_per_case = audit_psb(psb_freeze, psb_cases, psb_rows)
    strategies = evaluate_strategies_psb(psb_cases, psb_rows, psb_per_case)
    grs_comp, grs_per_case = audit_grs(grs_freeze, grs_cases, grs_rows, grs_bench)
    hg3 = evaluate_strategy_hg3(grs_cases, grs_rows)

    report = {
        'schema_version': 'guardian-vnext-policy-final-offline-audit-v1',
        'experiment': 'POLICY_FINAL_CYCLE (user 75-section protocol)',
        'stage': 'A_offline_complementarity_audit',
        'new_llm_calls': 0,
        'inputs': {
            'psb': {'freeze_sha256': psb_freeze.get('freeze_sha256'),
                    'architecture_commit': psb_freeze['architecture_commit'],
                    'n_cases': len(psb_cases)},
            'grs': {'architecture_commit': grs_freeze['architecture_commit'],
                    'n_cases': len(grs_cases)},
        },
        'h0_psb_complementarity': psb_comp,
        'h0_psb_strategies': strategies,
        'h0_grs_complementarity': grs_comp,
        'h0_grs_strategy_HG3_retain': hg3,
        'psb_grs_pair': {
            'status': 'NOT_COMPUTABLE',
            'reason': 'no shared corpus: PSB ran on the 44-case PSB causal '
                      'benchmark, GRS on the 56-case GRS Stage A corpus; '
                      'paired per-case comparison is impossible without new '
                      'inference (deferred to the fresh final holdout, where '
                      'all candidates run on the same cases)'},
        'notes': [
            'routing signals (witness, catalog-surface agreement) use only '
            'predictions + the supplied atom_catalog; gold joined for scoring',
            'gold-surface agreement is reported as a diagnostic only',
            'all numbers recomputed from sealed artifacts; seals verified',
        ],
    }
    AUDIT_PATH.write_text(json.dumps(report, indent=1, sort_keys=False,
                                     default=str) + '\n', encoding='utf-8')

    # -------- console summary
    print('=== Stage A offline audit (no new LLM calls) ===')
    print()
    print('H0 vs PSB (44 sealed cases):')
    for k in ('both_correct', 'h0_only_correct', 'psb_only_correct',
              'both_wrong', 'oracle_union_correct'):
        print(f"  {k:22s} {psb_comp[k]}")
    print(f"  validity               H0 {psb_comp['validity']['h0']}/44  "
          f"PSB {psb_comp['validity']['psb']}/44  both {psb_comp['validity']['both_valid']}")
    print(f"  agreement (catalog)    agree {psb_comp['agreement_catalog_surface']['agree']}  "
          f"disagree {psb_comp['agreement_catalog_surface']['disagree']}  "
          f"wrong-agreement {psb_comp['agreement_catalog_surface']['wrong_agreement']}")
    print(f"  witness on predictions {psb_comp['witness_on_predictions']}  "
          f"gold crosscheck match {psb_comp['witness_gold_crosscheck']['match']}/44 "
          f"mismatch {psb_comp['witness_gold_crosscheck']['mismatch']}")
    print()
    print('H0+PSB deterministic strategies (development data):')
    for name, metrics in strategies.items():
        if 'accuracy' in metrics:
            print(f"  {name}: acc {metrics['accuracy']} ({metrics['correct']}/{metrics['n']}) "
                  f"validity {metrics['validity']} corr {metrics['corrections_vs_h0']} "
                  f"regr {metrics['regressions_vs_h0']}")
        else:
            print(f"  {name}: gold-in-set {metrics['gold_in_retained_set_rate']} "
                  f"all-correct {metrics['all_retained_correct_rate']} "
                  f"definitive {metrics['definitive_coverage']} "
                  f"def-acc {metrics['definitive_accuracy']} "
                  f"unsafe-def {metrics['unsafe_definitive_rate']} "
                  f"wrong-agree {metrics['wrong_agreement']} "
                  f"regr {metrics['h0_correct_regression']}")
    print()
    print('H0 vs GRS (56 sealed cases):')
    for k in ('both_correct', 'h0_only_correct', 'grs_only_correct',
              'both_wrong', 'oracle_union_correct'):
        print(f"  {k:22s} {grs_comp[k]}")
    print(f"  agreement (catalog)    {grs_comp['agreement_catalog_surface']}")
    print()
    print('H0+GRS HG3 retain strategy (development data):')
    m = hg3
    print(f"  gold-in-set {m['gold_in_retained_set_rate']} all-correct "
          f"{m['all_retained_correct_rate']} definitive {m['definitive_coverage']} "
          f"def-acc {m['definitive_accuracy']} unsafe-def {m['unsafe_definitive_rate']} "
          f"wrong-agree {m['wrong_agreement']} singleton {m['singleton_rate']}")
    print()
    print(f'audit written to {AUDIT_PATH}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
