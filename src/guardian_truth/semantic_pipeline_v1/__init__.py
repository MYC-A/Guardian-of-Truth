"""Semantic Pipeline V1 public API."""

from .config import SemanticPipelineConfig


def run_experiment(*args, **kwargs):
    # Lazy import keeps the deterministic types usable without ML dependencies.
    from .runner import run_experiment as _run
    return _run(*args, **kwargs)


__all__ = ["SemanticPipelineConfig", "run_experiment"]
