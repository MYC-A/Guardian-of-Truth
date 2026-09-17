#!/usr/bin/env python3
"""CLI for Semantic Pipeline V1; delegates all work to the Python API."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from guardian_truth.semantic_pipeline_v1 import SemanticPipelineConfig, run_experiment
from guardian_truth.settings import load_env_file


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input-dir", type=Path)
    source.add_argument("--input-file", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--semantic-frontend", choices=("current", "v1"), default="v1")
    parser.add_argument("--ablation", choices=tuple(f"A{i}" for i in range(9)), default="A5")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--case-id")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--enable-gliner", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--enable-langextract", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--retrieval-top-k", type=int, default=12)
    parser.add_argument("--neighbor-window", type=int, default=1)
    parser.add_argument("--mistral-model")
    parser.add_argument("--dry-run", action="store_true",
                        help="exercise I/O/cache/artifacts without loading or calling models")
    args = parser.parse_args(argv)
    load_env_file()
    ablation = "A0" if args.semantic_frontend == "current" else args.ablation
    overrides = {"device": args.device, "retrieval_top_k": args.retrieval_top_k,
                 "neighbor_window": args.neighbor_window}
    if args.enable_gliner is not None:
        overrides["enable_gliner"] = args.enable_gliner
    if args.enable_langextract is not None:
        overrides["enable_langextract"] = args.enable_langextract
    if args.cache_dir is not None:
        overrides["cache_dir"] = str(args.cache_dir)
    overrides["mistral_model"] = (args.mistral_model or os.environ.get("MISTRAL_MODEL")
                                   or os.environ.get("mistral_model")
                                   or SemanticPipelineConfig.mistral_model)
    config = SemanticPipelineConfig.for_ablation(ablation, **overrides)
    run_experiment(input_dir=args.input_dir, input_file=args.input_file,
                   output_dir=args.output_dir, config=config, resume=args.resume,
                   case_id=args.case_id, limit=args.limit, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
