"""Explicit, serializable configuration for Semantic Pipeline V1."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path


ABLATIONS = {
    "A0": dict(use_current_frontend=True, use_mistral=False, use_nuextract=False,
               use_nli=False, use_binding=False),
    "A1": dict(use_mistral=True, use_nuextract=False, use_nli=False, use_binding=False),
    "A2": dict(use_mistral=False, use_nuextract=True, use_nli=False, use_binding=False),
    "A3": dict(use_mistral=True, use_nuextract=True, use_nli=False, use_binding=False),
    "A4": dict(use_mistral=True, use_nuextract=True, use_nli=True, use_binding=False),
    "A5": dict(use_mistral=True, use_nuextract=True, use_nli=True, use_binding=True),
    "A6": dict(use_mistral=True, use_nuextract=True, use_nli=True, use_binding=True,
               enable_gliner=True),
    "A7": dict(use_mistral=True, use_nuextract=True, use_nli=True, use_binding=True,
               enable_langextract=True),
    "A8": dict(use_mistral=True, use_nuextract=True, use_nli=True, use_binding=True,
               enable_gliner=True, enable_langextract=True),
}


@dataclass(frozen=True)
class SemanticPipelineConfig:
    """Every semantic or resource-affecting setting is recorded in run artifacts."""

    schema_version: str = "semantic-pipeline-v1"
    ablation: str = "A5"
    retrieval_top_k: int = 12
    neighbor_window: int = 1
    max_fragment_chars: int = 24_000
    mistral_model: str = "mistral-small-latest"
    nuextract_model: str = "numind/NuExtract3-W4A16"
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    nli_model: str = "cross-encoder/nli-deberta-v3-base"
    gliner_model: str = "fastino/gliner2.5-multi-v1"
    enable_gliner: bool = False
    enable_langextract: bool = False
    use_current_frontend: bool = False
    use_mistral: bool = True
    use_nuextract: bool = True
    use_nli: bool = True
    use_binding: bool = True
    cache_dir: str = ".guardian-cache/semantic-v1"
    device: str = "auto"
    mistral_api_key_env: str = "MISTRAL_API_KEY"
    mistral_max_output_tokens: int = 4096
    mistral_timeout_seconds: float = 120.0
    binding_top_k: int = 5
    nli_contradiction_threshold: float = 0.5

    def __post_init__(self) -> None:
        if self.ablation not in ABLATIONS:
            raise ValueError(f"unknown ablation: {self.ablation}")
        for name in ("retrieval_top_k", "max_fragment_chars", "binding_top_k",
                     "mistral_max_output_tokens"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.neighbor_window) is not int or self.neighbor_window < 0:
            raise ValueError("neighbor_window must be a non-negative integer")
        if not 0 <= self.nli_contradiction_threshold <= 1:
            raise ValueError("nli_contradiction_threshold must be in [0, 1]")
        if not self.mistral_api_key_env or "=" in self.mistral_api_key_env:
            raise ValueError("invalid Mistral key environment variable name")

    @classmethod
    def for_ablation(cls, name: str, **overrides) -> "SemanticPipelineConfig":
        if name not in ABLATIONS:
            raise ValueError(f"unknown ablation: {name}")
        values = dict(ABLATIONS[name])
        values.update(overrides)
        # Optional evidence layers are off unless selected by A6-A8 or overridden.
        values.setdefault("enable_gliner", False)
        values.setdefault("enable_langextract", False)
        return cls(ablation=name, **values)

    def with_cache_dir(self, path: str | Path) -> "SemanticPipelineConfig":
        return replace(self, cache_dir=str(path))

    def as_dict(self) -> dict:
        return asdict(self)
