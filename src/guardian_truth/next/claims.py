"""Blind claim extraction: this module accepts the candidate response only."""

from __future__ import annotations

import re

from guardian_truth.parsing import parse_events

from .records import Claim, ClaimCoverageItem, ClaimExtraction, ClaimKind, Span


_SENTENCE = re.compile(r"[^\n.!?]+(?:[.!?]+|$)")
_COMPLETED_RU = re.compile(
    r"\b(?:я\s+)?(?:уже\s+)?(?P<verb>отменил(?:а)?|изменил(?:а)?|вернул(?:а)?|"
    r"забронировал(?:а)?|перевел(?:а)?|оплатил(?:а)?|подключил(?:а)?|отключил(?:а)?|"
    r"возобновил(?:а)?|сбросил(?:а)?|обновил(?:а)?)\b",
    re.IGNORECASE,
)
_COMPLETED_EN = re.compile(
    r"\bI(?:'ve| have)?\s+(?P<verb>cancelled|canceled|changed|refunded|booked|"
    r"transferred|paid|enabled|disabled|resumed|reset|updated)\b",
    re.IGNORECASE,
)
_INTENT = re.compile(
    r"\b(?:я\s+(?:могу|попробую|собираюсь|буду)|могу\s+предложить|"
    r"I\s+(?:can|will|could|plan to))\b",
    re.IGNORECASE,
)
_REFUSAL = re.compile(
    r"\b(?:не\s+могу|невозможно|нет\s+(?:возможности|способа)|"
    r"I\s+(?:cannot|can't|am unable)|no\s+way)\b",
    re.IGNORECASE,
)
_ABSENCE = re.compile(
    r"\b(?:не\s+(?:наш[её]л|существует|доступно)|нет\s+(?:доступных|других)|"
    r"других\s+[^.!?\n]{0,80}\s+не\s+найдено|"
    r"not\s+found|does\s+not\s+exist|no\s+(?:available|other))\b",
    re.IGNORECASE,
)
_ENTITY = re.compile(r"\b(?P<key>[A-Za-z][A-Za-z0-9_]*_id)\s*[:=]\s*(?P<value>[\w.-]+)")


def _entities(text: str) -> tuple[tuple[str, str], ...]:
    return tuple(sorted({(m.group("key"), m.group("value")) for m in _ENTITY.finditer(text)}))


_REQUEST = re.compile(r"^(?:пожалуйста|уточните|сообщите|подтвердите|please|tell me|confirm)\b", re.IGNORECASE)
_SOCIAL = re.compile(r"^(?:спасибо|благодарю|понимаю|сочувствую|thank you|i understand)\b", re.IGNORECASE)


def extract_claims_with_coverage(response: str) -> ClaimExtraction:
    """Extract conservative high-value claims without prompt, labels, or trace."""
    events = parse_events(response, "response")
    claims: list[Claim] = []
    coverage: list[ClaimCoverageItem] = []
    for event in events:
        if event.role != "assistant" or event.kind != "text":
            continue
        for match in _SENTENCE.finditer(event.text):
            text = match.group().strip()
            if not text:
                continue
            absolute = Span("response", event.source.start + match.start(), event.source.start + match.end())
            entities = _entities(text)
            before = len(claims)
            completed = _COMPLETED_RU.search(text) or _COMPLETED_EN.search(text)
            if completed:
                claims.append(Claim(
                    id=f"claim:{len(claims)}",
                    kind=ClaimKind.ACTION,
                    subject="assistant",
                    predicate=completed.group("verb").lower(),
                    object="completed",
                    source=absolute,
                    modality="completed",
                    entities=entities,
                ))
            elif _INTENT.search(text):
                claims.append(Claim(
                    id=f"claim:{len(claims)}",
                    kind=ClaimKind.INTENT,
                    subject="assistant",
                    predicate="proposed_action",
                    object=text,
                    source=absolute,
                    modality="intent",
                    entities=entities,
                ))
            elif _REFUSAL.search(text):
                claims.append(Claim(
                    id=f"claim:{len(claims)}",
                    kind=ClaimKind.REFUSAL,
                    subject="assistant",
                    predicate="task_impossible",
                    object=True,
                    source=absolute,
                    entities=entities,
                ))
            elif _ABSENCE.search(text):
                claims.append(Claim(
                    id=f"claim:{len(claims)}",
                    kind=ClaimKind.ABSENCE,
                    subject="assistant",
                    predicate="asserted_absence",
                    object=text,
                    source=absolute,
                    entities=entities,
                ))
            created = tuple(claim.id for claim in claims[before:])
            if created:
                coverage.append(ClaimCoverageItem(absolute, "CLAIM", "typed_deterministic_match", created))
            elif text.endswith("?") or _REQUEST.search(text):
                coverage.append(ClaimCoverageItem(absolute, "NON_VERIFIABLE", "question_or_request"))
            elif _SOCIAL.search(text):
                coverage.append(ClaimCoverageItem(absolute, "NON_VERIFIABLE", "social_language"))
            else:
                coverage.append(ClaimCoverageItem(absolute, "UNKNOWN", "declarative_semantics_not_extracted"))
    return ClaimExtraction(tuple(claims), tuple(coverage), "C0_deterministic_blind")


def extract_claims(response: str) -> list[Claim]:
    return list(extract_claims_with_coverage(response).claims)
