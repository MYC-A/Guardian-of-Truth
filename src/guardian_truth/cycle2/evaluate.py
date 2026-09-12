"""Command line entrypoint for Cycle 2 experiments."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from guardian_truth.llm_client import ChatClient, ChatClientError, ClientConfig
from guardian_truth.runtime import REMOTE_PROVIDERS, provider_config
from guardian_truth.settings import load_env_file

from .model_gate import (
    blocked_candidate,
    build_gate_report,
    evaluate_candidate,
    load_gate_contract,
)
from .policy_arms import (
    blind_policy_cases,
    build_blocked_policy_report,
    build_policy_report,
    load_policy_arm_contract,
    run_model_policy_arms,
)
from .policy_semantics import load_policy_dataset


COMPROMISED_PROVIDERS = {"nvidia", "tokenharbor"}
DEFAULT_CONTRACT = Path("contracts/cycle2_model_gate_v2.json")
DEFAULT_OUTPUT = Path("outputs/cycle2/model_gate.json")
DEFAULT_POLICY_CASES = Path("outputs/cycle2/policy_cases.json")
DEFAULT_POLICY_OUTPUT = Path("outputs/cycle2/policy_results.json")
DEFAULT_POLICY_CONTRACT = Path("contracts/cycle2_policy_arms_v1.json")
DEFAULT_POLICY_CHECKPOINT = Path("outputs/cycle2/policy_proposals_checkpoint.json")


def _candidate(value: str) -> tuple[str, str]:
    provider, separator, model = value.partition("=")
    if not separator or provider not in {*REMOTE_PROVIDERS, "local"} or not model.strip():
        raise argparse.ArgumentTypeError("candidate must be provider=model")
    return provider, model.strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Guardian Cycle 2 evaluation")
    sub = parser.add_subparsers(dest="stage", required=True)
    gate = sub.add_parser("model-gate", help="run the predeclared provider reliability gate")
    gate.add_argument("--candidate", action="append", type=_candidate, required=True,
                      help="repeatable provider=model candidate")
    gate.add_argument("--env-file", type=Path, required=True)
    gate.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    gate.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    gate.add_argument("--rotated-provider", action="append", default=[],
                      choices=sorted(COMPROMISED_PROVIDERS),
                      help="attest that this provider credential was rotated after exposure")
    gate.add_argument("--overwrite", action="store_true")
    policy = sub.add_parser("policy", help="run policy arms only after the model gate")
    policy.add_argument("--cases", type=Path, default=DEFAULT_POLICY_CASES)
    policy.add_argument("--model-gate", type=Path, default=DEFAULT_OUTPUT)
    policy.add_argument("--output", type=Path, default=DEFAULT_POLICY_OUTPUT)
    policy.add_argument("--arm-contract", type=Path, default=DEFAULT_POLICY_CONTRACT)
    policy.add_argument("--checkpoint", type=Path, default=DEFAULT_POLICY_CHECKPOINT)
    policy.add_argument("--env-file", type=Path)
    policy.add_argument("--provider", choices=tuple(REMOTE_PROVIDERS))
    policy.add_argument("--model")
    policy.add_argument("--rotated-provider", action="append", default=[],
                        choices=sorted(COMPROMISED_PROVIDERS))
    policy.add_argument("--overwrite", action="store_true")
    return parser


def _run_model_gate(args: argparse.Namespace) -> int:
    if args.output.exists() and not args.overwrite:
        raise ValueError("refusing to overwrite an existing gate artifact")
    if not args.env_file.is_file():
        raise ValueError("explicit env file does not exist")
    contract = load_gate_contract(args.contract)
    load_env_file(args.env_file)
    results = []
    rotated = set(args.rotated_provider)
    for provider, model in args.candidate:
        credential_status = "rotated_after_exposure" if provider in rotated else "valid_unexposed"
        if provider in COMPROMISED_PROVIDERS and provider not in rotated:
            results.append(blocked_candidate(
                provider=provider,
                requested_model=model,
                credential_status="compromised_not_used",
                reason="ROTATION_ATTESTATION_REQUIRED",
            ))
            continue
        config = ClientConfig(
            timeout_seconds=contract.request.timeout_seconds,
            max_output_tokens=contract.request.max_output_tokens,
            max_retries=contract.request.max_retries,
            strict_schema=True,
            response_format_mode=contract.request.response_format_mode,
        )
        try:
            config = provider_config(config, provider, model=model)
            config = replace(
                config,
                timeout_seconds=contract.request.timeout_seconds,
                max_output_tokens=contract.request.max_output_tokens,
                max_retries=0,
                strict_schema=True,
                response_format_mode=contract.request.response_format_mode,
            )
            client = ChatClient(config)
            client.validate_configuration()
            result = evaluate_candidate(
                client,
                contract,
                provider=provider,
                requested_model=model,
                credential_status=credential_status,
            )
        except ChatClientError as error:
            result = blocked_candidate(
                provider=provider,
                requested_model=model,
                credential_status=credential_status,
                reason=error.category.upper(),
            )
        results.append(result)

    report = build_gate_report(contract, results)
    report["created_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    report["credential_values_serialized"] = False
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "policy_benchmark_permitted": report["policy_benchmark_permitted"],
        "admitted_candidates": report["admitted_candidates"],
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise ValueError(f"cannot read required artifact: {path}") from None
    if not isinstance(value, dict):
        raise ValueError(f"invalid required artifact: {path}")
    return value


def _run_policy(args: argparse.Namespace) -> int:
    if args.output.exists() and not args.overwrite:
        raise ValueError("refusing to overwrite an existing policy artifact")
    dataset = load_policy_dataset(args.cases)
    gate = _read_json(args.model_gate)
    if not gate.get("policy_benchmark_permitted"):
        report = build_blocked_policy_report(dataset, gate)
        report["created_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": report["status"], "P0": report["arms"]["P0"],
            "paired_p1_p2": report["paired_p1_p2"]["status"], "output": str(args.output),
        }, ensure_ascii=False))
        return 0

    if not args.env_file or not args.env_file.is_file() or not args.provider or not args.model:
        raise ValueError("passed gate requires --env-file, --provider, and --model")
    admitted = f"{args.provider}={args.model}"
    if admitted not in gate.get("admitted_candidates", []):
        raise ValueError("selected provider/model was not admitted by this gate")
    if args.provider in COMPROMISED_PROVIDERS and args.provider not in set(args.rotated_provider):
        raise ValueError("rotation attestation required for selected provider")
    contract = load_policy_arm_contract(args.arm_contract)
    load_env_file(args.env_file)
    config = provider_config(ClientConfig(), args.provider, model=args.model)
    config = replace(
        config, timeout_seconds=contract.timeout_seconds,
        max_output_tokens=contract.max_output_tokens, max_retries=0,
        strict_schema=True, response_format_mode=contract.response_format_mode,
    )
    client = ChatClient(config)
    client.validate_configuration()

    existing = []
    if args.checkpoint.exists():
        checkpoint = _read_json(args.checkpoint)
        if (checkpoint.get("schema_version") != "guardian-cycle2-policy-proposals-v1"
                or checkpoint.get("cases_sha256") != dataset.cases_digest
                or checkpoint.get("policy_arm_contract_sha256") != contract.digest
                or not isinstance(checkpoint.get("proposals"), list)):
            raise ValueError("checkpoint does not match the frozen benchmark/arm contract")
        existing = checkpoint["proposals"]

    def save_checkpoint(rows):
        payload = {
            "schema_version": "guardian-cycle2-policy-proposals-v1",
            "cases_sha256": dataset.cases_digest,
            "policy_arm_contract_sha256": contract.digest,
            "gold_serialized": False,
            "proposals": rows,
        }
        args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
        args.checkpoint.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        latest = rows[-1]
        print(json.dumps({
            "completed": len(rows), "total": len(dataset.cases) * 2,
            "case_id": latest["case_id"], "arm": latest["arm"],
            "transport_status": latest["transport_status"],
            "schema_status": latest["schema_status"],
        }, ensure_ascii=False), flush=True)

    proposals = run_model_policy_arms(
        client, blind_policy_cases(dataset), contract,
        existing=existing, checkpoint=save_checkpoint,
    )
    report = build_policy_report(dataset, gate, contract, proposals)
    report["created_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "arms": report["arms"],
        "paired_p1_p2": report["paired_p1_p2"]["status"],
        "output": str(args.output),
    }, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.stage == "model-gate":
            return _run_model_gate(args)
        if args.stage == "policy":
            return _run_policy(args)
    except ValueError as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    sys.exit(main())
