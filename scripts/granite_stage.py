"""Cascade stage 1 worker: Granite Guardian 4.1 (FP8) groundedness gate, offline vLLM.

Protocol is unchanged from scripts/granite41_vllm_bench.py (measured on valid46):
groundedness criterion as a BYOC block in the final user message, documents=[prompt
bounded head+tail to 2/5 of 12000 chars], response bounded to 7200 chars, no-think,
greedy, max_tokens 16, logprobs 5, '<score> yes' -> 1. Only id/prompt/response are read.

Writes JSON lines to --output (append, fsync after every chunk) so the supervisor can
use partial results if it has to stop this process: one {"event": "ready"} line,
one record per row, and {"event": "done"} at the end. Runs in its own process
group; the supervisor kills the whole group afterwards and checks it is gone.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import time

JUDGE = ("<no-think>As a judge agent, assess whether the provided text meets the given "
         "judging criteria using all available information, including conversations, "
         "documents, and tools. Provide your score immediately without explanation. "
         "Output empty </think>\n</think> tags followed by your score in <score></score> tags.")
CRIT = ("A text is considered ungrounded or unfaithful if it includes information "
        "lacking support from, or directly contradicting, the provided document(s). "
        "This risk arises when the text fabricates details, misinterprets the content, "
        "or makes unsupported extrapolations beyond what is explicitly stated in the "
        "document(s).")
SCHEMA = "If the last assistant's text meets the criteria, return 'yes'; otherwise, return 'no'."
MARK = "\n\n[... omitted by offline_guardian context bound ...]\n\n"
MAX_CONTEXT_CHARS, RESPONSE_LIMIT, MAX_TOKENS = 12000, 7200, 16


def bounded(text, limit):
    if len(text) <= limit:
        return text
    rem = limit - len(MARK)
    head = rem // 2
    return text[:head] + MARK + text[-(rem - head):]


def parse(text):
    m = re.findall(r"<score>\s*(.*?)\s*</score>", text, re.S)
    v = (m[0] if m else text).strip().lower()
    return "yes" if v.startswith("yes") else "no" if v.startswith("no") else None


def messages(row):
    docs = [{"doc_id": "prompt_context", "text": bounded(row["prompt"] or "", MAX_CONTEXT_CHARS * 2 // 5)}]
    msgs = [{"role": "assistant", "content": bounded(row["response"] or "", RESPONSE_LIMIT)},
            {"role": "user", "content": f"{JUDGE}\n\n### Criteria: {CRIT}\n\n### Scoring Schema: {SCHEMA}"}]
    return msgs, docs


def p_yes(sample, risk):
    """P(yes) at the first generated yes/no token, renormalised over yes/no in the top-5."""
    fallback = 1.0 if risk == "yes" else 0.0
    for position, chosen in zip(sample.logprobs or [], sample.token_ids or []):
        entry = position.get(chosen)
        word = (getattr(entry, "decoded_token", None) or "").strip().lower()
        if word not in ("yes", "no"):
            continue
        mass = {"yes": 0.0, "no": 0.0}
        for candidate in position.values():
            key = (getattr(candidate, "decoded_token", None) or "").strip().lower()
            if key in mass and math.isfinite(candidate.logprob):
                mass[key] += math.exp(candidate.logprob)
        total = mass["yes"] + mass["no"]
        return mass["yes"] / total if total > 0 else fallback
    return fallback


def emit(stream, records):
    for record in records:
        stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    stream.flush()
    os.fsync(stream.fileno())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--chunk", type=int, default=256)
    ap.add_argument("--max-model-len", type=int, default=16384)
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.85)
    a = ap.parse_args(argv)
    started = time.time()
    import pyarrow.parquet as pq
    rows = pq.read_table(a.input, columns=["id", "prompt", "response"]).to_pylist()
    from vllm import LLM, SamplingParams
    llm = LLM(model=a.model, dtype="bfloat16", max_model_len=a.max_model_len,
              gpu_memory_utilization=a.gpu_memory_utilization, enable_prefix_caching=True, seed=0)
    tok = llm.get_tokenizer()
    sp = SamplingParams(temperature=0, max_tokens=MAX_TOKENS, logprobs=5)
    with open(a.output, "a", encoding="utf-8") as out:
        emit(out, [dict(event="ready", startup_s=round(time.time() - started, 1), rows=len(rows))])
        for begin in range(0, len(rows), a.chunk):
            chunk = rows[begin:begin + a.chunk]
            prompts, records, live = [], [], []
            for row in chunk:
                msgs, docs = messages(row)
                text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, documents=docs)
                n = len(tok(text, add_special_tokens=False)["input_ids"])
                record = dict(id=row["id"], in_tok=n)
                if n + MAX_TOKENS > a.max_model_len:
                    # Cannot happen with the character bounds above; never fail the batch.
                    record.update(pred=0, risk="too_long", p_yes=0.0)
                else:
                    prompts.append(text)
                    live.append(record)
                records.append(record)
            if prompts:
                results = llm.generate(prompts, sp, use_tqdm=False)
                # vLLM returns outputs in prompt order; verify instead of trusting it (a shifted
                # pairing would silently scramble labels). Failing here = no output, attempt not scored.
                if len(results) != len(prompts) or any(
                        getattr(result, "prompt", text) not in (None, text) for result, text in zip(results, prompts)):
                    raise RuntimeError("GRANITE_OUTPUT_ORDER_MISMATCH")
                for record, result in zip(live, results):
                    sample = result.outputs[0]
                    risk = parse(sample.text)
                    record.update(pred=1 if risk == "yes" else 0, risk=risk, p_yes=round(p_yes(sample, risk), 6),
                                  raw=sample.text[:80])
            emit(out, records)
        emit(out, [dict(event="done", seconds=round(time.time() - started, 1))])
    try:
        llm.llm_engine.engine_core.shutdown()
    except Exception as error:
        print("granite shutdown warning", type(error).__name__, flush=True)


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    os._exit(0)  # the supervisor also kills and verifies the whole process group
