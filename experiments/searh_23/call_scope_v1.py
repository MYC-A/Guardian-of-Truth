"""Conservative action-scope check for explicit policy clauses.

This is a diagnostic correction to model-proposed BROKEN checks, not a proof
that every policy clause was considered. UNKNOWN preserves the model check.
The target action comes from the declared tool's source description.
"""

from __future__ import annotations

import re


_FIELD = re.compile(r"^\s*([A-Za-z_][A-Za-z_0-9]*):\s*"
                    r"(string|integer|number|boolean|array|object)(!?)"
                    r"(?=\s|$)", re.M)


def malformed_call(item: dict) -> list[str]:
    """Check declared required fields before considering model policy claims."""
    target = item["target"]
    source = item["tools"].get(target["tool"])
    if not source or not target["json_valid"] or not isinstance(target["arguments"], dict):
        return ["unknown_tool_or_invalid_json"]
    arguments = target["arguments"]
    errors = []
    for name, kind, required in _FIELD.findall(source):
        if required and name not in arguments:
            errors.append("missing:" + name)
            continue
        if name not in arguments:
            continue
        value = arguments[name]
        valid = {"string": lambda v: isinstance(v, str),
                 "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
                 "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
                 "boolean": lambda v: isinstance(v, bool),
                 "array": lambda v: isinstance(v, list),
                 "object": lambda v: isinstance(v, dict)}[kind](value)
        if not valid:
            errors.append("type:" + name)
    return errors


def _quote_in_policy(policy: str, quote: str) -> bool:
    words = quote.split()
    if len(words) < 4:
        return False
    return len(list(re.finditer(r"\s+".join(map(re.escape, words)), policy))) == 1


def _tool_description(source: str) -> str:
    line = source.splitlines()[0] if source.splitlines() else ""
    return line.split("—", 1)[1].strip().lower() if "—" in line else ""


def _target_family(item: dict) -> str | None:
    name = item["target"]["tool"]
    description = _tool_description(item["tools"].get(name, ""))
    if not description:
        return None
    head = description.split()[0]
    if head in {"read", "look", "lookup", "get", "find", "check", "compare", "verify", "search"}:
        return "READ"
    if head in {"record", "log", "write"}:
        return "AUDIT"
    if head in {"replace", "swap", "exchange"}:
        return "REPLACE"
    if head == "refund" or head == "process" and re.search(r"\brefund\b", description):
        return "REFUND"
    if head in {"modify", "change", "update"}:
        return "MODIFY"
    if head == "cancel":
        return "CANCEL"
    if head in {"transfer", "escalate"}:
        return "TRANSFER"
    return None


def explicitly_out_of_scope(policy_quote: str, item: dict) -> bool:
    if not _quote_in_policy(item["policy"], policy_quote):
        return False
    family = _target_family(item)
    if family is None:
        return False
    quote = " ".join(policy_quote.lower().split())
    # These source clauses explicitly name the governed action. A lookup used
    # to satisfy a precondition is not the action gated by that precondition.
    if re.search(r"\bbefore executing a device replacement or fee refund\b", quote):
        return family not in {"REPLACE", "REFUND"}
    if re.search(r"\ba device replacement costing over\b", quote):
        return family != "REPLACE"
    if re.search(r"\ba replacement may be executed only when\b", quote):
        return family != "REPLACE"
    if re.search(r"\bwhen stock is available and the identity, confirmation\b", quote):
        return family != "TRANSFER"
    if re.search(r"\bafter a replacement completes successfully, record an audit\b", quote):
        return family != "AUDIT"
    if re.search(r"\bbefore modifying or cancelling any reservation\b", quote):
        return family not in {"MODIFY", "CANCEL"}
    if re.search(r"\brefunds over \$\d+ require supervisor approval\b", quote):
        return family != "REFUND"
    if re.search(r"\bnever state that a replacement, refund, or audit completed\b", quote):
        return True  # The target is a tool call, not an assistant text claim.
    return False


def scoped_verdict(answer: dict, item: dict) -> dict:
    shape_errors = malformed_call(item)
    raw = answer.get("verdict")
    checks = answer.get("checks")
    if shape_errors:
        return {"verdict": "VIOLATION", "discarded": [], "retained_broken": [],
                "structural_errors": shape_errors}
    if raw != "VIOLATION" or not isinstance(checks, list):
        return {"verdict": raw, "discarded": [], "retained_broken": [],
                "structural_errors": []}
    discarded, retained = [], []
    for index, check in enumerate(checks):
        if not isinstance(check, dict) or check.get("status") != "BROKEN":
            continue
        if explicitly_out_of_scope(str(check.get("policy_quote", "")), item):
            discarded.append(index)
        else:
            retained.append(index)
    # Removing an invalid accusation does not prove that every applicable
    # policy clause was checked. Preserve the uncertainty for binary fallback.
    return {"verdict": "VIOLATION" if retained else "UNKNOWN" if discarded else raw,
            "discarded": discarded, "retained_broken": retained,
            "structural_errors": []}
