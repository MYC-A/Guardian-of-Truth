"""Freeze manifest: hashes of every inference-relevant file, prompts, models, suites and pre-registered rules."""
import hashlib, json, subprocess, sys
from experiments.multipacket_v1 import arms
from experiments.multipacket_v1.common import OUT, ROOT
from experiments.hybrid_mechanisms import interfaces

FILES = ['src/guardian_truth/evidence_packer/packer.py', 'src/guardian_truth/multipacket/packets.py',
         'src/guardian_truth/multipacket/ledger.py', 'src/guardian_truth/multipacket/controller.py',
         'experiments/multipacket_v1/arms.py', 'experiments/multipacket_v1/gaps.py', 'experiments/multipacket_v1/llm.py',
         'experiments/multipacket_v1/run.py', 'experiments/evidence_packer_v2/llm_eval.py', 'experiments/hybrid_mechanisms/interfaces.py',
         'outputs/multipacket_v1/baseline_cache/u2_replies.json', 'outputs/multipacket_v1/suite_syn_m1/inputs.jsonl',
         'outputs/multipacket_v1/suite_syn_m1/GOLD_eval_only.json']
RULES = {
    'unknown_to_binary': 'ERROR->1; NO_ERROR, UNKNOWN, technical null->0 (reported separately)',
    'degenerate': 'retrieval arms (C1,C2,D*,G2,G4) return A unchanged when the U2 20k packet is FULL_INPUT or when no new evidence is found',
    'D_final': 'primary = step-2 decision (model integrates ledger); secondary sticky = ERROR if any step ERROR',
    'C_aggregator': 'agree->agreed; ERROR vs other -> adjudication call on union of cited sources with both ledgers; NO_ERROR vs UNKNOWN -> NO_ERROR',
    'D3_trigger': 'third packet iff D2-final is UNKNOWN or differs from step 1',
    'G3_trigger': 'recheck iff first decision != ERROR and scan has applicability YES & violated TRUE',
    'G4': 'questions = A open questions + UNKNOWN scan assessments; PRIORITY search; <=2 QA rounds (depth<=1 follow-ups); S=4 hops/8000 chars, L=8/16000',
    'pilot': 'valid46 (contaminated, diagnostic), run 1, all non-oracle arms; oracle arms on ref15 only',
    'selection_for_SYN': 'per family (Parallel C1,C2 | Sequential D1,D2,D3 | Adaptive G2_S,G2_L,G3B,G3V,G4_S,G4_L) pick max(reason-correct TP - FP) on the valid46 pilot; tie -> fewer mean model calls; non-recursive gap arm = best of G2_*/G3*',
    'final_SYN': 'SYN-M1 (synthetic, 46 cases): A, B, FULL + selected arms; 3 runs (attempt index) for every selected arm if budget allows',
    'success': 'arm beats A only if mean F1 over runs higher AND reason-correct TP not lower AND paired sign test p<0.1; otherwise "not established"',
    'reason_judge': 'gpt-oss:120b via Ollama, same JUDGE_PROMPT as evidence_packer_v2, TP only, SAME/PARTIAL count as reason-correct',
    'budget': 'pilot <= ~900 reviewer calls (~8M tokens); SYN final <= ~1500 calls; stop and report if exceeded',
}


def main():
    sha = lambda p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
    man = dict(git_head=subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, cwd=ROOT).stdout.strip(),
               reviewer=dict(provider='mistral', model=arms.MODEL, temperature=0, max_tokens=1700, contract='I4 strict json_schema + admit'),
               prompts=dict(I4=hashlib.sha256((interfaces.PROMPT + interfaces.LABELS).encode()).hexdigest(),
                            ledger=hashlib.sha256(arms.LEDGER_ADDENDUM.encode()).hexdigest(),
                            adjudicate=hashlib.sha256(arms.ADJUDICATE_ADDENDUM.encode()).hexdigest(),
                            obligation=hashlib.sha256(arms.OBLIGATION_ADDENDUM.encode()).hexdigest(),
                            qa=hashlib.sha256(arms.QA_PROMPT.encode()).hexdigest()),
               arms=sorted(arms.ARMS), oracle_arms=list(arms.ORACLE_ARMS), files={f: sha(f) for f in FILES}, rules=RULES)
    man['manifest_sha256'] = hashlib.sha256(json.dumps(man, sort_keys=True).encode()).hexdigest()
    name = sys.argv[1] if len(sys.argv) > 1 else 'FREEZE_v1.json'
    (OUT / name).write_text(json.dumps(man, indent=1))
    print(name, man['manifest_sha256'])


if __name__ == '__main__':
    main()
