"""FactCG's published DeBERTa inference format, kept separate from legacy smoke.

Port of derenlei/FactCG@41f1854, factcg/utils.py and inference.py: input
instruction, NLTK sentence/word chunking (550 words), per-chunk class-1
softmax and max aggregation. The source is MIT licensed. No thresholds are
fitted here; 0.5 is the paper's fixed-threshold setting.
"""
from __future__ import annotations

INSTRUCTION_TEMPLATE = (
    '{text_a}\n\nChoose your answer: based on the paragraph above can we '
    'conclude that "{text_b}"?\n\nOPTIONS:\n- Yes\n- No\nI think the answer is '
)


def chunk_context(context: str, max_chunk_size: int = 550) -> list[str]:
    from nltk.tokenize import sent_tokenize, word_tokenize

    sentences = sent_tokenize(context)
    chunks: list[str] = []
    current: list[str] = []
    count = 0
    for sentence in sentences:
        size = len(word_tokenize(sentence))
        if current and count + size > max_chunk_size:
            chunks.append("\n".join(current).replace(" \n ", "\n").strip())
            current, count = [], 0
        current.append(sentence)
        count += size
    if current:
        chunks.append("\n".join(current).replace(" \n ", "\n").strip())
    return chunks


def native_inputs(context: str, claim: str) -> list[str]:
    chunks = chunk_context(context)
    if not chunks:
        raise ValueError("FactCG cannot score an empty context")
    return [INSTRUCTION_TEMPLATE.format(text_a=chunk, text_b=claim)
            for chunk in chunks]


def native_score(model, tokenizer, context: str, claim: str, device) -> float:
    import torch

    scores = []
    for value in native_inputs(context, claim):
        # Matches FactCG Inferencer.tokenize's DeBERTa path. The original
        # catches overlong claims and falls back to truncation=True.
        try:
            enc = tokenizer([value], max_length=2048,
                            truncation="only_first", padding="longest",
                            return_tensors="pt")
        except Exception:
            enc = tokenizer([value], max_length=2048,
                            truncation=True, padding="longest",
                            return_tensors="pt")
        with torch.inference_mode():
            logits = model(**{k: v.to(device) for k, v in enc.items()}).logits
        scores.append(float(torch.softmax(logits, dim=-1)[0, 1].item()))
    return max(scores)
