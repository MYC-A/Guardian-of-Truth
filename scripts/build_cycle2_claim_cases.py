"""Build the response-only Cycle 2 claim benchmark before extractor predictions.

The external parquet read is column-projected to id/response. Prompt, trace,
label, and explanation are neither loaded nor serialized.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from guardian_truth.parsing import parse_events


KINDS = (
    "ACTION_COMPLETED", "ACTION_FAILED", "STATE", "ATTRIBUTION", "INTENT",
    "REFUSAL", "FACT", "ABSENCE", "PERMISSION", "OTHER_VERIFIABLE",
    "NON_VERIFIABLE",
)
SENTENCE = re.compile(r"[^\n.!?]+(?:[.!?]+|$)")
QUESTION_REQUEST = re.compile(
    r"\?|^[\s()\-*]*(?:пожалуйста|уточните|сообщите|подтвердите|хотите|проверьте|"
    r"предоставьте|напишите|выберите|ответьте|могу ли|please|tell me|confirm|would you|do you want)\b", re.I,
)
SOCIAL = re.compile(
    r"\b(?:мне (?:очень )?жаль|я понимаю|я (?:очень )?ценю|желаю вам|с радостью помогу|"
    r"спасибо|thank you|i understand|i(?:'m| am) sorry|happy to help)\b", re.I,
)
FAILED = re.compile(r"\b(?:не удалось|завершил(?:ась|ся) ошибкой|отклон[её]н|ошибка|failed|declined|was not completed)\b", re.I)
COMPLETED = re.compile(
    r"\b(?:успешно|уже (?:отменил|изменил|вернул|забронировал|перевел|обновил)|"
    r"(?:оплата|операция) произведена|окончательно закрыт|снова активн|я наш[её]л ваш профиль|"
    r"я (?:ещ[её] раз )?(?:проверил|изучил)\b|"
    r"i(?:'ve| have) (?:cancelled|canceled|changed|refunded|booked|transferred|updated)|"
    r"has been (?:cancelled|canceled|changed|refunded|booked|closed|updated))\b", re.I,
)
REFUSAL = re.compile(r"\b(?:не могу|нет полномочий|не предусмотрен|не смогу|невозможно|i cannot|i can't|unable to|not authorized)\b", re.I)
INTENT = re.compile(r"\b(?:я (?:могу|буду|собираюсь|предлагаю|подготовлю|проверю|оформлю|переведу)|i (?:can|will|plan to))\b", re.I)
PERMISSION = re.compile(r"\b(?:вы (?:можете|сможете)|разрешено|допускается|you (?:can|may)|is permitted|are allowed)\b", re.I)
ABSENCE = re.compile(r"\b(?:не наш[её]л|не существует|нет|не найден[оы]?|no other|not found|does not exist|none available)\b", re.I)
ATTRIBUTION = re.compile(r"\b(?:согласно|по данным|система (?:показывает|указывает)|according to|the system (?:shows|reports))\b", re.I)
CALCULATION = re.compile(r"(?:\$?\d[\d ]*(?:[.,]\d+)?\s*[-+]\s*\$?\d|=|итогов|total(?:s| is)|difference is)", re.I)
STATE = re.compile(
    r"\b(?:статус|стоимост|цен[аы]|доплата|уровень|доступн|активн|закрыт|"
    r"составляет|у вас (?:есть|два|две)|в заказе|карта|бронирован|рейс|"
    r"status|price|cost|account|card|booking|order|is active|is closed)\b", re.I,
)
ENTITY = re.compile(
    r"(?:#[A-Z]\d+|\b(?:user|reservation|order|account|card|invoice|booking)[ _-]?id\s*[:=]?\s*[\w*-]+|"
    r"\b(?:заказ|бронирование|карта|сч[её]т)\s*(?:№|#|ID)?\s*[A-Z*]?\d[\w*-]*)",
    re.I,
)
TIME = re.compile(
    r"\b(?:сейчас|сегодня|вчера|завтра|текущ\w+|\d{1,2}\s+(?:мая|июня|июля|августа)|"
    r"now|today|yesterday|tomorrow|current(?:ly)?|\d{4}-\d{2}-\d{2})\b", re.I,
)


def span_kind(text: str) -> tuple[bool, str]:
    clean = re.sub(r"[*_`]", "", text).strip()
    if re.fullmatch(r"(?:[-*]\s*)?\d+[.)]?", clean) or QUESTION_REQUEST.search(clean) or SOCIAL.search(clean):
        return False, "NON_VERIFIABLE"
    if re.search(r"\bмне (?:сначала )?(?:нужно|необходимо)\b", clean, re.I):
        return True, "FACT"
    for pattern, kind in (
        (FAILED, "ACTION_FAILED"), (COMPLETED, "ACTION_COMPLETED"),
        (REFUSAL, "REFUSAL"), (INTENT, "INTENT"), (PERMISSION, "PERMISSION"),
        (ABSENCE, "ABSENCE"), (ATTRIBUTION, "ATTRIBUTION"),
        (CALCULATION, "OTHER_VERIFIABLE"), (STATE, "STATE"),
    ):
        if pattern.search(clean):
            return True, kind
    return True, "FACT"


def annotation(identifier: str, response: str, start: int, end: int, *,
               unsupported: bool | None = None, forced_kind: str | None = None,
               forced_source: str | None = None) -> dict:
    text = response[start:end]
    declarative, kind = span_kind(text)
    kind = forced_kind or kind
    if forced_kind == "NON_VERIFIABLE":
        declarative = False
    source = forced_source or (
        "SYSTEM" if kind == "ATTRIBUTION" else
        "ASSISTANT" if kind in {"ACTION_COMPLETED", "ACTION_FAILED", "INTENT", "REFUSAL"} else
        "UNSPECIFIED"
    )
    return {
        "id": identifier,
        "start": start,
        "end": end,
        "text": text,
        "declarative": declarative,
        "kind": kind,
        "entities": sorted(set(match.group(0) for match in ENTITY.finditer(text))),
        "times": sorted(set(match.group(0) for match in TIME.finditer(text))),
        "source": source,
        "unsupported": unsupported,
    }


CONTROLLED = [
    ("finance", "The transfer for account_id A17 was completed today.", "ACTION_COMPLETED", True, "ASSISTANT"),
    ("finance", "The transfer for account_id A18 was completed today.", "ACTION_COMPLETED", False, "ASSISTANT"),
    ("travel", "Booking ID B9 has been cancelled.", "ACTION_COMPLETED", True, "ASSISTANT"),
    ("travel", "Booking ID B10 has been cancelled.", "ACTION_COMPLETED", False, "ASSISTANT"),
    ("retail", "The refund operation failed for order_id R4.", "ACTION_FAILED", False, "ASSISTANT"),
    ("retail", "The refund operation failed for order_id R5.", "ACTION_FAILED", True, "ASSISTANT"),
    ("telecom", "The activation request was declined today.", "ACTION_FAILED", False, "ASSISTANT"),
    ("telecom", "The activation request was declined yesterday.", "ACTION_FAILED", True, "ASSISTANT"),
    ("health", "The appointment status is confirmed for 2026-09-20.", "STATE", True, "SYSTEM"),
    ("health", "The appointment status is pending for 2026-09-21.", "STATE", False, "SYSTEM"),
    ("logistics", "Package order_id P22 is currently in transit.", "STATE", True, "SYSTEM"),
    ("logistics", "Package order_id P23 is currently delivered.", "STATE", False, "SYSTEM"),
    ("finance", "According to the system, account_id A19 has a balance of $40.", "ATTRIBUTION", True, "SYSTEM"),
    ("finance", "According to the system, account_id A20 has a balance of $55.", "ATTRIBUTION", False, "SYSTEM"),
    ("travel", "The booking system reports no delay for reservation_id Z7.", "ATTRIBUTION", True, "SYSTEM"),
    ("travel", "The booking system reports a delay for reservation_id Z8.", "ATTRIBUTION", False, "SYSTEM"),
    ("retail", "I will check order_id W31 tomorrow.", "INTENT", None, "ASSISTANT"),
    ("retail", "I can request a refund for order_id W32.", "INTENT", None, "ASSISTANT"),
    ("telecom", "Я проверю состояние счёта 778 завтра.", "INTENT", None, "ASSISTANT"),
    ("health", "Я подготовлю запись на 20 мая.", "INTENT", None, "ASSISTANT"),
    ("finance", "I cannot close account_id A21.", "REFUSAL", None, "ASSISTANT"),
    ("travel", "Я не могу изменить бронирование 991.", "REFUSAL", None, "ASSISTANT"),
    ("retail", "I am unable to replace order_id W33.", "REFUSAL", None, "ASSISTANT"),
    ("telecom", "У меня нет полномочий закрыть счёт 779.", "REFUSAL", None, "ASSISTANT"),
    ("science", "Water freezes at zero degrees Celsius at standard pressure.", "FACT", False, "UNSPECIFIED"),
    ("science", "Venus is the closest planet to the Sun.", "FACT", True, "UNSPECIFIED"),
    ("geography", "Paris is the capital of France.", "FACT", False, "UNSPECIFIED"),
    ("geography", "Sydney is the capital of Australia.", "FACT", True, "UNSPECIFIED"),
    ("retail", "No other order was found for user_id U8.", "ABSENCE", True, "SYSTEM"),
    ("retail", "No other order was found for user_id U9.", "ABSENCE", False, "SYSTEM"),
    ("travel", "Других рейсов на 28 мая нет.", "ABSENCE", True, "SYSTEM"),
    ("travel", "Других рейсов на 29 мая нет.", "ABSENCE", False, "SYSTEM"),
    ("finance", "You may download the statement for account_id A22.", "PERMISSION", None, "UNSPECIFIED"),
    ("travel", "Вы можете выбрать место при регистрации.", "PERMISSION", None, "UNSPECIFIED"),
    ("retail", "Returns are allowed for order_id W34.", "PERMISSION", None, "UNSPECIFIED"),
    ("telecom", "Разрешено сменить тариф после 20 мая.", "PERMISSION", None, "UNSPECIFIED"),
    ("finance", "The total is $81 - $11 = $70.", "OTHER_VERIFIABLE", True, "UNSPECIFIED"),
    ("travel", "Для трёх билетов итоговая стоимость составляет 1200 долларов.", "OTHER_VERIFIABLE", False, "UNSPECIFIED"),
    ("social", "Спасибо, что обратились к нам!", "NON_VERIFIABLE", None, "ASSISTANT"),
    ("social", "Would you like me to continue?", "NON_VERIFIABLE", None, "ASSISTANT"),
]


def build(source: Path) -> dict:
    import pandas as pd

    frame = pd.read_parquet(source, columns=["id", "response"])
    cases = []
    n_external = 0
    for row in frame.itertuples(index=False):
        annotations = []
        for event in parse_events(row.response, "response"):
            if event.role != "assistant" or event.kind != "text":
                continue
            for index, match in enumerate(SENTENCE.finditer(event.text)):
                if not match.group().strip():
                    continue
                start = event.source.start + match.start()
                end = event.source.start + match.end()
                annotations.append(annotation(f"{row.id}::s{len(annotations)}", row.response, start, end))
        n_external += len(annotations)
        cases.append({"id": row.id, "domain": row.id.split("__", 1)[0],
                      "source_kind": "EXTERNAL_RESPONSE", "response": row.response,
                      "annotations": annotations})
    for index, (domain, text, kind, unsupported, source_name) in enumerate(CONTROLLED):
        response = "⟦ASSISTANT⟧\n" + text
        start = len("⟦ASSISTANT⟧\n")
        cases.append({
            "id": f"controlled::{index:02d}", "domain": domain,
            "source_kind": "CONTROLLED_MINIMAL_PAIR", "response": response,
            "annotations": [annotation(
                f"controlled::{index:02d}::s0", response, start, len(response),
                unsupported=unsupported, forced_kind=kind, forced_source=source_name,
            )],
        })
    spans = sum(len(case["annotations"]) for case in cases)
    if not 150 <= spans <= 300 or n_external != 169:
        raise ValueError("unexpected frozen benchmark span count")
    canonical = json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": "guardian-cycle2-claim-cases-v1",
        "frozen_before_extractor_predictions": True,
        "extractor_input": "candidate_response_only",
        "source_columns_read": ["id", "response"],
        "external_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "prompt_trace_tool_label_explanation_read": False,
        "annotation_method": "rule_assisted_semantic_curation_with_controlled_minimal_pairs",
        "kind_vocabulary": list(KINDS),
        "n_external_spans": n_external,
        "n_controlled_spans": len(CONTROLLED),
        "n_spans": spans,
        "cases_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"n_spans": result["n_spans"], "cases_sha256": result["cases_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
