# Рабочий Guardian API/CLI — 2026-10-01

Выбран метод **R0** по завершённому сравнению: [DECISION.md](../DECISION.md).
Deployment config **`r0-service-v1`**: та же схема J→B, но лимит входа12000
символов до любой обрезки и без archive replay из dev-журнала. Это отдельный
эксплуатационный профиль, созданный после сравнения; frozen predictions
и configs не изменены. Все dev/sealed inputs короче872 символов.

## Два режима

- `structural-v02`: CPU, без API/GPU. Подтверждённый hit→ERROR;
  чистый скан→UNKNOWN, поскольку смысл не проверен.
- `r0-service-v1`: structural → Gemma4:31b через Ollama API → Ministral14B
  через Mistral API только при ERROR/UNKNOWN. GPU этому режиму не нужен.
  GP/GE, нативный Granite и Φ не входят в default. Старые experiment configs
  и V6 доступны явно по `config_id`, их качество не приписывается этому режиму.

NO_ERROR — модельная оценка, не гарантия полноты. INVALID/UNSURE B сохраняет
исходное решение; при отсутствии валидного J и B — UNKNOWN/degraded.
Правильная цитата не доказывает правильность объяснения или метки.

## Текущий Vast

Сначала читайте `/etc/vast-agents-guide.md`. Supervised service
`guardian_research` слушает **127.0.0.1:18090**; нет нового public port,
Caddy route или туннеля. Checkout `/workspace/guardian/repos/hybrid-service-worktree`,
pin `6f72cb77`. Не меняйте исполняемые файлы работающего процесса.

```powershell
ssh guardian-vast 'supervisorctl status guardian_research'
ssh guardian-vast 'curl -fsS http://127.0.0.1:18090/health'
```

Шаблоны managed запуска: `vast-local.sh`, `vast-local.conf`.
Ручной запуск в свободном отдельном checkout:

```bash
GUARDIAN_CONFIG=r0-service-v1 GUARDIAN_WORKERS=1 GUARDIAN_MAX_QUEUE=4 \
GUARDIAN_AUDIT_PATH=/workspace/guardian/results/service/audit.jsonl \
/workspace/guardian/venv/bin/python -m uvicorn service.app:app \
  --host 127.0.0.1 --port 18090 --workers 1
```

Python3.12.3, fastapi0.142.2, uvicorn0.54.0, openai3.22.1,
pandas3.0.6, pyarrow25.0.1 уже установлены; versions в `requirements-api.txt`.
NVIDIA/CUDA для default не переустанавливать. Docker live launch не проверен;
использован venv и supervisor внутри непривилегированного контейнера Vast.

Клиент читает `MISTRAL_API_KEY`/`MISTRAL_MODEL` из уже настроенного
`/workspace/guardian/secrets/mistral.env`, Ollama key — из `api_keys.env`.
Существующий формат — `export NAME='value'`. Секреты не входят в Git/audit.
`/models` удостоверяет metadata-доступ, не право на генерацию.

## HTTP и CLI

| Endpoint | Назначение |
|---|---|
| GET /health | Процесс и текущий config ID |
| GET /ready | GET/models configured providers, TTL60с, без генерации |
| GET /v1/configs | Versioned configs |
| POST /v1/check | `{case_id,prompt,response,config_id?}` |
| POST /v1/check/batch | `{cases:[...],config_id?}`, до4 в этом deployment |

Исходные policy/history/tool outputs — данные проверки. Tools из проверяемой
траектории реально не исполняются. JSON содержит ERROR/NO_ERROR/UNKNOWN,
basis/config, findings с quotes/spans/binding, assumptions, coverage,
degraded, trace_id, usage, module_trace и audit_status. Trace хранит голоса,
валидацию/re-asks, review B; structural finding CONFIRMED, смысловой JUDGED.
Сбой аудита отмечается WRITE_FAILED/degraded и не стирает решение.

```bash
cd /workspace/guardian/repos/hybrid-service-worktree
/workspace/guardian/venv/bin/python -m service.cli \
  --input cases.csv --config r0-service-v1 --outdir /workspace/guardian/results/cli

/workspace/guardian/venv/bin/python service/final_operations_probe.py \
  --output /workspace/guardian/results/operations_probe
```

CSV/parquet вход: `id,prompt,response`. Выход: `predictions.csv`,
`results.jsonl`, `audit.jsonl`. CSV mapping ERROR→1, NO_ERROR/UNKNOWN→0;
UNKNOWN обязательно сохраняется в JSONL и не является доказанной корректностью.

Operations probe — небольшой реальный HTTP/CLI smoke. Проверяет модельные
ERROR с findings и NO_ERROR с живыми calls, structural ERROR, clean offline
UNKNOWN, long/batch, оба недоступных providers в отдельном временном HTTP
процессе и восстановление через настоящие providers. Outage имитируется
направлением upstream в закрытый loopback-порт, production ключи/службы
не меняются. Это не benchmark и не выключение внешних провайдеров.

## Лимиты и цена

Один worker, очередь4, batch>4→429. HTTP deadline240с; если worker ещё
работает, после timeout его слот сохраняется до завершения. Audit может
получить позднее завершение с тем же trace_id.

Deployment cap12000 символов prompt+response; превышение→UNKNOWN до API.
Исторические исследовательские configs допускают200000, их J обрезает
середину свыше12000 явно в trace; это не полный просмотр длинной истории.

J max1500 новых токенов, B max2000; один technical JSON re-ask, не новый
голос. Wrapper transport retries ограничены, SDK retries отключены;
неудачные транспортные попытки пишутся в cost log. Usage calls/tokens —
логическая работа, api_calls/api_tokens — некешированная работа, не цена
в долларах. В старых jobs скрытые SDK attempts не сохранились полностью.
Exact-request cache находится вне Git; его latency не равна холодной latency.
Удалённое имя модели не гарантирует неизменный weight revision.

`workspace_is_volume=false`: off-box сохранение обязательно перед
Destroy/Recycle. Ничего такого не выполнялось. Общий policy compiler,
сертифицированный tool effect/reachability и перенос на новые логические
формы пока не доказаны.

Результаты: [sealed report](../docs/searh_23/HYBRID_SEALED_RESULTS_2026-10-01.md).
