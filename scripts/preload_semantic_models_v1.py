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
    parser.add_argument("--gliner-python", default="/mnt/data/guardian/gliner2_env/bin/python")
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
    for stage in (item for item in args.models if item != "gliner"):
        model_name, loader = loaders[stage]
        with lifecycle.loaded(stage=f"preload:{stage}", model_name=model_name,
                              loader=lambda device, n=model_name, fn=loader: fn(n, device)):
            print(f"verified {stage}: {model_name}", flush=True)
    if "gliner" in args.models:
        from guardian_truth.semantic_pipeline_v1.models.gliner_optional import GLiNER2Sidecar
        adapter = GLiNER2Sidecar(model_name=config.gliner_model,
                                 python_executable=args.gliner_python)
        result = adapter.extract_batch([{"id": "smoke", "text":
            "Identity verification happens before the account is closed."}],
            device=lifecycle.resolved_device())
        lifecycle.record_external({
            "stage": "preload:gliner", "model": config.gliner_model,
            "device": result.get("device"), "load_duration_s": result.get("load_duration_s", 0),
            "execution_duration_s": result.get("execution_duration_s", 0),
            "max_allocated_vram_bytes": None, "max_reserved_vram_bytes": None,
            "process_isolated": True, "architecture": result.get("architecture")})
        print(json.dumps(result["rows"], ensure_ascii=False, indent=2), flush=True)
    print(json.dumps(lifecycle.records, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
