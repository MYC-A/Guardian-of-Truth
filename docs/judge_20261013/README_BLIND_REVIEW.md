# Blind review A/B/C/D — исправленный пакет кода, 17.10.2026

Статус: IMPLEMENTED / CPU_VERIFIED / GPU_UNTESTED. Quality, production timing,
независимая оценка и Linux CI отдельно отмечаются в отчёте. Это opt-in пакет
исходников и точного patch без весов/runtime. Production JUDGE_CONFIG.json сохранён.

## Исполнение

A — прежний overall; B — final checklist без prepass; C — open prepass + final;
D — blind prepass + final. Один offline vllm.LLM. Overall/final: exact one-token
log P(YES) − log P(NO), temperature=1. Prepass: отдельные SamplingParams,
temperature=0, max_tokens=384, thinking=False. С резервным overall D требует три
вызова на строку. Три offline-повтора — повторение опыта, не голоса на строку.

Сначала все primary записываются с fsync. Опциональный run-local файл
primary-inputs-<run_id>.jsonl сохраняет текст, хэши, позицию, фактическое сокращение
и cap каждой primary-попытки. Для успешно оценённой строки это вход, переданный
модели. Технический отказ primary не запрещает review сохранённого подготовленного
входа. В RAM остаются offsets/хэши, а не все большие запросы.

Final читает эту основу с проверкой run/input/row/token integrity и заново
build_prompt не вызывает. Notes — MODEL_HYPOTHESIS. Если notes не помещаются,
DROPPED_SIZE. Если не помещается сам checklist, FINAL_BUILD_ERROR/FINAL_TOO_LONG,
без скрытого изменения исходника. Любой отсутствующий/inexact/error final оставляет
весь набор на primary(review_incomplete). Сохраняются квота .30 и hard override;
рейтинги по строкам не смешиваются. Повторная final-запись отключает этот рейтинг.

Blind использует только prompt и фиксированные параметры. C/D отличаются лишь
видимостью response. Notes: entities, условные constraints MUST/MUST_NOT/MAY с
предпосылками/исключениями, unknowns. Источники адресуются кодом; валидная ссылка
не доказывает семантическую применимость. TRUNCATED/INVALID/ERROR отличаются от
VALID, пустые notes считаются отдельно. Ошибка одного output/parsing/scoring
изолирована по строке; primary не переписывается.

## Применение архива

Распаковать ZIP в отдельную папку. PACKAGE_MANIFEST.json содержит base SHA,
source commit, SHA256 файлов. Installer проверяет integrity, компиляцию Python,
base SHA, чистоту worktree и git apply --check до изменения исходников.
При чужих изменениях отказывается писать; точно применённый пакет даёт ALREADY_APPLIED.

```powershell
python 'A:\PATH\PACKAGE\apply_blind_review_patch.py' --repo 'C:\PATH\WORKTREE' --check
python 'A:\PATH\PACKAGE\apply_blind_review_patch.py' --repo 'C:\PATH\WORKTREE'
Set-Location 'C:\PATH\WORKTREE'
$env:PYTHONPATH = "$PWD\src;$PWD"
python -m unittest tests.test_transcript tests.test_judge_mechanical tests.test_judge_transcript_integration tests.test_judge_v3 tests.test_judge_stage_rows tests.test_judge_u2 tests.test_u2_action_policy tests.test_judge_build_mode tests.test_evidence_packer tests.test_judge_blind_review tests.test_judge_blind_review_integration -v
```

История содержит NTFS-недопустимые пути. Подготовка НОВОГО worktree в Windows:

```powershell
git worktree add --no-checkout -b YOUR_NEW_BRANCH C:/PATH/WORKTREE BASE_SHA
git -C C:/PATH/WORKTREE -c core.protectNTFS=false sparse-checkout set .github docs scripts src submission tests experiments/u2_action_policy_20261016
git -C C:/PATH/WORKTREE -c core.protectNTFS=false read-tree -mu HEAD
```

Фильтр sparse исключает исторические outputs; core.protectNTFS здесь применяется
только к этим командам. Не делать полный checkout/reset существующих копий.

Новые тесты проверяют snapshots/interrupted write, сохранённое сокращение,
checklist overflow, ошибки outputs, все arms через настоящий stage, supervisor с
mock process transport, literal/duplicate id, Parquet, отсутствие gold и глобальный
fallback. Сборщик проверяется на минимальном fixture ZIP, не конкурсном архиве.
Workflow сохраняет старые тесты и реальный encoder, добавляя новые проверки.
Локальные файлы encoder: A:/Guardian-weights/u2-minilm-e8f8c211.

## Команды GPU-эксперимента — ещё не выполненные результаты

До запусков нужны inventory inputs/labels, дедупликация, группы и split manifests.
valid46 — только регрессии. Просмотренные данные — EXPLORATORY. Сначала pilot
16–32 уникальных строк разных длин. Только при >15% обрывов по max_tokens разрешено
один раз повысить 384→768 одинаково для C/D до quality, без выбора по меткам.

```bash
export PYTHONPATH="$PWD/src:$PWD"
for ARM in A_off B_none C_open; do
  for REP in 1 2 3; do
    python scripts/eval_judge_valid.py --input DATA.parquet --model /existing/qwen36-awq \
      --config submission/JUDGE_BLIND_REVIEW_${ARM}.json --python /runtime/run_python.sh \
      --seconds 3600 --out runs/br_${ARM}_r${REP}
  done
done
for REP in 1 2 3; do
  python scripts/eval_judge_valid.py --input DATA.parquet --model /existing/qwen36-awq \
    --config submission/JUDGE_BLIND_REVIEW_EXPERIMENT.json --python /runtime/run_python.sh \
    --seconds 3600 --out runs/br_D_r${REP}
done
python scripts/judge_analysis.py --input DATA.parquet \
  --run runs/br_A_off_r1 --run runs/br_B_none_r1 --run runs/br_C_open_r1 --run runs/br_D_r1 \
  --out runs/analysis_r1.json
```

Модель: cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit,
revision 00fcea2d3bcf5389b518d4fc082e5590e0ba4844. Использовать проверенные локальные веса.
eval оценивает effective рейтинг и отдельно пишет primary_score/final_score.
Analysis проверяет хэши контекстов между arms, где они доступны, и блокирует
matched-сравнение при несовпадении. Он сообщает AUC/AP, F1/P/R/confusion при .30,
paired grouped ΔF1/ΔAUC CI на exact-пересечении, без переноса prevalence 130/548.
All-row hard/fallback метрики — отдельно в eval. Подбор порога выключен по умолчанию;
--exploratory-thresholds включает только явно оптимистичную диагностику.

Группы id-prefix — технический fallback, не доказательство независимости: проверить
по inventory, при необходимости задать --group-regex. Повторы не складывать в новые
независимые задачи. Analysis не выдаёт автоматический ACCEPT по одной метрике.
Длинный quality deadline не доказывает runtime: нужен отдельный настоящий supervisor
с stop=1380, kill=1530, watchdog=1680 от predict.py, внешним лимитом 1800 с и холодным
стартом. CPU/fake-vLLM не подтверждают F1 Qwen или скорость. Итог качества до GPU,
проверки данных и полного бюджета — INSUFFICIENT_EVIDENCE.
