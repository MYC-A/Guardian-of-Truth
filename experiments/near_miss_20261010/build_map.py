"""Step A on the GPU host: sample tool maps for every unique policy with vLLM (offline engine).

    python build_map.py --model <dir> --policies policies.jsonl --out raw_samples.jsonl
policies.jsonl rows: {"key", "policy", "catalog"}. Writes one row per (key, replicate, sample).
Seeds are fixed: replicate A = 1,2,3; replicate B = 4,5,6. Temperature 0.7, thinking disabled.
Self-contained on purpose (only the prompt builder is imported) so it runs in the vLLM venv.
"""
import argparse
import json
import time

from experiments.near_miss_20261010.policy import messages

SEEDS = dict(A=[1, 2, 3], B=[4, 5, 6])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', required=True)
    ap.add_argument('--policies', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--max-model-len', type=int, default=32768)
    a = ap.parse_args()
    from vllm import LLM, SamplingParams
    pols = [json.loads(x) for x in open(a.policies, encoding='utf-8')]
    t0 = time.time()
    llm = LLM(model=a.model, max_model_len=a.max_model_len, gpu_memory_utilization=0.88,
              enable_prefix_caching=True, generation_config='vllm')
    jobs, convs, params = [], [], []
    for p in pols:
        for rep, seeds in SEEDS.items():
            for seed in seeds:
                jobs.append(dict(key=p['key'], replicate=rep, seed=seed))
                convs.append(messages(p['policy'], p['catalog']))
                params.append(SamplingParams(temperature=0.7, top_p=0.95, max_tokens=6144, seed=seed))
    t1 = time.time()
    outs = llm.chat(convs, params, chat_template_kwargs=dict(enable_thinking=False))
    with open(a.out, 'x', encoding='utf-8') as f:
        for j, o in zip(jobs, outs):
            c = o.outputs[0]
            f.write(json.dumps(dict(j, text=c.text, finish=c.finish_reason, tokens=len(c.token_ids)),
                               ensure_ascii=False) + '\n')
    print(json.dumps(dict(policies=len(pols), generations=len(jobs), load_s=round(t1 - t0, 1),
                          gen_s=round(time.time() - t1, 1))))


if __name__ == '__main__':
    main()
