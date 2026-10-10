# Qwen: компактный blind pre-pass, готовый к серверному сравнению

Ветка `fix/qwen-compact-prepass-20261010`. Основа — output-recovery runtime
`75ebc063` с отдельным аудитом `4bea4aa4`. Готовый конкурсный ZIP не менялся.
Новых model/API/SSH вызовов нет; сервер пользователь предоставит позже.
Runtime-код и тесты зафиксированы в `b8c6e111`; следующая публикация добавляет
отчёты/receipt и tooling измерений, не новый runtime.

## Реализованные режимы

Public entry point: `python -m guardian_truth.submission.cli --pre-profile ...`.

| Режим | Pre-pass | Reviewer | Назначение |
|---|---|---|---|
| `legacy` (default) | Исходный blind2, max3400 | Исходный B2 wire | Контроль и сохранение прежнего поведения |
| `dedup` | Тот же запрос и схема blind2 | Exact source aliases вместо повторного текста | Отдельная абляция переноса источников |
| `compact` | Новая адресная схема, max1700 | Aliases + компактные hypotheses + code-owned selected norm units | Кандидат для проверки скорости/качества |

В compact модель не копирует policy quotations. Код выдаёт norm-unit IDs;
модель выбирает адрес нормы, указывает условный scope, состояние условий в
прочитанной истории и короткое объяснение. Entities/ownership, вычисления с
inputs, expected actions и uncertainties сохраняются. String bounds локально
проверяются схемой: ничего не обрезается после ответа. Некорректный pre-pass
отбрасывается с диагностикой, исходный reviewer выполняется без нового retry.

Unit — транспортный кусок, **не атомарное бизнес-правило**. Полный parent policy
доступен pre-pass и reviewer; NOT/guards/exceptions не удаляются даже на границе
600-character chunks. Offset относится к точному parent source text, не к
полному original prompt. Selected unit text добавляет код, а не модель. Это
ограниченный повтор выбранных premises; полная blind policy второй раз не
копируется там, где есть подтверждённый alias.

Aliases требуют той же категории, code-issued ID после `blind:`, неотрицательного
integer event, роли, tool/kind, текста и всех остальных metadata. По совпавшему
тексту разных событий alias не создаётся. Basis — source-record equivalence,
не восстановленная original-span identity. Blind catalog с отдельным span
сохраняется, если ordinary packet не имеет той же записи. Code inverse точно
восстанавливает весь blind view. Coverage/unread и chronology сохраняются.

Scope/state остаются MODEL_HYPOTHESIS. Не вводятся правила по tool names,
benchmark IDs или доменам; нет автоматического расширения области нормы с
return/update на lookup. Final admission принимает только ordinary packet IDs.
Blind-only facts остаются citation gaps, source address не доказывает binding.

## Ответ для каждой обработанной строки

Первичный reviewer сохраняет прежнюю reason-last schema, max1700 и admission v2.
Сохранены root-close normalization только после полной повторной validation,
отдельное RAW_MODEL_DECISION при пригодном полном enum и DEFAULT_ZERO, если
классификации нет. Нет дополнительных reviewer calls. Already-supported
positive и прежние успешные 0/1 не заменяются fallback.

Новый optional pre-stage имеет отдельный catch: ошибка компактизации возвращает
unchanged base review, а не преждевременно переводит строку в0. Последующая
pipeline/layer/per-future ошибка обрабатывается прежним recovery. Полный выход
остаётся ordered Parquet `id,label`, label int64 0/1. Startup/input/I/O failure
или внешнее убийство процесса не могут гарантировать готовый файл.

## Проверено локально

- 184 passed, 2 платформенных skipped в выбранном runtime/contract/package set.
  Новые независимые compact boundary fixtures: 45 tests. Review и fixtures
  выполнены отдельными субагентами; root также проверил full runtime.
- Полные frozen legacy replays:46+46 rows, **179+180 exact requests**,0 changes
  binary/owner/accusation;0 missing requests. Это regression preservation,
  не новое качество compact и не повторная inference.
- Source roundtrip на полном baseline46 для нового dedup: все совпали.
- **45/46** сохранённых pre proposals помещаются в60 000-byte reviewer cap после
  dedup, против32/46 доставленных в старом прогоне. Оставшаяся proposal —61 024
  bytes. Это проверка размера нового wire; старый reviewer reply не переносится.
- Во втором архиве: **44/46** помещаются после dedup против34/46 delivered;
  max61 894 bytes. На одинаковом delivered subset reviewer wire сокращается
  на15.3% /15.5% в первом/втором архиве. Дополнительные analyses увеличивают
  aggregate reviewer input: выигрыш subset нельзя считать whole-run ускорением.
- Compact pre requests:46/46 проходят byte cap, maximum38 333 bytes. Минимальный
  compact reviewer с empty arrays также46/46 помещается, max56 037. Реальные
  новые answers и tokenizer/context fit пока не измерены: нижняя граница не
  доказывает доставку любого полного ответа. Ordinary cap60000 не повышался.
- Новая pre representation увеличила суммарный pre wire на6.4% из-за units и
  схемы. Ожидаемая экономия — прежде всего меньше generated quotations/prose,
  а не обещанное уменьшение каждого pre input. Измерения tokens/latency требуют
  сервера. Новые delivered analyses могут добавить reviewer input.

Receipts: [wire accounting](baseline46_wire_accounting.json),
[second archive accounting](speed16_wire_accounting.json),
[legacy baseline replay](legacy_baseline46_replay.json),
[legacy speed16 replay](legacy_speed16_replay.json).

Код: `src/guardian_truth/submission/blind_compact.py`; CLI wiring — `cli.py`.
Tests: `tests/test_submission_blind_compact.py`. Offline reproduction:

```powershell
$env:PYTHONPATH='src;.'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONUTF8='1'
python -X utf8 scripts/blind_prepass_offline_audit.py --input valid.parquet --calls outputs/qwen_submission_20261008/bench-baseline-20261008/calls.json --traces outputs/qwen_submission_20261008/bench-baseline-20261008/traces.jsonl --candidate-accounting --output <NEW_REPORT.json>
```

Это размер/контрактный replay. Никакие predictions compact из старых raw не
создаются. Live protocol: [SERVER_PROTOCOL.md](SERVER_PROTOCOL.md).
Independent checks: [REVIEW.md](REVIEW.md).
