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


def run_langextract(
    text: str,
    prompt_description: str,
    examples=None,
    thinking: bool = False,
    max_char_buffer: int = 2000,
    extraction_passes: int = 1,
    tag_prefix: str = "lx",
):
    """Run lx.extract with the z-ai provider. Returns list[AnnotatedDocument]."""
    import langextract as lx

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


def extractions_to_records(annotated, source_text: str) -> list[dict]:
    """Convert AnnotatedDocument extractions to plain records with spans."""
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
