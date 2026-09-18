"""Stage-major Semantic Pipeline V1 runner shared by the API and CLI."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import time

from guardian_truth.settings import load_env_file
from guardian_truth.vnext.adapters import AdapterMode
from guardian_truth.vnext.e2e.backend_v1 import E2ECachingBackend
from guardian_truth.vnext.e2e.competition_adapter_v1 import adapt_competition_input
from guardian_truth.vnext.e2e.e2e_types_v1 import E2EArmConfig, SEMANTICS_ARMS
from guardian_truth.vnext.e2e.json_extract_backend_v1 import JsonExtractBackend

from .binding import bind_candidate, rerank_candidate
from .cache import ContentAddressedCache, canonical_json, content_key
from .config import SemanticPipelineConfig
from .integration import run_existing_core
from .models.lifecycle import ModelLifecycleManager
from .models.mistral import MistralRuleExtractor
from .phi import build_phi
from .render import render_rule
from .retrieval import retrieve_fragments
from .source_timeline import build_source_timeline, verify_timeline
from .types import (ComponentState, NLIEvidence, RetrievedFragment, RetrievalResult, RuleCandidate,
                    SemanticInterpretationSet, to_wire)


@dataclass(frozen=True)
class InferenceRecord:
    case_id: str
    prompt: str
    response: str


@dataclass
class _CaseState:
    record: InferenceRecord
    safe_id: str
    case_dir: Path
    done_path: Path
    case_run_key: str
    started: float = field(default_factory=time.monotonic)
    timeline: object | None = None
    query: str = ""
    retrieval: RetrievalResult | None = None
    segment_by_id: dict = field(default_factory=dict)
    by_extractor: dict = field(default_factory=lambda: {"mistral": [], "nuextract": []})
    candidates: list[RuleCandidate] = field(default_factory=list)
    gliner_rows: list[dict] | None = None
    langextract_rows: dict | None = None
    nli_rows: list[dict] = field(default_factory=list)
    adapted: object | None = None
    tool_catalog: tuple = ()
    phi: SemanticInterpretationSet | None = None
    component_status: dict = field(default_factory=dict)
    stage_durations: dict[str, float] = field(default_factory=dict)


def _json_dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    sort_keys=True, default=str), encoding="utf-8")
    temporary.replace(path)


def _supported_files(input_dir: Path) -> list[Path]:
    return sorted(path for path in input_dir.rglob("*")
                  if path.is_file() and path.suffix.lower() in {".jsonl", ".json", ".csv", ".parquet"})


def _rows(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
    if suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("records"), list):
            value = value["records"]
        return value if isinstance(value, list) else [value]
    if suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))
    try:
        import pandas as pd
    except ImportError as error:
        raise RuntimeError("parquet input requires guardian-truth[data]") from error
    return pd.read_parquet(path).to_dict("records")


def load_input_records(*, input_dir: str | Path | None = None,
                       input_file: str | Path | None = None,
                       case_id: str | None = None, limit: int | None = None):
    """Return label-free inference records and a separate post-inference gold map."""
    if (input_dir is None) == (input_file is None):
        raise ValueError("provide exactly one of input_dir or input_file")
    paths = _supported_files(Path(input_dir)) if input_dir is not None else [Path(input_file)]
    records, gold, seen = [], {}, set()
    for path in paths:
        for row in _rows(path):
            missing = {"id", "prompt", "response"} - set(row)
            if missing:
                raise ValueError(f"{path}: missing fields {sorted(missing)}")
            identifier = str(row["id"])
            if identifier in seen:
                raise ValueError(f"duplicate case id: {identifier}")
            seen.add(identifier)
            if case_id is not None and identifier != case_id:
                continue
            records.append(InferenceRecord(identifier, str(row["prompt"]), str(row["response"])))
            if "label" in row and row["label"] not in (None, ""):
                raw = int(row["label"]) if isinstance(row["label"], str) else row["label"]
                if raw not in (0, 1):
                    raise ValueError(f"invalid binary label for {identifier}")
                gold[identifier] = int(raw)
            if limit is not None and len(records) >= limit:
                return records, gold
    if case_id is not None and not records:
        raise ValueError(f"case id not found: {case_id}")
    return records, gold


def _safe_case_id(case_id: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", case_id).strip("._") or "case"
    return stem[:100] + "__" + hashlib.sha256(case_id.encode()).hexdigest()[:10]


def _environment() -> dict:
    value = {"python": platform.python_version(), "platform": platform.platform(),
             "gpu_execution_observed": False,
             "hf_hub_offline": os.environ.get("HF_HUB_OFFLINE") == "1",
             "transformers_offline": os.environ.get("TRANSFORMERS_OFFLINE") == "1",
             "hf_home": os.environ.get("HF_HOME"),
             "hf_hub_cache": os.environ.get("HUGGINGFACE_HUB_CACHE")}
    try:
        import torch
        value.update({"torch": torch.__version__, "cuda_runtime": torch.version.cuda,
                      "cuda_available": bool(torch.cuda.is_available()),
                      "cuda_device_count": int(torch.cuda.device_count())})
        if torch.cuda.is_available():
            value["gpu_name"] = torch.cuda.get_device_name(0)
    except ImportError:
        value["torch"] = None
    return value


def _status(state: str | ComponentState, reason: str | None = None, **extra) -> dict:
    state = ComponentState(state).value
    return {"state": state, "executed": state == ComponentState.EXECUTED.value,
            "reason": reason, **extra}


def _duration(state: _CaseState, stage: str, started: float) -> None:
    state.stage_durations[stage] = round(
        state.stage_durations.get(stage, 0.0) + time.monotonic() - started, 6)


def _fragment_neighbors(timeline, segment_id: str, window: int) -> tuple[str, ...]:
    ordered = sorted(timeline.segments, key=lambda segment: segment.event_index)
    index = next((i for i, segment in enumerate(ordered) if segment.segment_id == segment_id), None)
    if index is None:
        return ()
    return tuple(ordered[i].exact_text for i in range(max(0, index - window),
                                                       min(len(ordered), index + window + 1))
                 if i != index)


def _retrieval_from_wire(value: dict) -> RetrievalResult:
    return RetrievalResult(tuple(RetrievedFragment(**item) for item in value["fragments"]),
                           tuple(value["routed_segment_ids"]),
                           tuple(value["unrouted_segment_ids"]),
                           tuple(value["source_coverage"]))


def _core_summary(analysis) -> dict:
    check = analysis.result.certificate_check
    return {"status": analysis.result.status.value,
            "prediction": analysis.product_decision.binary_label,
            "certificate_valid": bool(check.valid) if check is not None else None,
            "world_count": analysis.world_count, "required_worlds": analysis.required_worlds,
            "frontend_statuses": list(analysis.frontend_statuses),
            "diagnostics": {"primary_reason": (
                analysis.result.diagnostics.primary_reason.value
                if analysis.result.diagnostics.primary_reason else None),
                "missing_evidence": list(analysis.result.diagnostics.missing_evidence)}}


def _write_case_artifacts(case_dir: Path, *, state: _CaseState, core: dict,
                          summary: str) -> None:
    _json_dump(case_dir / "source_segments.json", to_wire(state.timeline))
    _json_dump(case_dir / "retrieved_fragments.json", to_wire(state.retrieval))
    _json_dump(case_dir / "mistral.json", [to_wire(item) for item in state.by_extractor["mistral"]])
    _json_dump(case_dir / "nuextract.json", [to_wire(item) for item in state.by_extractor["nuextract"]])
    _json_dump(case_dir / "gliner_evidence.json", {
        "status": state.component_status.get("gliner"), "rows": state.gliner_rows or []})
    _json_dump(case_dir / "langextract_alignment.json", state.langextract_rows or {
        "status": state.component_status.get("langextract"), "aligned_candidates": []})
    _json_dump(case_dir / "component_status.json", state.component_status)
    _json_dump(case_dir / "nli_checks.json", state.nli_rows)
    _json_dump(case_dir / "binding_candidates.json", [to_wire(item) for item in state.candidates])
    _json_dump(case_dir / "phi.json", to_wire(state.phi))
    _json_dump(case_dir / "core_result.json", core)
    (case_dir / "summary.txt").write_text(summary, encoding="utf-8")


def _metric_summary(rows: list[dict], gold: dict[str, int]) -> dict:
    metrics = {"cases": len(rows), "source_segments": sum(row["source_segments"] for row in rows),
               "retrieved_fragments": sum(row["retrieved_fragments"] for row in rows),
               "mistral_candidates": sum(row["mistral_candidates"] for row in rows),
               "nuextract_candidates": sum(row["nuextract_candidates"] for row in rows),
               "extractor_agreements": sum(row["extractor_agreements"] for row in rows),
               "extractor_disagreements": sum(row["extractor_disagreements"] for row in rows),
               "nli_contradictions": sum(row["nli_contradictions"] for row in rows),
               "nli_neutral": sum(row["nli_neutral"] for row in rows),
               "nli_entailment": sum(row["nli_entailment"] for row in rows),
               "average_phi_size": (sum(row["phi_size"] for row in rows) / len(rows) if rows else 0),
               "unresolved_bindings": sum(row["unresolved_bindings"] for row in rows),
               "core_statuses": {status: sum(row["core_status"] == status for row in rows)
                                 for status in ("PROVED_ERROR", "PROVED_NO_ERROR", "UNRESOLVED", "INCONSISTENT")}}
    scored = [row for row in rows if row["id"] in gold]
    if scored:
        tp = sum(row["prediction"] == 1 and gold[row["id"]] == 1 for row in scored)
        fp = sum(row["prediction"] == 1 and gold[row["id"]] == 0 for row in scored)
        fn = sum(row["prediction"] == 0 and gold[row["id"]] == 1 for row in scored)
        tn = sum(row["prediction"] == 0 and gold[row["id"]] == 0 for row in scored)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        metrics["post_inference_evaluation"] = {
            "TP": tp, "FP": fp, "FN": fn, "TN": tn, "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0}
    return metrics


def _initial_states(records, output: Path, config, resume: bool, dry_run: bool):
    active, predictions, timings = [], [], []
    for record in records:
        safe_id = _safe_case_id(record.case_id)
        case_dir = output / "cases" / safe_id
        done_path = case_dir / "complete.json"
        key = content_key(stage="completed_case", model="semantic-pipeline-v1",
                          config={**config.as_dict(), "dry_run": dry_run},
                          payload={"prompt": record.prompt, "response": record.response})
        if resume and done_path.is_file():
            previous = json.loads(done_path.read_text(encoding="utf-8"))
            if previous.get("case_run_key") == key:
                predictions.append(previous["prediction_row"])
                timings.append(previous["timing"])
                continue
        active.append(_CaseState(record, safe_id, case_dir, done_path, key))
    return active, predictions, timings


def run_experiment(*, input_dir=None, input_file=None, output_dir,
                   config: SemanticPipelineConfig | None = None, resume: bool = True,
                   case_id: str | None = None, limit: int | None = None,
                   dry_run: bool = False) -> dict:
    """Run V1 stage-major. Gold labels never enter any inference object or cache key."""
    load_env_file()
    if config is None:
        configured_model = (os.environ.get("MISTRAL_MODEL") or os.environ.get("mistral_model")
                            or SemanticPipelineConfig.mistral_model)
        config = SemanticPipelineConfig.for_ablation("A5", mistral_model=configured_model)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    cache_path = Path(config.cache_dir)
    if not cache_path.is_absolute():
        cache_path = output / cache_path
    cache = ContentAddressedCache(cache_path, resume=resume)
    lifecycle = ModelLifecycleManager(config.device)
    records, gold = load_input_records(input_dir=input_dir, input_file=input_file,
                                       case_id=case_id, limit=limit)
    environment = _environment()
    _json_dump(output / "environment.json", environment)
    _json_dump(output / "config.json", config.as_dict())
    _json_dump(output / "environment" / "config.json", config.as_dict())
    _json_dump(output / "environment" / "runtime.json", environment)
    manifest = {
        "schema_version": config.schema_version, "ablation": config.ablation,
        "semantic_frontend": "current" if config.use_current_frontend else "v1",
        "core_semantic_backend": config.core_backend, "execution_order": "stage-major",
        "dry_run": dry_run, "resume": resume, "case_count": len(records),
        "input_ids_sha256": hashlib.sha256(canonical_json(
            [record.case_id for record in records]).encode()).hexdigest(),
        "labels_crossed_inference_firewall": False, "cache_dir": str(cache_path),
        "hf_cache_note": "Hugging Face cache is distinct from Guardian content-addressed stage cache",
    }
    _json_dump(output / "run_manifest.json", manifest)
    states, predictions, timings = _initial_states(records, output, config, resume, dry_run)

    # Prepare every active case before loading any checkpoint.
    for state in states:
        started = time.monotonic()
        state.timeline = build_source_timeline(state.record.prompt, state.record.response)
        verify_timeline(state.timeline, state.record.prompt, state.record.response)
        state.segment_by_id = {segment.segment_id: segment for segment in state.timeline.segments}
        state.query = state.record.response + "\n" + " ".join(
            segment.exact_text for segment in state.timeline.segments if segment.source_type == "USER")
        try:
            state.adapted = adapt_competition_input({"id": state.record.case_id,
                "prompt": state.record.prompt, "response": state.record.response})
            state.tool_catalog = state.adapted.case.tool_schemas
        except ValueError:
            state.adapted = None
        _duration(state, "prepare", started)

    # Retrieval: inspect all cache entries first, then load BGE once for all misses.
    retrieval_misses = []
    for state in states:
        engine = "lexical" if dry_run or config.use_current_frontend else "bge-m3"
        key = content_key(stage="embedding_retrieval", model=config.embedding_model,
            config={"top_k": config.retrieval_top_k, "neighbor_window": config.neighbor_window,
                    "max_fragment_chars": config.max_fragment_chars, "retrieval_engine": engine},
            payload={"timeline": to_wire(state.timeline), "query": state.query})
        cached = cache.get("embedding_retrieval", key)
        if cached is not None:
            state.retrieval = _retrieval_from_wire(cached)
            state.component_status["retrieval"] = _status("EXECUTED", "CACHE_HIT", model=engine)
        else:
            retrieval_misses.append((state, key))
    if retrieval_misses and (dry_run or config.use_current_frontend):
        for state, key in retrieval_misses:
            started = time.monotonic()
            state.retrieval = retrieve_fragments(
                state.timeline, query=state.query, top_k=config.retrieval_top_k,
                neighbor_window=config.neighbor_window, max_fragment_chars=config.max_fragment_chars)
            cache.put("embedding_retrieval", key, to_wire(state.retrieval))
            state.component_status["retrieval"] = _status("EXECUTED", model="lexical")
            _duration(state, "retrieval", started)
    elif retrieval_misses:
        from .models.embeddings import BGEEmbedder
        with lifecycle.loaded(stage="embedding_retrieval", model_name=config.embedding_model,
                              loader=lambda device: BGEEmbedder.load(config.embedding_model, device)) as (model, _):
            embedder = BGEEmbedder(config.embedding_model, model, cache=cache)
            for state, key in retrieval_misses:
                started = time.monotonic()
                state.retrieval = retrieve_fragments(
                    state.timeline, query=state.query, top_k=config.retrieval_top_k,
                    neighbor_window=config.neighbor_window, max_fragment_chars=config.max_fragment_chars,
                    embedder=embedder)
                cache.put("embedding_retrieval", key, to_wire(state.retrieval))
                state.component_status["retrieval"] = _status("EXECUTED", model=config.embedding_model)
                _duration(state, "retrieval", started)

    # Remote Mistral is shared by frontend extraction and the explicitly named core backend.
    mistral = None
    needs_mistral = bool(states) and not dry_run and (
        config.use_mistral or config.use_current_frontend or config.core_backend == "mistral")
    if needs_mistral:
        mistral = MistralRuleExtractor(
            model=config.mistral_model, api_key_env=config.mistral_api_key_env,
            max_output_tokens=config.mistral_max_output_tokens,
            timeout_seconds=config.mistral_timeout_seconds, cache=cache)
        mistral.client.validate_configuration()
    for state in states:
        if config.use_mistral and not dry_run:
            started = time.monotonic()
            for fragment in state.retrieval.fragments:
                state.by_extractor["mistral"].extend(mistral.extract(
                    segment_id=fragment.segment_id, source_text=fragment.exact_text,
                    context=_fragment_neighbors(state.timeline, fragment.segment_id,
                                                config.neighbor_window)))
            state.component_status["mistral_frontend"] = _status(
                "EXECUTED", model=config.mistral_model)
            _duration(state, "mistral_frontend", started)
        else:
            state.component_status["mistral_frontend"] = _status(
                "DISABLED", "DRY_RUN" if dry_run else "ABLATION_DISABLED")

    # NuExtract: one checkpoint load, all cases/fragments, one unload.
    if config.use_nuextract and states and not dry_run:
        from .models.nuextract import NuExtractRuleExtractor
        with lifecycle.loaded(stage="nuextract", model_name=config.nuextract_model,
                loader=lambda device: NuExtractRuleExtractor.load(config.nuextract_model, device)) as (loaded, _):
            model, processor = loaded
            extractor = NuExtractRuleExtractor(model_name=config.nuextract_model, model=model,
                                                processor=processor, cache=cache)
            for state in states:
                started = time.monotonic()
                for fragment in state.retrieval.fragments:
                    state.by_extractor["nuextract"].extend(extractor.extract(
                        segment_id=fragment.segment_id, source_text=fragment.exact_text,
                        context=_fragment_neighbors(state.timeline, fragment.segment_id,
                                                    config.neighbor_window)))
                state.component_status["nuextract"] = _status(
                    "EXECUTED", model=config.nuextract_model)
                _duration(state, "nuextract", started)
    else:
        for state in states:
            state.component_status["nuextract"] = _status(
                "DISABLED", "DRY_RUN" if dry_run else "ABLATION_DISABLED")
    for state in states:
        state.candidates = [*state.by_extractor["mistral"], *state.by_extractor["nuextract"]]

    # GLiNER2.5 runs once, in a Transformers-4.x sidecar environment.
    if config.enable_gliner and states and not dry_run:
        from .models.gliner_optional import GLiNER2Sidecar, GLiNER2SidecarError
        if not Path(config.gliner_python).is_file():
            for state in states:
                state.component_status["gliner"] = _status(
                    "UNAVAILABLE", "SIDECAR_PYTHON_NOT_FOUND", python=config.gliner_python)
        else:
            pending, cached_rows = [], {}
            for state in states:
                state.gliner_rows = []
                for fragment in state.retrieval.fragments:
                    key = content_key(stage="gliner2", model=config.gliner_model,
                        config={"entities": GLiNER2Sidecar.ENTITY_LABELS,
                                "relations": GLiNER2Sidecar.RELATION_LABELS},
                        payload={"text": fragment.exact_text})
                    cached = cache.get("gliner2", key)
                    item_id = f"{state.safe_id}:{fragment.segment_id}"
                    if cached is None:
                        pending.append((state, fragment, key, item_id))
                    else:
                        cached_rows[item_id] = cached
            try:
                if pending:
                    adapter = GLiNER2Sidecar(model_name=config.gliner_model,
                        python_executable=config.gliner_python,
                        timeout_seconds=config.gliner_timeout_seconds)
                    response = adapter.extract_batch([
                        {"id": item_id, "text": fragment.exact_text}
                        for _, fragment, _, item_id in pending],
                        device=lifecycle.resolved_device())
                    lifecycle.record_external({
                        "stage": "gliner2_sidecar", "model": config.gliner_model,
                        "device": response.get("device"),
                        "load_duration_s": response.get("load_duration_s", 0),
                        "execution_duration_s": response.get("execution_duration_s", 0),
                        "max_allocated_vram_bytes": None, "max_reserved_vram_bytes": None,
                        "process_isolated": True, "architecture": response.get("architecture")})
                    returned = {row["id"]: row for row in response["rows"]}
                    for _, _, key, item_id in pending:
                        row = returned[item_id]
                        cache.put("gliner2", key, row)
                        cached_rows[item_id] = row
                for state in states:
                    state.gliner_rows = [cached_rows[f"{state.safe_id}:{fragment.segment_id}"]
                                         for fragment in state.retrieval.fragments]
                    state.component_status["gliner"] = _status(
                        "EXECUTED", model=config.gliner_model,
                        process="isolated-subprocess", cached=not pending)
            except (GLiNER2SidecarError, KeyError, ValueError) as error:
                for state in states:
                    state.component_status["gliner"] = _status(
                        "FAILED", "SIDECAR_ERROR", error=str(error))
    else:
        for state in states:
            state.component_status["gliner"] = _status(
                "DISABLED", "DRY_RUN" if dry_run else "ABLATION_DISABLED")

    # NLI: one load over all candidates.
    nli_states = [state for state in states if state.candidates]
    if config.use_nli and nli_states and not dry_run:
        from .models.nli import NLIFirewall
        with lifecycle.loaded(stage="nli", model_name=config.nli_model,
                              loader=lambda device: NLIFirewall.load(config.nli_model, device)) as (model, _):
            firewall = NLIFirewall(config.nli_model, model)
            for state in states:
                started, checked = time.monotonic(), []
                for candidate in state.candidates:
                    rendering = render_rule(candidate.rule)
                    premise = "\n".join(span.quote for span in candidate.source_spans) or \
                              state.segment_by_id[candidate.source_segment_ids[0]].exact_text
                    key = content_key(stage="nli", model=config.nli_model, config={},
                                      payload={"premise": premise, "hypothesis": rendering})
                    raw = cache.get("nli", key)
                    if raw is None:
                        evidence = firewall.check(premise, rendering)
                        raw = to_wire(evidence)
                        cache.put("nli", key, raw)
                    else:
                        evidence = NLIEvidence(raw["label"], raw["scores"], tuple(raw["logits"]),
                                               raw["model"], raw["rendering"])
                    state.nli_rows.append({"candidate_id": candidate.candidate_id, **raw})
                    checked.append(replace(candidate,
                                           nli_evidence=(*candidate.nli_evidence, evidence)))
                state.candidates = checked
                state.component_status["nli"] = _status("EXECUTED", model=config.nli_model)
                _duration(state, "nli", started)
    else:
        for state in states:
            reason = "NO_CANDIDATES" if config.use_nli and not dry_run else (
                "DRY_RUN" if dry_run else "ABLATION_DISABLED")
            state.component_status["nli"] = _status("DISABLED", reason)

    # Binding BGE and reranker each load once across the complete case batch.
    binding_states = [s for s in states if s.candidates and s.tool_catalog]
    if config.use_binding and binding_states and not dry_run:
        from .models.embeddings import BGEEmbedder
        with lifecycle.loaded(stage="binding_embedding", model_name=config.embedding_model,
                              loader=lambda device: BGEEmbedder.load(config.embedding_model, device)) as (model, _):
            embedder = BGEEmbedder(config.embedding_model, model, cache=cache)
            for state in binding_states:
                started = time.monotonic()
                entities = tuple(dict.fromkeys(re.findall(
                    r'\b[A-Za-z][A-Za-z0-9_-]*\d+[A-Za-z0-9_-]*\b', state.record.prompt)))
                state.candidates = [bind_candidate(item, state.tool_catalog,
                    entity_candidates=entities, embedder=embedder, top_k=config.binding_top_k)
                    for item in state.candidates]
                _duration(state, "binding_embedding", started)
        from .models.reranker import BGEReranker
        with lifecycle.loaded(stage="binding_rerank", model_name=config.reranker_model,
                              loader=lambda device: BGEReranker.load(config.reranker_model, device)) as (model, _):
            reranker = BGEReranker(config.reranker_model, model, cache=cache)
            for state in binding_states:
                started = time.monotonic()
                state.candidates = [rerank_candidate(item, state.tool_catalog, reranker=reranker)
                                    for item in state.candidates]
                state.component_status["binding"] = _status(
                    "EXECUTED", models=[config.embedding_model, config.reranker_model])
                _duration(state, "binding_rerank", started)
        for state in states:
            if state not in binding_states:
                state.component_status["binding"] = _status("DISABLED", "NO_CANDIDATES_OR_CATALOG")
    else:
        for state in states:
            reason = "NO_CANDIDATES_OR_CATALOG" if config.use_binding and not dry_run else (
                "DRY_RUN" if dry_run else "ABLATION_DISABLED")
            state.component_status["binding"] = _status("DISABLED", reason)

    # LangExtract does not contain a model. Without an explicit provider it is
    # unavailable, never a successful no-op.
    for state in states:
        state.phi = build_phi(state.candidates, state.retrieval.source_coverage,
                              contradiction_threshold=config.nli_contradiction_threshold)
        if config.enable_langextract and not dry_run:
            from .models.langextract_optional import LangExtractAligner, LangExtractUnavailable
            aligner = LangExtractAligner(model_id=config.langextract_model)
            status = aligner.status()
            state.component_status["langextract"] = status
            if status["state"] == "EXECUTED":
                try:
                    aligned = aligner.align(state.record.prompt,
                                            [to_wire(item) for item in state.candidates])
                    state.langextract_rows = {"status": status, "mode": "span-alignment-only",
                        "changed_semantics": False, "aligned_candidates": aligned}
                except LangExtractUnavailable as error:
                    state.component_status["langextract"] = _status(
                        "UNAVAILABLE", str(error))
        else:
            state.component_status["langextract"] = _status(
                "DISABLED", "DRY_RUN" if dry_run else "ABLATION_DISABLED")

    current_backend = semantic_backend = None
    if mistral is not None:
        current_tag = hashlib.sha256(canonical_json({"model": config.mistral_model,
            "max_output_tokens": config.mistral_max_output_tokens,
            "frontend": "current-B4h"}).encode()).hexdigest()[:16]
        semantic_tag = hashlib.sha256(canonical_json({"model": config.mistral_model,
            "max_output_tokens": config.mistral_max_output_tokens,
            "frontend": "semantic-v1"}).encode()).hexdigest()[:16]
        current_backend = E2ECachingBackend(JsonExtractBackend(mistral.client, interval_seconds=0),
                                             cache_path=cache_path / f"current_core__{current_tag}.json")
        semantic_backend = E2ECachingBackend(JsonExtractBackend(mistral.client, interval_seconds=0),
                                              cache_path=cache_path / f"v1_core__{semantic_tag}.json")

    # Final proof-core integration remains case-local, after every model stage.
    for position, state in enumerate(states, 1):
        started = time.monotonic()
        if dry_run:
            core_result = {"status": "UNRESOLVED", "prediction": 0,
                           "certificate_valid": None, "reason": "DRY_RUN_NO_MODELS"}
            state.component_status["core_semantic_backend"] = _status("DISABLED", "DRY_RUN")
        elif state.adapted is None:
            core_result = {"status": "UNRESOLVED", "prediction": 0,
                "certificate_valid": None, "reason": "INPUT_NOT_COMPATIBLE_WITH_EXISTING_CORE_ADAPTER"}
            state.component_status["core_semantic_backend"] = _status("UNAVAILABLE", "INPUT_ADAPTER_FAILED")
        elif config.core_backend == "unavailable":
            core_result = {"status": "UNRESOLVED", "prediction": 0,
                "certificate_valid": None, "reason": "CORE_SEMANTIC_BACKEND_NOT_CONFIGURED",
                "bridge_unresolved": list(state.phi.unresolved)}
            state.component_status["core_semantic_backend"] = _status(
                "UNAVAILABLE", "ABLATION_HAS_NO_REMOTE_SEMANTIC_BACKEND")
        elif config.use_current_frontend:
            from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1
            guardian = GuardianE2EV1(current_backend,
                arm=E2EArmConfig("B4h", ("h0_hist",), ("conservative",)),
                adapter_mode=AdapterMode.COMPETITION, semantics=SEMANTICS_ARMS["B3"])
            core_result = _core_summary(guardian.analyze_e2e_v1(state.adapted.case))
            state.component_status["core_semantic_backend"] = _status(
                "EXECUTED", model=config.mistral_model)
        else:
            system_ids = {segment.segment_id for segment in state.timeline.segments
                          if segment.source_type == "SYSTEM"}
            knowledge_ids = {fragment.segment_id for fragment in state.retrieval.fragments
                             if "knowledge-result-guarantee" in fragment.reasons}
            normative_ids = {candidate.source_segment_ids[0] for candidate in state.phi.interpretations
                              if candidate.rule.modality != "UNKNOWN"
                              and candidate.source_segment_ids
                              and candidate.source_segment_ids[0] in knowledge_ids}
            policy_ids = frozenset(system_ids | normative_ids)
            knowledge_texts = tuple(state.segment_by_id[identifier].exact_text
                                    for identifier in sorted(normative_ids))
            analysis, bridge_unresolved = run_existing_core(
                state.adapted.case, state.phi, backend=semantic_backend,
                policy_segment_ids=policy_ids, additional_normative_texts=knowledge_texts,
                arm=E2EArmConfig("B4h", ("h0_hist",), ("conservative",)),
                adapter_mode=AdapterMode.COMPETITION, semantics=SEMANTICS_ARMS["B3"])
            core_result = {**_core_summary(analysis),
                           "bridge_unresolved": list(bridge_unresolved)}
            state.component_status["core_semantic_backend"] = _status(
                "EXECUTED", model=config.mistral_model)
        _duration(state, "core", started)

        digest_sets = {name: {item.canonical_digest for item in values}
                       for name, values in state.by_extractor.items()}
        agreements = len(digest_sets["mistral"] & digest_sets["nuextract"])
        disagreements = len(digest_sets["mistral"] ^ digest_sets["nuextract"])
        labels = [row["label"] for row in state.nli_rows]
        prediction_row = {
            "id": state.record.case_id, "prediction": core_result["prediction"],
            "core_status": core_result["status"], "source_segments": len(state.timeline.segments),
            "retrieved_fragments": len(state.retrieval.fragments),
            "mistral_candidates": len(state.by_extractor["mistral"]),
            "nuextract_candidates": len(state.by_extractor["nuextract"]),
            "extractor_agreements": agreements, "extractor_disagreements": disagreements,
            "nli_contradictions": labels.count("CONTRADICTION"),
            "nli_neutral": labels.count("NEUTRAL"),
            "nli_entailment": labels.count("ENTAILMENT"),
            "phi_size": len(state.phi.interpretations),
            "unresolved_bindings": sum(any(value.startswith("ambiguous-")
                for value in item.unresolved_components) for item in state.candidates)}
        timing = {"id": state.record.case_id,
                  "total_duration_s": round(time.monotonic() - state.started, 6),
                  "stage_durations_s": state.stage_durations}
        summary = (f"case_id: {state.record.case_id}\ncore_status: {core_result['status']}\n"
                   f"prediction: {core_result['prediction']}\nphi_size: {len(state.phi.interpretations)}\n"
                   f"unresolved: {len(state.phi.unresolved)}\n")
        _write_case_artifacts(state.case_dir, state=state, core=core_result, summary=summary)
        if case_id is not None:
            _write_case_artifacts(output / "traces" / state.safe_id,
                                  state=state, core=core_result, summary=summary)
        _json_dump(state.done_path, {"case_id": state.record.case_id,
            "case_run_key": state.case_run_key, "prediction_row": prediction_row,
            "timing": timing})
        predictions.append(prediction_row)
        timings.append(timing)
        print(f"semantic-v1 {position}/{len(states)} {state.record.case_id} {core_result['status']}",
              flush=True)

    order = {record.case_id: index for index, record in enumerate(records)}
    predictions.sort(key=lambda row: order[row["id"]])
    timings.sort(key=lambda row: order[row["id"]])
    with (output / "predictions.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "label"], lineterminator="\n")
        writer.writeheader()
        for row in predictions:
            writer.writerow({"id": row["id"], "label": row["prediction"]})
    metrics = _metric_summary(predictions, gold)
    _json_dump(output / "metrics.json", metrics)
    _json_dump(output / "timings.json", {"cases": timings, "models": lifecycle.records,
                                          "model_load_counts": lifecycle.load_counts(),
                                          "stage_load_counts": lifecycle.stage_load_counts()})
    environment["gpu_execution_observed"] = any(
        str(record.get("device", "")).startswith("cuda") for record in lifecycle.records)
    _json_dump(output / "environment.json", environment)
    _json_dump(output / "environment" / "runtime.json", environment)
    manifest["completed_cases"] = len(predictions)
    manifest["completed"] = len(predictions) == len(records)
    manifest["model_load_counts"] = lifecycle.load_counts()
    manifest["stage_load_counts"] = lifecycle.stage_load_counts()
    component_rollup = {}
    for name in {name for state in states for name in state.component_status}:
        values = [state.component_status[name]["state"] for state in states]
        component_rollup[name] = {status: values.count(status) for status in sorted(set(values))}
    manifest["component_status_rollup"] = component_rollup
    _json_dump(output / "run_manifest.json", manifest)
    return {"manifest": manifest, "metrics": metrics, "predictions": predictions}
