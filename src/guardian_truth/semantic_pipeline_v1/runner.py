"""One implementation behind both the Python API and CLI."""

from __future__ import annotations

from dataclasses import dataclass, replace
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import time

from guardian_truth.vnext.e2e.backend_v1 import E2ECachingBackend
from guardian_truth.vnext.e2e.competition_adapter_v1 import adapt_competition_input
from guardian_truth.vnext.e2e.json_extract_backend_v1 import JsonExtractBackend
from guardian_truth.vnext.adapters import AdapterMode
from guardian_truth.vnext.e2e.e2e_types_v1 import E2EArmConfig, SEMANTICS_ARMS
from guardian_truth.settings import load_env_file

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
from .types import NLIEvidence, RuleCandidate, SemanticInterpretationSet, to_wire


@dataclass(frozen=True)
class InferenceRecord:
    case_id: str
    prompt: str
    response: str


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
                raw = row["label"]
                if isinstance(raw, str):
                    raw = int(raw)
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
             "gpu_execution_claimed": False}
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


def _fragment_neighbors(timeline, segment_id: str, window: int) -> tuple[str, ...]:
    ordered = sorted(timeline.segments, key=lambda segment: segment.event_index)
    index = next((i for i, segment in enumerate(ordered) if segment.segment_id == segment_id), None)
    if index is None:
        return ()
    return tuple(ordered[i].exact_text for i in range(max(0, index - window),
                                                       min(len(ordered), index + window + 1))
                 if i != index)


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


