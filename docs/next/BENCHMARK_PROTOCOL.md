# Frozen benchmark protocol

## Цель и порядок фиксации

Сначала фиксируются input hashes, split/group mapping, arms, prompts, schemas,
models, thresholds, budgets и external adapter commits. После первого чтения
test labels нельзя менять detector, adapter или threshold; исправления переходят
в следующий цикл.

`valid.parquet` — development sample (46 строк, 45 trajectory groups), а не
независимая оценка. Результаты на нём служат диагностикой и regression gate.

## Arms

- Policy: P0–P6, один frozen case set и candidate pool.
- Tool effects: T0–T3; T1 задаёт human/gold reference.
- Claims: C0 deterministic blind, C1 local typed, C2 strong typed.
- End-to-end: X0 CURRENT_V5_3, X1 HOLISTIC_STRONG, X2 HOLISTIC_LOCAL,
  X3 QUERY_CONDITIONED, X4 VIGIL_LIKE, X5 PROPOSED_MIN, X6 slow path только
  после положительного conditional gain.
- Long context: L0 full, L1 top-k, L2 compile-once.

## Leakage boundaries

- Detector получает только `prompt,response`.
- Policy compiler получает только SYSTEM policy; не получает trace/response.
- Claim extractor получает только response; не получает prompt/trace.
- Label/explanation читаются harness после frozen prediction.
- Threshold выбирается только на calibration split.
- Split выполняется по trajectory group и дополнительно по policy/tool/domain
  для соответствующего generalization test.

## Метрики

End-to-end: TP/FP/FN/TN, precision, recall, F1, accuracy, FPR; per-domain,
per-policy, per-tool и per-failure-type; selective risk/coverage и abstention.
Для scores: AUROC/AUPRC, Brier, ECE. Для policy/effects/claims — coverage,
precision/recall и conditional downstream gain.

Сравнения парные: exact McNemar и hierarchical bootstrap по trajectories.
Отчёт обязан включать point delta и 95% CI, а не только среднее. На 46-row
development sample CI ожидаемо широк; это не повод скрывать его.

## Budget fairness

Каждый arm получает одинаковые максимумы input chars/tokens, output tokens,
HTTP attempts и wall time. Отдельно публикуются фактические requests, tokens,
latency p50/p95, errors/rate limits и стоимость. Compile-once cost амортизируется
по policy hash и показывается отдельно.

## Metamorphic regression suite

Минимум 14 пар: user/assistant role swap; intent/completed; claim/observation;
attempt/confirmed effect; failed/no-effect; not-found/absence; unknown/false;
proposal/execution; request/confirmation; same type/different entity;
old/current; tool name/effect; LLM hypothesis/fact; irrelevant-context append.

Любой hard violation на отрицательной стороне такой пары блокирует кандидат до
разбора. Incumbent exact positives должны сохраняться (`incumbent protection`).

## Воспроизводимый запуск

```powershell
python -m guardian_truth.next.evaluate baseline --input valid.parquet
python -m guardian_truth.next.evaluate policy --input valid.parquet
python -m guardian_truth.next.evaluate tool --input valid.parquet
python -m guardian_truth.next.evaluate claims --input valid.parquet
python -m guardian_truth.next.evaluate internal --input valid.parquet
python -m guardian_truth.next.evaluate external --external-root <pinned-checkouts-root>
python -m guardian_truth.next.evaluate final
```

Не реализованные arms записываются как `unavailable`/`not_run`; это часть
протокола, а не нулевой результат.

Первый frozen external run уже выполнен. Поле
`first_blind_run_occurred=true` теперь намеренно блокирует повторный запуск с
тем же manifest. Новый detector, renderer, threshold или subset требует нового
versioned manifest/cycle; историю текущего run переписывать нельзя.
