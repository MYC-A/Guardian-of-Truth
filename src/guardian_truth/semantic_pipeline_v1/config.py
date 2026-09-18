"""Explicit, serializable configuration for Semantic Pipeline V1."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path


ABLATIONS = {
    "A0": dict(use_current_frontend=True, use_mistral=False, use_nuextract=False,
               use_nli=False, use_binding=False, core_backend="mistral"),
    "A1": dict(use_mistral=True, use_nuextract=False, use_nli=False, use_binding=False,
               core_backend="mistral"),
    # A2 must not gain a hidden Mistral call through the unchanged core.
    "A2": dict(use_mistral=False, use_nuextract=True, use_nli=False, use_binding=False,
               core_backend="unavailable"),
    "A3": dict(use_mistral=True, use_nuextract=True, use_nli=False, use_binding=False,
               core_backend="mistral"),
    "A4": dict(use_mistral=True, use_nuextract=True, use_nli=True, use_binding=False,
               core_backend="mistral"),
    "A5": dict(use_mistral=True, use_nuextract=True, use_nli=True, use_binding=True,
               core_backend="mistral"),
    "A6": dict(use_mistral=True, use_nuextract=True, use_nli=True, use_binding=True,
               enable_gliner=True, core_backend="mistral"),
    "A7": dict(use_mistral=True, use_nuextract=True, use_nli=True, use_binding=True,
               enable_langextract=True, core_backend="mistral"),
    "A8": dict(use_mistral=True, use_nuextract=True, use_nli=True, use_binding=True,
               enable_gliner=True, enable_langextract=True, core_backend="mistral"),
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
    gliner_python: str = "/mnt/data/guardian/gliner2_env/bin/python"
    gliner_timeout_seconds: float = 600.0
    langextract_model: str | None = None
    enable_gliner: bool = False
    enable_langextract: bool = False
    use_current_frontend: bool = False
    use_mistral: bool = True
    use_nuextract: bool = True
    use_nli: bool = True
    use_binding: bool = True
    core_backend: str = "mistral"
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
        if self.core_backend not in {"mistral", "unavailable"}:
            raise ValueError("core_backend must be mistral or unavailable")
        if self.gliner_timeout_seconds <= 0:
            raise ValueError("gliner_timeout_seconds must be positive")

    @classmethod
    def for_ablation(cls, name: str, **overrides) -> "SemanticPipelineConfig":
        if name not in ABLATIONS:
            raise ValueError(f"unknown ablation: {name}")
        values = dict(ABLATIONS[name])
        values.update(overrides)
        # Optional layers are off unless selected by A6-A8 or explicitly overridden.
        # Runs with LangExtract enabled are diagnostic-only until it has a provider.
        values.setdefault("enable_gliner", False)
        values.setdefault("enable_langextract", False)
        return cls(ablation=name, **values)

    def with_cache_dir(self, path: str | Path) -> "SemanticPipelineConfig":
        return replace(self, cache_dir=str(path))

    def as_dict(self) -> dict:
        value = asdict(self)
        value["experiment_class"] = self.experiment_class
        value["quality_evaluation_eligible"] = self.quality_evaluation_eligible
        return value

    @property
    def quality_evaluation_eligible(self) -> bool:
        # GLiNER hypotheses currently reach Phi/core only as unresolved bridge
        # evidence, while LangExtract has no configured provider. Neither can
        # change a proof verdict through a lossless lowering in V1.
        return (self.ablation not in {"A6", "A7", "A8"}
                and not self.enable_gliner and not self.enable_langextract)

    @property
    def diagnostic_reason(self) -> str | None:
        gliner = self.ablation in {"A6", "A8"} or self.enable_gliner
        langextract = self.ablation in {"A7", "A8"} or self.enable_langextract
        if gliner and langextract:
            return "DIAGNOSTIC_ONLY_GLINER2_AND_LANGEXTRACT"
        if gliner:
            return "DIAGNOSTIC_ONLY_GLINER2_NO_SAFE_CORE_LOWERING"
        if langextract:
            return "DIAGNOSTIC_ONLY_LANGEXTRACT"
        return None

    @property
    def experiment_class(self) -> str:
        return "quality-ablation" if self.quality_evaluation_eligible else "diagnostic-only"