def _write_case_artifacts(case_dir: Path, *, timeline, retrieval, by_extractor,
                          gliner, langextract, nli_rows, candidates, phi, core, summary: str) -> None:
    _json_dump(case_dir / "source_segments.json", to_wire(timeline))
    _json_dump(case_dir / "retrieved_fragments.json", to_wire(retrieval))
    _json_dump(case_dir / "mistral.json", [to_wire(item) for item in by_extractor.get("mistral", ())])
    _json_dump(case_dir / "nuextract.json", [to_wire(item) for item in by_extractor.get("nuextract", ())])
    if gliner is not None:
        _json_dump(case_dir / "gliner_evidence.json", gliner)
    if langextract is not None:
        _json_dump(case_dir / "langextract_alignment.json", langextract)
    _json_dump(case_dir / "nli_checks.json", nli_rows)
    _json_dump(case_dir / "binding_candidates.json", [to_wire(item) for item in candidates])
    _json_dump(case_dir / "phi.json", to_wire(phi))
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
        metrics["post_inference_evaluation"] = {"TP": tp, "FP": fp, "FN": fn, "TN": tn,
            "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0}
    return metrics


def run_experiment(*, input_dir=None, input_file=None, output_dir,
                   config: SemanticPipelineConfig | None = None, resume: bool = True,
                   case_id: str | None = None, limit: int | None = None,
                   dry_run: bool = False) -> dict:
    """Run V1. Labels are retained outside this function's inference objects."""
    load_env_file()
    if config is None:
        configured_model = (os.environ.get("MISTRAL_MODEL")
                            or os.environ.get("mistral_model")
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
    manifest = {"schema_version": config.schema_version, "ablation": config.ablation,
                "semantic_frontend": "current" if config.use_current_frontend else "v1",
                "dry_run": dry_run, "resume": resume, "case_count": len(records),
                "input_ids_sha256": hashlib.sha256(canonical_json(
                    [record.case_id for record in records]).encode()).hexdigest(),
                "labels_crossed_inference_firewall": False,
                "cache_dir": str(cache_path)}
    _json_dump(output / "run_manifest.json", manifest)

    mistral = None
    if (config.use_mistral or config.use_current_frontend) and not dry_run:
        mistral = MistralRuleExtractor(model=config.mistral_model,
            api_key_env=config.mistral_api_key_env,
            max_output_tokens=config.mistral_max_output_tokens,
            timeout_seconds=config.mistral_timeout_seconds, cache=cache)
        mistral.client.validate_configuration()
    predictions, timings = [], []
    for position, record in enumerate(records, 1):
        started = time.monotonic()
        safe_id = _safe_case_id(record.case_id)
        case_dir = output / "cases" / safe_id
        done_path = case_dir / "complete.json"
        case_run_key = content_key(stage="completed_case", model="semantic-pipeline-v1",
            config={**config.as_dict(), "dry_run": dry_run},
            payload={"prompt": record.prompt, "response": record.response})
        if resume and done_path.is_file():
            previous = json.loads(done_path.read_text(encoding="utf-8"))
            if previous.get("case_run_key") == case_run_key:
                predictions.append(previous["prediction_row"])
                timings.append(previous["timing"])
                continue
        timeline = build_source_timeline(record.prompt, record.response)
        verify_timeline(timeline, record.prompt, record.response)
        query = record.response + "\n" + " ".join(
            segment.exact_text for segment in timeline.segments if segment.source_type == "USER")

        retrieval_key = content_key(stage="embedding_retrieval", model=config.embedding_model,
            config={"top_k": config.retrieval_top_k, "neighbor_window": config.neighbor_window,
                    "max_fragment_chars": config.max_fragment_chars,
                    "retrieval_engine": "lexical" if dry_run or config.use_current_frontend else "bge-m3"},
            payload={"timeline": to_wire(timeline), "query": query})
        # Retrieval output is cached as a full auditable stage artifact. A cache
        # hit can skip BGE loading, but reconstruction stays deterministic.
        cached_retrieval = cache.get("embedding_retrieval", retrieval_key)
        if cached_retrieval is not None:
            from .types import RetrievedFragment, RetrievalResult
            retrieval = RetrievalResult(
                tuple(RetrievedFragment(**item) for item in cached_retrieval["fragments"]),
                tuple(cached_retrieval["routed_segment_ids"]),
                tuple(cached_retrieval["unrouted_segment_ids"]),
                tuple(cached_retrieval["source_coverage"]))
        elif dry_run or config.use_current_frontend:
            retrieval = retrieve_fragments(timeline, query=query, top_k=config.retrieval_top_k,
                neighbor_window=config.neighbor_window, max_fragment_chars=config.max_fragment_chars)
            cache.put("embedding_retrieval", retrieval_key, to_wire(retrieval))
        else:
            from .models.embeddings import BGEEmbedder
            with lifecycle.loaded(stage="embedding_retrieval", model_name=config.embedding_model,
                                  loader=lambda device: BGEEmbedder.load(config.embedding_model, device)) as (model, _):
                retrieval = retrieve_fragments(timeline, query=query, top_k=config.retrieval_top_k,
                    neighbor_window=config.neighbor_window, max_fragment_chars=config.max_fragment_chars,
                    embedder=BGEEmbedder(config.embedding_model, model, cache=cache))
            cache.put("embedding_retrieval", retrieval_key, to_wire(retrieval))

        segment_by_id = {segment.segment_id: segment for segment in timeline.segments}
        by_extractor = {"mistral": [], "nuextract": []}
        if config.use_mistral and not dry_run:
            for fragment in retrieval.fragments:
                by_extractor["mistral"].extend(mistral.extract(
                    segment_id=fragment.segment_id, source_text=fragment.exact_text,
                    context=_fragment_neighbors(timeline, fragment.segment_id, config.neighbor_window)))
        if config.use_nuextract and not dry_run:
            from .models.nuextract import NuExtractRuleExtractor
            with lifecycle.loaded(stage="nuextract", model_name=config.nuextract_model,
                    loader=lambda device: NuExtractRuleExtractor.load(config.nuextract_model, device)) as (loaded, _):
                model, tokenizer = loaded
                extractor = NuExtractRuleExtractor(model_name=config.nuextract_model, model=model,
                                                    tokenizer=tokenizer, cache=cache)
                for fragment in retrieval.fragments:
                    by_extractor["nuextract"].extend(extractor.extract(
                        segment_id=fragment.segment_id, source_text=fragment.exact_text,
                        context=_fragment_neighbors(timeline, fragment.segment_id, config.neighbor_window)))
        candidates = [*by_extractor["mistral"], *by_extractor["nuextract"]]

        gliner_rows = None
        if config.enable_gliner and not dry_run:
            from .models.gliner_optional import GLiNEREvidenceExtractor
            gliner_rows = []
            with lifecycle.loaded(stage="gliner", model_name=config.gliner_model,
                    loader=lambda device: GLiNEREvidenceExtractor.load(config.gliner_model, device)) as (model, _):
                extractor = GLiNEREvidenceExtractor(config.gliner_model, model)
                for fragment in retrieval.fragments:
                    key = content_key(stage="gliner", model=config.gliner_model,
                                      config={"labels": list(extractor.LABELS)},
                                      payload={"text": fragment.exact_text})
                    evidence = cache.get("gliner", key)
                    if evidence is None:
                        evidence = extractor.extract(fragment.exact_text)
                        cache.put("gliner", key, evidence)
                    gliner_rows.append({"segment_id": fragment.segment_id, "evidence": evidence})

        nli_rows = []
        if config.use_nli and candidates and not dry_run:
            from .models.nli import NLIFirewall
            with lifecycle.loaded(stage="nli", model_name=config.nli_model,
                                  loader=lambda device: NLIFirewall.load(config.nli_model, device)) as (model, _):
                firewall = NLIFirewall(config.nli_model, model)
                checked = []
                for candidate in candidates:
                    rendering = render_rule(candidate.rule)
                    premise = "\n".join(span.quote for span in candidate.source_spans) or \
                              segment_by_id[candidate.source_segment_ids[0]].exact_text
                    key = content_key(stage="nli", model=config.nli_model, config={},
                                      payload={"premise": premise, "hypothesis": rendering})
                    raw = cache.get("nli", key)
                    if raw is None:
                        evidence = firewall.check(premise, rendering)
                        raw = to_wire(evidence); cache.put("nli", key, raw)
                    else:
                        evidence = NLIEvidence(raw["label"], raw["scores"], tuple(raw["logits"]),
                                               raw["model"], raw["rendering"])
                    nli_rows.append({"candidate_id": candidate.candidate_id, **raw})
                    checked.append(replace(candidate, nli_evidence=(*candidate.nli_evidence, evidence)))
                candidates = checked

        tool_catalog = ()
        try:
            adapted = adapt_competition_input({"id": record.case_id, "prompt": record.prompt,
                                               "response": record.response})
            tool_catalog = adapted.case.tool_schemas
        except ValueError:
            adapted = None
        if config.use_binding and candidates and tool_catalog and not dry_run:
            entity_candidates = tuple(dict.fromkeys(re.findall(
                r'\b[A-Za-z][A-Za-z0-9_-]*\d+[A-Za-z0-9_-]*\b', record.prompt)))
            from .models.embeddings import BGEEmbedder
            with lifecycle.loaded(stage="binding_embedding", model_name=config.embedding_model,
                                  loader=lambda device: BGEEmbedder.load(config.embedding_model, device)) as (model, _):
                embedder = BGEEmbedder(config.embedding_model, model, cache=cache)
                candidates = [bind_candidate(item, tool_catalog, entity_candidates=entity_candidates,
                                              embedder=embedder,
                                              top_k=config.binding_top_k) for item in candidates]
            from .models.reranker import BGEReranker
            with lifecycle.loaded(stage="binding_rerank", model_name=config.reranker_model,
                                  loader=lambda device: BGEReranker.load(config.reranker_model, device)) as (model, _):
                reranker = BGEReranker(config.reranker_model, model, cache=cache)
                candidates = [rerank_candidate(item, tool_catalog, reranker=reranker)
                              for item in candidates]

        phi = build_phi(candidates, retrieval.source_coverage,
                        contradiction_threshold=config.nli_contradiction_threshold)
        langextract_rows = None
        if config.enable_langextract and not dry_run:
            # Alignment is deliberately downstream of independent extraction
            # and cannot create/delete meanings in V1.
            from .models.langextract_optional import LangExtractAligner
            aligned = LangExtractAligner().align(record.prompt, [to_wire(item) for item in candidates])
            langextract_rows = {"mode": "span-alignment-only", "added_fragments": 0,
                                "changed_semantics": False, "aligned_candidates": aligned}

        if dry_run:
            core_result = {"status": "UNRESOLVED", "prediction": 0,
                           "certificate_valid": None, "reason": "DRY_RUN_NO_MODELS"}
        elif adapted is None:
            core_result = {"status": "UNRESOLVED", "prediction": 0,
                           "certificate_valid": None,
                           "reason": "INPUT_NOT_COMPATIBLE_WITH_EXISTING_CORE_ADAPTER"}
        elif config.use_current_frontend:
            core_cache_tag = hashlib.sha256(canonical_json({
                "model": config.mistral_model,
                "max_output_tokens": config.mistral_max_output_tokens,
                "frontend": "current-B4h"}).encode()).hexdigest()[:16]
            backend = E2ECachingBackend(JsonExtractBackend(mistral.client, interval_seconds=0),
                                        cache_path=cache_path / f"current_core__{core_cache_tag}.json")
            from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1
            guardian = GuardianE2EV1(
                backend, arm=E2EArmConfig("B4h", ("h0_hist",), ("conservative",)),
                adapter_mode=AdapterMode.COMPETITION, semantics=SEMANTICS_ARMS["B3"])
            core_result = _core_summary(guardian.analyze_e2e_v1(adapted.case))
        else:
            core_cache_tag = hashlib.sha256(canonical_json({
                "model": config.mistral_model,
                "max_output_tokens": config.mistral_max_output_tokens,
                "frontend": "semantic-v1"}).encode()).hexdigest()[:16]
            backend = E2ECachingBackend(JsonExtractBackend(mistral.client, interval_seconds=0),
                                        cache_path=cache_path / f"v1_core__{core_cache_tag}.json")
            system_ids = {segment.segment_id for segment in timeline.segments
                          if segment.source_type == "SYSTEM"}
            knowledge_ids = {fragment.segment_id for fragment in retrieval.fragments
                             if "knowledge-result-guarantee" in fragment.reasons}
            normative_knowledge_ids = {candidate.source_segment_ids[0] for candidate in phi.interpretations
                                       if candidate.rule.modality != "UNKNOWN"
                                       and candidate.source_segment_ids
                                       and candidate.source_segment_ids[0] in knowledge_ids}
            policy_ids = frozenset(system_ids | normative_knowledge_ids)
            knowledge_texts = tuple(segment_by_id[segment_id].exact_text
                                    for segment_id in sorted(normative_knowledge_ids))
            analysis, bridge_unresolved = run_existing_core(
                adapted.case, phi, backend=backend, policy_segment_ids=policy_ids,
                additional_normative_texts=knowledge_texts,
                arm=E2EArmConfig("B4h", ("h0_hist",), ("conservative",)),
                adapter_mode=AdapterMode.COMPETITION, semantics=SEMANTICS_ARMS["B3"])
            core_result = {**_core_summary(analysis), "bridge_unresolved": list(bridge_unresolved)}

        digests_by_extractor = {name: {item.canonical_digest for item in values}
                                for name, values in by_extractor.items()}
        agreements = len(digests_by_extractor["mistral"] & digests_by_extractor["nuextract"])
        disagreements = len(digests_by_extractor["mistral"] ^ digests_by_extractor["nuextract"])
        labels = [row["label"] for row in nli_rows]
        prediction_row = {"id": record.case_id, "prediction": core_result["prediction"],
                          "core_status": core_result["status"],
                          "source_segments": len(timeline.segments),
                          "retrieved_fragments": len(retrieval.fragments),
                          "mistral_candidates": len(by_extractor["mistral"]),
                          "nuextract_candidates": len(by_extractor["nuextract"]),
                          "extractor_agreements": agreements, "extractor_disagreements": disagreements,
                          "nli_contradictions": labels.count("CONTRADICTION"),
                          "nli_neutral": labels.count("NEUTRAL"),
                          "nli_entailment": labels.count("ENTAILMENT"), "phi_size": len(phi.interpretations),
                          "unresolved_bindings": sum(any(value.startswith("ambiguous-")
                              for value in item.unresolved_components) for item in candidates)}
        elapsed = round(time.monotonic() - started, 6)
        timing = {"id": record.case_id, "total_duration_s": elapsed}
        summary = (f"case_id: {record.case_id}\ncore_status: {core_result['status']}\n"
                   f"prediction: {core_result['prediction']}\nphi_size: {len(phi.interpretations)}\n"
                   f"unresolved: {len(phi.unresolved)}\n")
        _write_case_artifacts(case_dir, timeline=timeline, retrieval=retrieval,
            by_extractor=by_extractor, gliner=gliner_rows, langextract=langextract_rows,
            nli_rows=nli_rows,
            candidates=candidates, phi=phi, core=core_result, summary=summary)
        if case_id is not None:
            trace_dir = output / "traces" / safe_id
            _write_case_artifacts(trace_dir, timeline=timeline, retrieval=retrieval,
                by_extractor=by_extractor, gliner=gliner_rows, langextract=langextract_rows,
                nli_rows=nli_rows,
                candidates=candidates, phi=phi, core=core_result, summary=summary)
        completion = {"case_id": record.case_id, "case_run_key": case_run_key,
                      "prediction_row": prediction_row, "timing": timing}
        _json_dump(done_path, completion)
        predictions.append(prediction_row); timings.append(timing)
        print(f"semantic-v1 {position}/{len(records)} {record.case_id} {core_result['status']}", flush=True)

    with (output / "predictions.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", "label"], lineterminator="\n")
        writer.writeheader()
        for row in predictions:
            writer.writerow({"id": row["id"], "label": row["prediction"]})
    metrics = _metric_summary(predictions, gold)
    _json_dump(output / "metrics.json", metrics)
    _json_dump(output / "timings.json", {"cases": timings, "models": lifecycle.records})
    manifest["completed_cases"] = len(predictions)
    manifest["completed"] = len(predictions) == len(records)
    _json_dump(output / "run_manifest.json", manifest)
    return {"manifest": manifest, "metrics": metrics, "predictions": predictions}
