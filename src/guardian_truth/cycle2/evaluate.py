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


COMPROMISED_PROVIDERS = {"nvidia", "tokenharbor"}
DEFAULT_CONTRACT = Path("contracts/cycle2_model_gate_v1.json")
DEFAULT_OUTPUT = Path("outputs/cycle2/model_gate.json")


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
        )
        try:
            config = provider_config(config, provider, model=model)
            config = replace(
                config,
                timeout_seconds=contract.request.timeout_seconds,
                max_output_tokens=contract.request.max_output_tokens,
                max_retries=0,
                strict_schema=True,
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


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.stage == "model-gate":
            return _run_model_gate(args)
    except ValueError as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    sys.exit(main())
