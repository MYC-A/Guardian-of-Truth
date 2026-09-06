"""Bounded diagnostic state, never an additional source of truth or a score.

Only observed categories get actions: missing source -> local reading, rejected
output -> recheck the SAME evidence. Other uncertainty is retained but not routed.
"""

from dataclasses import asdict, dataclass, field


@dataclass
class Uncertainty:
    claim: str
    kind: str
    reason: str
    need: str
    known_evidence: list[str] = field(default_factory=list)
    attempted_actions: list[dict] = field(default_factory=list)
    request: dict | None = None


def short(value, limit=600):
    return value[:limit] if isinstance(value, str) else ''


def valid_ids(value, reader, *, direct=False):
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(key for key in value[:32] if isinstance(key, str)
                and ((direct and key == 'prompt') or reader.citation(key) is not None)))


def claim_memory(output, reader, *, direct=False):
    """Retain model judgments as revisable hypotheses; filter unread citations."""
    claims = output.get('claims', [])
    if not isinstance(claims, list):
        return []
    memory = []
    for claim in claims[:12]:
        if not isinstance(claim, dict) or not short(claim.get('text')):
            continue
        reported = claim.get('verdict')
        if reported not in ('supported', 'contradicted', 'unknown'):
            reported = 'unknown'
        ids = valid_ids(claim.get('evidence_ids'), reader, direct=direct)
        # Valid references do not establish entailment. No mechanical promotion.
        grounded = any(key != 'response' for key in ids)
        memory.append({'claim':short(claim['text'], 300), 'reported_verdict':reported,
                       'state':reported if grounded else 'unknown',
                       'reason':short(claim.get('reason'), 400), 'evidence_ids':ids,
                       'authority':'revisable_model_hypothesis'})
    return memory


def refresh_memory(memory, reader, *, direct=False):
    """Eviction removes current support, but does not erase the previous judgment."""
    result = []
    for claim in memory:
        item = dict(claim)
        current = valid_ids(item['evidence_ids'], reader, direct=direct)
        item['unavailable_evidence_ids'] = [key for key in item['evidence_ids'] if key not in current]
        item['current_evidence_ids'] = current
        if item['unavailable_evidence_ids']:
            item['state'] = 'unknown'
        result.append(item)
    return result


def safe_request(value):
    """Small allowlist; model text cannot become code, a URL or a remote action."""
    if not isinstance(value, dict):
        return None
    action = value.get('action')
    if action in ('read', 'graph'):
        key = 'ids' if action == 'read' else 'fact_ids'
        ids = value.get(key)
        if isinstance(ids, list):
            ids = [x[:80] for x in ids[:8] if isinstance(x, str)]
            return {'action':action, key:ids} if ids else None
    if action == 'search' and short(value.get('query'), 300).strip():
        return {'action':'search', 'query':short(value['query'], 300)}
    if action == 'entity' and short(value.get('field'), 100).strip():
        entity = value.get('value')
        if type(entity) in (str, int):
            return {'action':'entity', 'field':short(value['field'], 100),
                    'value':short(entity, 300) if isinstance(entity, str) else entity}
    return None


def diagnose(output, result, reader, *, direct=False):
    """Keep explicit uncertainty and technical rejection separate.

    Missing/invalid references alone NEVER imply missing world evidence. The
    model's semantic reason is recorded as a hypothesis, not silently inferred.
    """
    items = []
    claims = output.get('claims', [])
    if isinstance(claims, list):
        for claim in claims[:12]:
            if not isinstance(claim, dict) or claim.get('verdict') != 'unknown':
                continue
            detail = claim.get('uncertainty', {})
            detail = detail if isinstance(detail, dict) else {}
            kind = detail.get('kind')
            kind = kind if kind == 'MISSING_EVIDENCE' else 'OTHER'
            need = short(detail.get('need'))
            request = safe_request(detail.get('request')) if kind == 'MISSING_EVIDENCE' else None
            if kind == 'MISSING_EVIDENCE' and need.strip() and request is None:
                request = {'action':'search', 'query':need[:300]}
            items.append(Uncertainty(short(claim.get('text')), kind,
                         short(claim.get('reason')), need,
                         valid_ids(claim.get('evidence_ids'), reader, direct=direct),
                         request=request))
    semantic_unknown = {'language_assessment_unknown', 'language_claims_unknown'}
    rejected = [issue for issue in result.unresolved if issue not in semantic_unknown]
    if rejected:
        items.insert(0, Uncertainty('Candidate assessment output', 'INVALID_OUTPUT',
                     ', '.join(rejected),
                     'Recheck consistency and use only current prompt evidence IDs; missing evidence is not false.',
                     valid_ids(output.get('evidence_ids'), reader, direct=direct)))
    if not items and output.get('verdict') == 'unknown':
        items.append(Uncertainty('Candidate assessment', 'OTHER', short(output.get('reason')),
                                 '', valid_ids(output.get('evidence_ids'), reader, direct=direct)))
    return items


def recovery_action(items):
    # Repair rejection first; do not invent a retrieval need from invalid syntax.
    for item in items:
        if item.kind == 'INVALID_OUTPUT':
            return item, {'action':'recheck_same_evidence'}
    for item in items:
        if item.kind == 'MISSING_EVIDENCE' and item.need.strip() and item.request:
            return item, item.request
    return None, None


def snapshots(items):
    return [asdict(item) for item in items]
