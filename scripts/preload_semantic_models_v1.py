#!/usr/bin/env python3
"""Download and smoke-load Semantic V1 checkpoints one at a time."""

from __future__ import annotations

import argparse
import json

from guardian_truth.semantic_pipeline_v1.config import SemanticPipelineConfig
from guardian_truth.semantic_pipeline_v1.models.lifecycle import ModelLifecycleManager


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", choices=("embedding", "nuextract", "nli", "reranker", "gliner"),
                        default=("embedding", "nuextract", "nli", "reranker"))
    parser.add_argument("--device", default="auto")
    args = parser.parse_args(argv)
    config = SemanticPipelineConfig(device=args.device)
    lifecycle = ModelLifecycleManager(args.device)
    loaders = {}
    if "embedding" in args.models:
        from guardian_truth.semantic_pipeline_v1.models.embeddings import BGEEmbedder
        loaders["embedding"] = (config.embedding_model, BGEEmbedder.load)
    if "nuextract" in args.models:
        from guardian_truth.semantic_pipeline_v1.models.nuextract import NuExtractRuleExtractor
        loaders["nuextract"] = (config.nuextract_model, NuExtractRuleExtractor.load)
    if "nli" in args.models:
        from guardian_truth.semantic_pipeline_v1.models.nli import NLIFirewall
        loaders["nli"] = (config.nli_model, NLIFirewall.load)
    if "reranker" in args.models:
        from guardian_truth.semantic_pipeline_v1.models.reranker import BGEReranker
        loaders["reranker"] = (config.reranker_model, BGEReranker.load)
    if "gliner" in args.models:
        from guardian_truth.semantic_pipeline_v1.models.gliner_optional import GLiNEREvidenceExtractor
        loaders["gliner"] = (config.gliner_model, GLiNEREvidenceExtractor.load)
    for stage in args.models:
        model_name, loader = loaders[stage]
        with lifecycle.loaded(stage=f"preload:{stage}", model_name=model_name,
                              loader=lambda device, n=model_name, fn=loader: fn(n, device)):
            print(f"verified {stage}: {model_name}", flush=True)
    print(json.dumps(lifecycle.records, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
