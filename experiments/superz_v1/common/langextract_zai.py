"""Google LangExtract provider backed by the z-ai GLM bridge.

LangExtract organizes source-grounded extraction: the model is asked to
output extraction phrases, and LangExtract aligns them to exact char
intervals of the ORIGINAL text (with alignment_status). This module plugs
z-ai GLM (glm-4-plus) in as the inference engine, so grounding is real:
every extracted element is checked against source bytes.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langextract.core import base_model, types as core_types

from common.zai_client import chat


class ZaiLanguageModel(base_model.BaseLanguageModel):
    """LangExtract provider calling z-ai GLM through the cached bridge."""

    def __init__(self, thinking: bool = False, tag_prefix: str = "lx", **kwargs):
        super().__init__(**kwargs)
        self._thinking = thinking
        self._tag_prefix = tag_prefix
        self.n_calls = 0

    def infer(
        self, batch_prompts: Sequence[str], **kwargs
    ) -> Iterator[Sequence[core_types.ScoredOutput]]:
        # temperature etc are ignored by the bridge; z-ai default used.
        for prompt in batch_prompts:
            self.n_calls += 1
            resp = chat(
                user=prompt,
                system=(
                    "You are a precise information extraction engine. "
                    "Follow the output format requested in the prompt exactly. "
                    "Only use text copied from the provided source; never invent."
                ),
                thinking=self._thinking,
                tag=f"{self._tag_prefix}/{self.n_calls}",
            )
            if resp.ok:
                yield [core_types.ScoredOutput(output=resp.content, score=0.0)]
            else:
                # yield empty to let langextract record a gap honestly
                yield []


class MistralLanguageModel(base_model.BaseLanguageModel):
    """LangExtract provider calling Mistral (ministral-14b-latest) directly.

    Enables true cross-model theory construction: the SAME LangExtract
    grounding machinery runs over a DIFFERENT model.
    """

    def __init__(self, tag_prefix: str = "lxm", **kwargs):
        super().__init__(**kwargs)
        self._tag_prefix = tag_prefix
        self.n_calls = 0

    def infer(
        self, batch_prompts: Sequence[str], **kwargs
    ) -> Iterator[Sequence[core_types.ScoredOutput]]:
        for prompt in batch_prompts:
            self.n_calls += 1
            resp = chat(
                user=prompt,
                system=(
                    "You are a precise information extraction engine. "
                    "Follow the output format requested in the prompt exactly. "
                    "Only use text copied from the provided source; never invent."
                ),
                thinking=False,
                provider="mistral",
                tag=f"{self._tag_prefix}/{self.n_calls}",
            )
            if resp.ok:
                yield [core_types.ScoredOutput(output=resp.content, score=0.0)]
            else:
                yield []


def run_langextract(
    text: str,
    prompt_description: str,
    examples=None,
    thinking: bool = False,
    max_char_buffer: int = 2000,
    extraction_passes: int = 1,
    tag_prefix: str = "lx",
    model_provider: str = "zai",
):
    """Run lx.extract with the z-ai or Mistral provider. Returns (result, n_calls)."""
    import langextract as lx

    if model_provider == "mistral":
        model = MistralLanguageModel(tag_prefix=tag_prefix)
    else:
        model = ZaiLanguageModel(thinking=thinking, tag_prefix=tag_prefix)
    result = lx.extract(
        text,
        prompt_description=prompt_description,
        examples=examples,
        model=model,
        max_char_buffer=max_char_buffer,
        extraction_passes=extraction_passes,
        show_progress=False,
    )
    return result, model.n_calls


def _normalized_realign(source: str, text: str) -> tuple[int, int] | None:
    """Whitespace-insensitive re-alignment: locate `text` in `source`
    ignoring runs of whitespace (line-wrapped policies break exact spans)
    and markdown emphasis chars (models sometimes add **bold**/`code`
    markers absent from the source). Returns absolute (start, end) in the
    ORIGINAL source, or None.
    """
    import re as _re

    def norm(s: str) -> str:
        s = _re.sub(r"[*`]", "", s)  # strip emphasis markers added by the model
        return _re.sub(r"\s+", " ", s).strip().lower()

    n_src = norm(source)
    n_txt = norm(text)
    if not n_txt or len(n_txt) < 8:
        return None
    # token-index mapping: walk source once, remember offsets of non-space runs
    tokens_src = []
    pos = 0
    for m in _re.finditer(r"\S+", source):
        tokens_src.append((m.group(0), m.start(), m.end()))
        pos += 1
    joined = []
    offsets = []  # token idx -> (start_in_joined, len)
    cur = 0
    for tok, s, e in tokens_src:
        joined.append(tok.lower())
        offsets.append((cur, len(tok)))
        cur += len(tok) + 1
    joined_str = " ".join(joined)
    i = joined_str.find(n_txt)
    if i < 0:
        return None
    # map back: find token containing joined-index i and end
    start_tok = end_tok = None
    for idx, (j_start, j_len) in enumerate(offsets):
        if start_tok is None and j_start <= i < j_start + j_len + 1:
            start_tok = idx
        if j_start < i + len(n_txt) <= j_start + j_len + 1:
            end_tok = idx
            break
    if start_tok is None:
        return None
    if end_tok is None:
        # end may fall exactly on a space boundary
        for idx, (j_start, j_len) in enumerate(offsets):
            if j_start + j_len == i + len(n_txt) - 1:
                end_tok = idx
                break
    if end_tok is None:
        return None
    return (tokens_src[start_tok][1], tokens_src[end_tok][2])


def extractions_to_records(annotated, source_text: str) -> list[dict]:
    """Convert AnnotatedDocument extractions to plain records with spans.

    Unanchored extractions get ONE whitespace-insensitive re-alignment
    attempt (recovered=True); only if that fails they stay unanchored.
    """
    from langextract.core import data as lx_data

    out = []
    if isinstance(annotated, lx_data.AnnotatedDocument):
        docs = [annotated]
    else:
        docs = list(annotated)
    for doc in docs:
        for ext in doc.extractions:
            rec = {
                "class": ext.extraction_class,
                "text": ext.extraction_text,
                "description": ext.description,
                "alignment_status": str(ext.alignment_status),
            }
            if ext.char_interval is not None:
                rec["start"] = ext.char_interval.start_pos
                rec["end"] = ext.char_interval.end_pos
                # byte-exact verification against source
                rec["span_exact"] = (
                    source_text[rec["start"] : rec["end"]] == ext.extraction_text
                )
                if not rec["span_exact"]:
                    ra = _normalized_realign(source_text, ext.extraction_text)
                    if ra:
                        rec["start"], rec["end"] = ra
                        rec["span_exact"] = True
                        rec["realigned"] = True
            else:
                ra = _normalized_realign(source_text, ext.extraction_text)
                if ra:
                    rec["start"], rec["end"] = ra
                    rec["span_exact"] = True
                    rec["realigned"] = True
                else:
                    rec["start"] = None
                    rec["end"] = None
                    rec["span_exact"] = False
            attrs = ext.attributes or {}
            if isinstance(attrs, dict):
                rec["attributes"] = [
                    {"name": str(k), "text": str(v)} for k, v in attrs.items()
                ]
            else:
                rec["attributes"] = [
                    {
                        "name": getattr(a, "attribute_name", str(a)),
                        "text": getattr(a, "attribute_text", ""),
                    }
                    for a in attrs
                ]
            out.append(rec)
    return out
