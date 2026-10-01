# Guardian Check Service — Stage A (2026-10-01)

Минимальный работающий сервис проверки хода AI-агента по политике,
каталогу инструментов и истории. Реализован на существующем baseline
(задание «Guardian как сервис», §13): детерминированный слой —
исправленный структурный канал v0.2 (директива §5.1); модельный слой —
пре-регистрированное V6-правило двух судей с третьим проверяльщиком
только при расхождении (`experiments/searh_23/three_architectures/
PREREGISTERED_PROTOCOL.md`).

## Запуск

```bash
# локальный офлайн-режим (structural-only, ключи не нужны):
python -m uvicorn service.app:app --host 0.0.0.0 --port 8090

# модельный режим V6 (нужен env провайдеров three_architectures):
GUARDIAN_CONFIG=v6-judges python -m uvicorn service.app:app --port 8090

# batch CLI (официальный формат id,prompt,response -> predictions.csv):
python -m service.cli --input valid.parquet --config structural-v02 \
    --outdir outputs/service_smoke
```

Зависимости: `fastapi`, `uvicorn` (+ `openai`, `pandas` для v6/batch).
GPU для structural-v02 не нужен; v6-judges использует API-каналы
(gemma4:31b / gpt-oss через ollama.com, mistral через api.mistral.ai).

## API

| Endpoint | Назначение |
|---|---|
| `GET /health` | живость процесса (без опроса моделей) |
| `GET /ready` | готовность каналов: structural / parser / mistral / ollama |
| `GET /v1/configs` | список замороженных конфигов |
| `POST /v1/check` | один кейс `{case_id, prompt, response}` |
| `POST /v1/check/batch` | до 64 кейсов за вызов |

Ответ (§13):

```json
{
  "case_id": "example",
  "decision": "ERROR | NO_ERROR | UNKNOWN",
  "decision_basis": "schema | model | hybrid",
  "config_id": "structural-v02",
  "findings": [{"type": "...", "checked": {...}, "quotes": [...],
                 "binding": {...}, "arguments_for": [...],
                 "arguments_against": [], "status": "CONFIRMED|JUDGED",
                 "module": "structural_v02 | judge/<model>"}],
  "assumptions": [],
  "coverage": {"structural": "clean_scan", "model": "not_configured"},
  "degraded": false,
  "trace_id": "5a1f43ea19c44e6d",
  "usage": {"calls": 0, "tokens": 0}
}
```

## Семантика решений (честность по построению)

- **ERROR** — есть подтверждённый structural-хит (basis `schema`) или
  обоснованный судьями новый ошибочный ход (basis `model`).
- **NO_ERROR** — только в конфигурациях, где семантику реально покрывает
  модельный слой (консенсус двух судей с валидными голосами). Чистый
  структурный скан ≠ доказательство корректности.
- **UNKNOWN** — покрытие неполно (модель не настроена), невалидные
  голоса после единственного технического re-ask, недоступный канал
  (никогда не молчаливый 0/1 — `degraded: true` + причина), превышение
  контекстного бюджета.
- Маппинг для `predictions.csv`: `ERROR -> 1`, `NO_ERROR/UNKNOWN -> 0`
  (заморожено в конфиге, качество маппинга UNKNOWN измеряется на dev).

## Конфиги (заморожены, без правки кода)

- `structural-v02` — офлайн-детерминированный baseline (v0.2).
- `v6-judges` — structural + V6: J1 `gemma4:31b`, J2
  `ministral-14b-latest` (по одному голосу на семейство), третий
  `gpt-oss:20b` ТОЛЬКО при расхождении/невалидном голосе; повторы одной
  модели никогда не голосуют; недоступный канал = деградация кейса.

## Ограничения контура (24 ГБ GPU / 31 ГБ RAM)

- structural-v02: CPU-only, <1 c на кейс, без внешних вызовов.
- v6-judges: 2 API-вызова на кейс (3 при эскалации ~15-35%); latency
  определяется провайдером; локальный granite-guardian-4.1-8b (bf16
 15.6 GiB) подключается отдельным конфигом после нативного
  V5-тестирования (см. HISTORY_AUDIT §18).
- Очередь: `GUARDIAN_MAX_QUEUE` (по умолчанию 8), таймаут запроса и
  контекстный бюджет — в конфиге (`limits`).

## Smoke

```bash
python service/test_service_smoke.py   # 7/7: readiness, запрос, batch,
                                        # бюджет, деградация канала, аудит
```
