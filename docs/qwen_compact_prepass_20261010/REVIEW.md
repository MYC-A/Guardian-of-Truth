# Проверка нового compact/dedup runtime

Субагент `/root/archive_review` выполнил read-only code/logic review; отдельный
`/root/stage_isolation` написал только regression/contrast fixtures. Runtime
реализован root. API/model/GPU calls отсутствуют. Production не менялся.

## Проверенные границы

- Prompt-only blindness сохраняется при изменении текущих arguments/prose;
  action-conditioned metadata в pre-input не добавляются.
- Exact source alias не объединяет одинаковый текст разных actor/event/category.
  New metadata сохраняется и участвует в equality; bool/integer не смешиваются.
  None/negative/string event не alias. Text + text_ref ambiguity отвергается.
- Inverse точно восстанавливает source view; blind catalog с unmatched span,
  full parent policy, coverage и unread gaps остаются.
- Norm units идут только из normative_sources; source/evidence IDs проходят
  local schema. Transport partition точно сохраняет NOT/unless даже на границе.
  Partition completeness отделена от source completeness и assessment coverage.
- Unknown IDs, JSON/transport/packing exceptions нового optional pre-stage
  возвращают unchanged base reviewer. Нет новых reviewer retries.
- Schema/typed input mistakes не повышают Model Hypothesis до policy proof.
  Обычные final source IDs и admission не расширяются blind-only источниками.
- Already-valid positive/negative и независимые positive сохраняются; прежние
  root-close, RAW_MODEL_DECISION и DEFAULT_ZERO остаются отдельными режимами.
- Legacy wire/cache replay полностью совпадает. Compact/dedup reviewer wires
  и compact pre wire — новые запросы, прежние ответы на них не переносятся.

## Замечания, учтённые в ходе review

1. Source span уже отсутствует у обычных slim sources: alias называется
   SOURCE_RECORD_EQUIVALENCE, не original-span proof. Требуется точный code ID,
   категория, integer event и все metadata. Selected norm offsets относятся к
   parent text.
2. Empty source/norm inventory не разрешает emit фиктивных NO_SOURCE/NO_NORM:
   соответствующие arrays имеют maxItems0; placeholder items unreachable.
3. Optional inject защищён отдельно: compaction exception не отменяет primary.
4. Telemetry хранит pre и review byte budgets, bounded assessment status,
   item-cap hits, full source coverage и unit partition completeness отдельно.

## Validation

45 новых compact tests; полный выбранный runtime/contract/package set:
**184 passed, 2 skipped**. Root запустил его после final runtime changes.
Субагент отдельно запускал recovery/wire subset; замечания проверены по коду.
Полные legacy replays: **92 rows,359 exact requests,0 differences,0 missing**.
Outputs и fingerprints лежат рядом; network tripwire включён.

Независимый reviewer не обнаружил блокирующего semantic-authority обхода в
новом коде. Это не сертификация общего Guardian. Ограничения: bounded neutral
view,8 requirements и1700 completion tokens; возможная потеря нужных assessments;
LLM binding/applicability errors; новые wire quality, tokenizer fit и GPU latency
не проверены. Opt-in profile не принят как default.
