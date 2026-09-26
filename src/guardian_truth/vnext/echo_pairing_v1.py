"""Conservative repair of no-ID read results using reviewed entity echoes.

Only a unique pending call of the same exact tool identity and requestor can
be paired. Explicit transport IDs are never overridden. The application must
review the result field as an echo of the requested entity, not merely a field
that sometimes contains a related ID.
"""

from dataclasses import dataclass, replace
import re

from .tools import read_path
from .types import LedgerEvent, ToolIdentity


@dataclass(frozen=True)
class ReadEchoContract:
    identity: ToolIdentity
    argument_path: tuple[str, ...]
    result_paths: tuple[tuple[str, ...], ...]
    provenance: str

    def __post_init__(self):
        paths = (self.argument_path, *self.result_paths)
        if (not self.identity.provider or not self.identity.version
                or not self.identity.schema_sha256 or len(self.identity.schema_sha256) != 64
                or not self.provenance or not self.result_paths
                or any(not path or any(not isinstance(part, str) or not part for part in path)
                       for path in paths)):
            raise ValueError("version-bound reviewed read echo fields required")


@dataclass(frozen=True)
class EchoPairingResult:
    events: tuple[LedgerEvent, ...]
    rebound_result_ids: tuple[str, ...]


_EXPLICIT_TRANSPORT = re.compile(r'\b(?:call_id|request_id)="[^"\n]+"')


def _has_explicit_transport(event: LedgerEvent) -> bool:
    header = event.raw_text.split("⟧", 1)[0] if "⟧" in event.raw_text else ""
    return bool(_EXPLICIT_TRANSPORT.search(header))


def _echo_value(result: LedgerEvent, contract: ReadEchoContract):
    values = []
    for path in contract.result_paths:
        value, present = read_path(result.payload, path)
        if not present or type(value) not in {str, int}:
            return None
        values.append(value)
    if any(type(value) is not type(values[0]) or value != values[0]
           for value in values[1:]):
        return None
    return values[0]


def pair_read_echoes(events: tuple[LedgerEvent, ...],
                     contracts: tuple[ReadEchoContract, ...]) -> EchoPairingResult:
    if len({contract.identity for contract in contracts}) != len(contracts):
        raise ValueError("unique reviewed read identity required")
    by_identity = {contract.identity: contract for contract in contracts}
    prior_calls = {}
    consumed = set()
    output, rebound = [], []
    for event in events:
        if event.kind == "call" and event.call_id:
            prior_calls[event.call_id] = event
        elif event.kind == "result":
            if event.call_id and not event.pairing_issue:
                consumed.add(event.call_id)
            elif (event.pairing_issue == "AMBIGUOUS_CALL_IDENTITY"
                  and event.call_candidates and not _has_explicit_transport(event)
                  and event.actor == "tool" and event.source.document == "prompt"):
                contract = by_identity.get(event.tool)
                if contract is not None and event.payload_json is not None:
                    echoed = _echo_value(event, contract)
                    if echoed is not None:
                        matches = []
                        for call_id in event.call_candidates:
                            call = prior_calls.get(call_id)
                            if (call_id in consumed or call is None or call.index >= event.index
                                    or call.kind != "call" or call.actor != event.requestor
                                    or call.tool != event.tool or call.payload_json is None):
                                continue
                            requested, present = read_path(call.payload, contract.argument_path)
                            if present and type(requested) is type(echoed) and requested == echoed:
                                matches.append(call_id)
                        if len(matches) == 1:
                            event = replace(event, call_id=matches[0],
                                            call_candidates=(matches[0],), pairing_issue=None)
                            consumed.add(matches[0])
                            rebound.append(event.event_id)
        output.append(event)
    return EchoPairingResult(tuple(output), tuple(rebound))
