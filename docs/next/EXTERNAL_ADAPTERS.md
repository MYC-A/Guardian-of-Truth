# External adapters: safe pre-run scaffold

Статус на 2026-09-12: format-only adapters реализованы и проверены на локальных
fixtures, но ни один внешний labelled run не выполнялся. Файл
`outputs/next/external_results.json` по-прежнему обязан оставаться `not_run`, пока
readiness manifest не станет полностью зелёным.

## Граница данных

Каждый adapter возвращает две разные проекции:

- `model_view()` — только native trace/messages и native tool schemas;
- `harness_view()` — label, его provenance, failure categories и native target indices.

Harness обязан сначала сохранить prediction, и только затем читать
`harness_view()`. Adapter не исполняет tools, не запускает модель, не выбирает
subset и не исправляет входные данные. Неизвестный role, partial reward,
сломанный target index или нелокализуемая injection приводят к исключению, а не
к догадке.

Запрещены любые преобразования, способные помочь Guardian: переименование tools,
перефразирование policy, упрощение JSON, удаление distractors, verb aliases,
инъекция недостающего state и ручной repair trace. `native_events` сохраняют
исходные dict-поля и порядок; адаптер добавляет только routing metadata вне
native событий.

## Честная роль источников

| Source | Поддерживаемый native artifact | Scope | Label mapping | Ограничение |
|---|---|---|---|---|
| ATFD | synthetic trajectory JSON и bundled `tau_bench/results/final/*.json` | localized synthetic; trajectory-level recorded τ | synthetic `ground_truth.outcome`; recorded mapping повторяет pinned ATFD `TauBenchAdapter` | synthetic остаётся `SOURCE_SYNTHETIC`; recorded reward не локализует turn |
| historical τ-bench | `historical_trajectories/*.json` | trajectory-level end-to-end | только exact reward 0/1 | reward не локализует turn; partial rewards отклоняются |
| AgentDojo | native `TraceLogger` JSON | localized injection security | `security=false` → failure | utility failures не переназначаются; injection должна verbatim находиться в tool result |
| ToolSandbox | generated `conversation.json` | tool/schema OOD diagnostic | отсутствует | similarity/milestones не превращаются в Guardian label |
| BFCL | native BFCL v4 JSONL row with inline `function` schemas | independent tool/schema OOD diagnostic | отсутствует | reference answer не является recorded monitoring trajectory; multi-turn rows требуют отдельного frozen schema join |

Таким образом, ToolSandbox и BFCL могут измерять schema/effect-vocabulary
coverage, но не должны попадать в общий TP/FP/FN/TN Guardian. Это не «нулевые
результаты», а другой тип evidence.

## Freeze gate до первого blind run

Source of truth — `contracts/external_sources_v1.json`. Для каждого источника
до запуска нужны:

1. exact selected file paths и SHA-256;
2. принятый license review;
3. frozen label-independent selection rule, sample budget, grouped split policy,
   subset/unsupported-row policy и grouping;
4. frozen Guardian commit/tree;
5. hashes config, prompts, thresholds и model manifest.

`external_readiness()` не читает datasets или labels без явно переданных локальных
checkout roots. При переданных roots он read-only проверяет exact Git HEAD,
безопасность relative paths, selected-file SHA-256 и наличие license file.
Текущее машинное состояние записано в
`outputs/next/external_adapter_readiness.json` и равно `not_ready`. После первого
run любые найденные ошибки можно только записывать в
`NEXT_CYCLE_CANDIDATES.md`; менять adapter, regex, aliases, prompt или threshold
на том же blind subset нельзя.

Readiness artifact содержит SHA-256 самого freeze manifest, поэтому его нельзя
незаметно переставить на другую selection/configuration.

## Подтверждённые native contracts

Форматы сверены непосредственно с закреплёнными revisions:

- ATFD synthetic trajectory: `trajectory_id`, `ground_truth`, `failure_event_indices`, `events`;
- ATFD recorded τ document: document-level `info.environment_info.policy` плюс native
  `simulations[].messages`, `reward_info`, `termination_reason`, `task_id`, `trial`;
- τ-bench historical row: `task_id`, `reward`, `info`, `traj`, `trial`;
- AgentDojo `TraceLogger`: context fields, `messages`, `error`, `utility`, `security`;
- ToolSandbox scenario artifacts: `conversation.json` с `messages` и `tools`;
- BFCL: JSONL rows с `id`, `question` и inline `function`; multi-turn `path`
  никогда не используется как замена schema, так как это answer-side signal.

Лицензии обнаружены в pinned revisions: ATFD CC-BY-4.0, τ-bench MIT,
AgentDojo MIT, ToolSandbox Apple sample-code license, BFCL Apache-2.0. В manifest
они намеренно имеют статус `detected_pending_approval`: обнаружение текста
лицензии не заменяет решение о допустимости конкретного evaluation/redistribution.

## Локальная проверка без external run

```powershell
python -m pytest tests/test_next_external_adapters.py -q
```

Fixture-тесты проверяют schema validation, label isolation, native trace
preservation, grouping, отсутствие ложного end-to-end label для ToolSandbox и
BFCL и fail-closed readiness.
