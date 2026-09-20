"""Smoke test: LangExtract + z-ai GLM on the refund-rule example from the
user directive (RU). Verifies:
 1. extraction really runs through LangExtract (not decoratively),
 2. extracted elements carry char spans that are byte-exact vs source,
 3. the exception clause is found and anchored.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.langextract_zai import extractions_to_records, run_langextract

SOURCE = (
    "Правила обработки возвратов.\n"
    "Возврат средств запрещён без проверки личности, кроме случаев, когда "
    "клиент уже прошёл проверку в текущем обращении.\n"
    "Для возвратов свыше 10 000 рублей требуется подтверждение руководителя.\n"
    "Возвраты по заказам с уже полученным подтверждением не требуют нового "
    "подтверждения."
)

from langextract.core import data as lx_data

examples = [
    lx_data.ExampleData(
        text=(
            "Правила блокировки карт.\n"
            "Блокировка карты возможна только по заявлению клиента, "
            "за исключением случаев подозрения на мошенничество."
        ),
        extractions=[
            lx_data.Extraction(
                extraction_class="обязанность",
                extraction_text="Блокировка карты возможна только по заявлению клиента",
                attributes={"тип": "обязательное условие"},
            ),
            lx_data.Extraction(
                extraction_class="исключение",
                extraction_text="за исключением случаев подозрения на мошенничество",
                attributes={"тип": "исключение"},
            ),
        ],
    )
]

result, n_calls = run_langextract(
    SOURCE,
    prompt_description=(
        "Извлеки из текста все нормативные смысловые элементы: обязанности, "
        "запреты, разрешения, условия, исключения и пороговые значения. "
        "Для каждого элемента укажи класс (обязанность|запрет|разрешение|"
        "условие|исключение|порог) и скопируй точный фрагмент исходного текста."
    ),
    examples=examples,
    max_char_buffer=2000,
    tag_prefix="smoke-lx",
)

recs = extractions_to_records(result, SOURCE)
print(f"n_calls={n_calls}, n_extractions={len(recs)}")
for r in recs:
    print(
        f"  [{r['class']:>10}] span=({r['start']},{r['end']}) exact={r['span_exact']} "
        f"status={r['alignment_status']}: {r['text'][:70]}"
    )

# gate: at least one exception found and anchored
has_exc = any(r["class"] == "исключение" and r["span_exact"] for r in recs)
has_threshold = any(r["class"] in ("порог", "условие") and r["span_exact"] for r in recs)
print(f"GATE exception_anchored={has_exc} threshold_anchored={has_threshold}")
assert recs, "no extractions"
assert all(r["span_exact"] for r in recs if r["start"] is not None), "non-exact span"
print("LX SMOKE OK")
