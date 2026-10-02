# Отдельный модульный исследовательский сервис

Состояние проверено 2026-10-02. Исследовательская ветка
`research/modular-step2-4-20261002`; рабочий процесс закреплён на
`3a6ffcb197a59c45b4cfcc023c2ce859ef65781b`.

## Процессы и доступ

| Процесс | Адрес | Default | Назначение |
|---|---|---|---|
| `guardian_research` | `127.0.0.1:18090` | прежний R0 | Существующий сервис |
| `guardian_modular_20261002` | `127.0.0.1:18092` | `modular-structural-v1` | Изолированный эксперимент |

Подключение — настроенный SSH `guardian-vast`. Прочитать operating guide
`/etc/vast-agents-guide.md` до управления instance. Public proxy, туннель
и default R0 не менялись. Старый процесс сохранил PID10702 при обновлении.

Checkout: `/workspace/guardian/repos/modular-step2-4-3a6ffcb1`.
Python: `/workspace/guardian/modular_venv/bin/python`.
Supervisor config: `/etc/supervisor/conf.d/guardian_modular_20261002.conf`.
Журналы: `/workspace/guardian/results/modular_steps_20261002/`.

## Интерфейс и смысл статусов

`GET /health`, `GET /ready`, `GET /v1/configs`, `POST /v1/check`,
`POST /v1/check/batch`. Check принимает `case_id`, `prompt`, `response`,
необязательный `config_id`. Batch не более4, один worker и очередь4,
deadline240s; занятый worker не освобождается досрочно после timeout.

`ready=true` удостоверяет наличие локального контура. Отдельные поля
`provider_availability=UNPROBED`, `inference_probe_performed=false`
показывают, что доступность удалённого inference этим не проверена.

Default structural выявляет только поддержанные механические нарушения.
UNKNOWN при прозаической политике — допустимое отсутствие semantic coverage,
не правильная отрицательная метка. Replay повторяет точную архивную запись
C0 и имеет basis `ARCHIVED_JUDGED_REPLAY_NOT_NEW_INFERENCE`.

Модельные R0/strict-B/always-B/graph/atomic/SystemV2 профили исполнимы,
но часть не измерена end-to-end. Native/model-proposed результаты advisory;
Oracle-код импортируется только диагностикой/тестами, не inference-сервисом.

## Лимиты и отказ

При `len(prompt)+len(response)>12000` — UNKNOWN до inference, без обрезки.
При исчерпании общего бюджета — UNKNOWN, `degraded=true`,
`resource_guard/...` и реальная стоимость попыток. Оригинальный pilot cap
не увеличен: 699667/700000 логических токенов/консервативных bounds;
новая холодная заявка в текущем состоянии не помещается.

На запрос ограничено20 фактических API-attempts; скрытые SDK retries
отключены. INVALID B не получает статус CONFIRMED в строгом профиле.
JSONL сохраняет UNKNOWN. CLI binary CSV mapping0 указан явно, это не
определённый NO_ERROR.

## Что реально проверено

- 16 regression-проверок прошли на Windows Python3.13 и server Python3.12
  на предшествующей кодовой ревизии2467dcfa. Изменение3a6ffcb1 касается
  переносимого fingerprint frozen-протокола; его совпадение отдельно
  проверено на обеих платформах.
- Новый live HTTP long-bank: 48 входов 1k/4k/8k/12k проходят механическую
  обработку целиком; 12 входов12001 возвращают UNKNOWN без обрезки.
- R0 live HTTP с исчерпанным ledger возвращает UNKNOWN через resource guard,
  actual API attempts0. Это проверка лимита, не настоящий provider outage.
- Прежние replay/batch/CLI-resume и симулированный auxiliary отказ проверены
  на `ed641291`; старые receipts сохранены отдельно.
- На текущем процессе HTTP подтвердил регистрацию
  `modular-negative-adaptive-v1`: запрос вернул UNKNOWN/degraded через
  resource guard, новых API-attempts0. Primary/B inference не выполнялся.
- Frozen selection V4 на Windows и сервере совпадает как разобранный JSON.
  Сам shared-B прогон остановлен до провайдера: BUDGET_STOP, done0/192.

Новые receipts находятся в `outputs/searh_23/modular_steps_20261002/`:
`modular_service_receipt_3a6ffcb1.json`, `adaptive_http_probe.json`,
`negative_review_pilot_v4/selection_server.json` и
`negative_review_pilot_v4/status.json`. Предыдущие
`modular_service_receipt_b0abb74c.json` и `service_long_v2_probes/receipt.json`
сохранены как история проверок.
Сравнение semantic labels на длинных входах ещё не выполнялось.

## Воспроизведение и обновление

Из изолированного checkout на сервере, сохраняя текущий ledger:

```bash
/workspace/guardian/modular_venv/bin/python experiments/searh_23/modular_steps_20261002/http_long_context_probe.py
/workspace/guardian/modular_venv/bin/python experiments/searh_23/modular_steps_20261002/modular_cli.py --input cases.jsonl --output decisions.jsonl --config modular-replay-v1 --csv decisions.csv
```

Для обновления нашего процесса `remote_service.py COMMIT_SHA --replace-own`
создаёт новый immutable checkout, проверяет точный собственный command,
порт/каталог/default и единственную supervisor section. Backup предыдущего
собственного config сохраняется на сервере; чужая section или изменённый
command останавливает замену. Используется только `supervisorctl update
guardian_modular_20261002`. Исходный процесс18090 не перезапускается.

Исходная manifest/JSONL/prompt bytes сохраняются LF между Windows/Linux
через `.gitattributes`. Код, новые данные и важные receipts сохранены Git
и локально; `workspace_is_volume=false`, Destroy/Recycle уничтожит контейнер.
Такие действия не выполнялись.
