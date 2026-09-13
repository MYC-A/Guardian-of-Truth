"""Read-only, gold-free audit of sealed Goal-only physical request receipts.

Separate from the frozen scorer/calculus. No model calls, repairs, verdict
changes or artifact writes. Only sealed stages may be audited.
"""

import argparse
import json
from pathlib import Path

from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, verify_files, write_new


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/vnext"


def audit_receipts_v2(output, root, stage):
    def path(name):
        return output / ("goal_v3_isolation_v2_" + name + ".json")

    def read(name):
        return json.loads(path(name).read_text(encoding="utf-8"))

    frozen = read("inference_freeze")
    if (verify_files(root, frozen["source_sha256"])
            or file_digest(path("inputs")) != frozen["inputs_sha256"]):
        raise ValueError("frozen source/input integrity failed")
    rows, seal, boundary = read(stage + "_predictions"), read(stage + "_prediction_seal"), read(stage + "_boundary")
    ids = [row["case_id"] for row in rows]
    if not ids or ids != frozen["stages"][stage][:len(ids)]:
        raise ValueError("sealed stage is not the exact requested prefix")
    if seal != prediction_seal(rows, ids, architecture_commit=frozen["architecture_commit"],
                              configuration_sha256=digest(frozen)):
        raise ValueError("prediction seal mismatch")
    if (boundary["prediction_sha256"] != digest(rows) or boundary["seal_sha256"] != digest(seal)
            or boundary["attempted_case_ids"] != ids):
        raise ValueError("boundary lineage mismatch")
    sources = {row["case_id"]: row["source"] for row in read("inputs")}
    artifacts, usage, deliveries, retries, abandoned, output_exceeds_setting = {}, [], 0, 0, 0, []
    for row in rows:
        cid, source = row["case_id"], sources[row["case_id"]]
        if any(key in source for key in ("policy", "gold", "reference")):
            raise ValueError("not Goal-only source")
        if row["source_sha256"] != digest(source):
            raise ValueError("case source changed")
        count = row["physical_requests"]
        if type(count) is not int or count not in {1, 2} or len(row["request_telemetry"]) != count:
            raise ValueError("invalid physical request count")
        stem = "case_" + cid.replace(":", "_").lower()
        if digest(read(stem)) != digest(row):
            raise ValueError("case/prediction mismatch")
        first, prior = None, None
        telemetry = []
        for ordinal in range(count):
            name = stem + f"_request_{ordinal:03d}"
            request, result = read(name), read(name + "_result")
            if (request["case_id"] != cid or request["ordinal"] != ordinal
                    or request["source_sha256"] != digest(source)
                    or request["configuration_sha256"] != digest(frozen)
                    or result["request_sha256"] != digest(request)
                    or request["payload_sha256"] != digest({"messages": request["messages"],
                        "configuration": frozen["configuration"]})):
                raise ValueError("physical request/result lineage mismatch")
            messages = request["messages"]
            if (len(messages) != 2 or messages[0]["role"] != "system" or messages[1]["role"] != "user"
                    or json.loads(messages[1]["content"]) != {"source": source}
                    or digest({"version": frozen["frontend_version"], "system": messages[0]["content"]})
                        != frozen["prompt_sha256"]):
                raise ValueError("request prompt/source differs from freeze")
            if ordinal:
                if (request["payload_sha256"] != first["payload_sha256"]
                        or messages != first["messages"] or prior["transport_status"] == "SUCCESS"
                        or prior["retryable"] is not True
                        or prior["error_category"] not in frozen["configuration"]["retry_categories"]):
                    raise ValueError("semantic or changed-payload retry")
                retries += 1
            first = first or request
            prior = result["telemetry"]
            telemetry.append(prior)
            usage.append(prior["usage"])
            deliveries += prior["transport_status"] == "SUCCESS"
            abandoned += prior.get("remote_outcome") == "UNKNOWN_NO_AUTOMATIC_RETRY"
            if prior["usage"].get("completion_tokens", 0) > frozen["configuration"]["max_output_tokens"]:
                output_exceeds_setting.append({"case_id": cid, "ordinal": ordinal})
            for item in (name, name + "_result"):
                artifacts[path(item).name] = file_digest(path(item))
        if telemetry != row["request_telemetry"] or prior != row["telemetry"] or result["proposal"] != row["proposal"]:
            raise ValueError("case differs from physical capture")
    complete_usage = all(all(type(item.get(key)) is int and item[key] >= 0
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")) for item in usage)
    return {"schema_version": "guardian-goal-v3-v2-independent-physical-audit-v1", "stage": stage,
        "architecture_commit": frozen["architecture_commit"], "inference_freeze_sha256": file_digest(path("inference_freeze")),
        "prediction_seal_sha256": file_digest(path(stage + "_prediction_seal")),
        "gold_opened": False, "model_calls": 0, "sealed_cases": len(ids),
        "physical_requests": len(usage), "transport_retries": retries, "successful_deliveries": deliveries,
        "abandoned_unknown_captures": abandoned, "usage_complete": complete_usage,
        "reported_usage": {key: sum(item.get(key, 0) for item in usage)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")},
        "reported_output_exceeds_request_setting": output_exceeds_setting,
        "physical_artifact_sha256": artifacts}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("S1", "S2", "S3"), required=True)
    parser.add_argument("--save", action="store_true", help="save a new immutable audit receipt")
    args = parser.parse_args()
    report = audit_receipts_v2(OUT, ROOT, args.stage)
    if args.save:
        write_new(OUT / ("goal_v3_isolation_v2_" + args.stage + "_independent_receipt_audit.json"), report)
    print(json.dumps({key: value for key, value in report.items() if key != "physical_artifact_sha256"}, ensure_ascii=False))
