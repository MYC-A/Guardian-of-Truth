# Наборы для следующего judge-эксперимента — 18.10.2026

Подготовлены реальные файлы для переноса на GPU. Новых модельных вызовов,
платформенных отправок, обучения и генерации синтетических диалогов не было.
Исходный код текущего решения и его ZIP не пересобирались.

Локальный пакет: `A:/Guardian-submissions/judge-eval-data-20261018/ready-v1/`.
Компактные manifests этого выпуска лежат рядом с этим документом. Полные CSV,
метки, лицензии и построчный token preflight находятся в переносимом data-архиве.

## Состав и порядок использования

| Файл / раздел | Строк | 0 / 1 | Групп | Назначение |
|---|---:|---:|---:|---|
| `pilot32` | 32 | 16 / 16 | 11 | Первый технический GPU-прогон: 24 CompliBench + 8 самых длинных уникальных исторических диалогов |
| `compli_dev` | 520 | 375 / 145 | 6 intent-семейств | Проверка реализации и фиксация кандидата до просмотра его eval-результатов |
| `compli_eval` | 1893 | 1320 / 573 | 21 intent-семейство | Внешняя проверка переноса на отложенных семействах; ограничения ниже |
| `regression_seen` | 397 | 154 / 243 | 355 prompt-proxy | Просмотренные Guardian-регрессии; не новый holdout |
| `auxiliary_policyguard` | 300 | 168 no_violation / 132 violation | Не установлены | Только вспомогательная задача целой траектории; исключена из текущего quality-run |

Дополнительный `compli_pilot` содержит те же 24 benchmark-строки, что входят в
`pilot32`. Повторно запускать его после `pilot32` не нужно. Pilot и его поднаборы
не суммируются как независимые наблюдения; восемь длинных примеров намеренно
повторяются в регрессионном наборе.

Всего в CompliBench-source 306 диалогов и 2713 ходов ассистента. Три pilot-семейства
содержат 300 ходов; 24 используются в пилоте, оставшиеся 276 не входят в dev/eval.
В dev+eval 2413 текущих ходов, без искусственного выравнивания долей классов.
Равенство классов в pilot32 получилось при отборе без меток, оно не было критерием.

Каждый основной раздел содержит:

- `inputs.csv`: **только id,prompt,response**; это вход для модели.
- `labels.jsonl`: позиция, literal id, gold, группа, provenance и source SHA;
  объяснения/аннотации остаются только здесь.
- `MANIFEST.json`: размер, SHA256, классы и состав раздела.
- `TOKEN_PREFLIGHT.jsonl`: фактические токены и хэши текста/token IDs для подготовки
  overall и open-audit через нынешние runtime helpers; без генерации модели.

## Откуда данные и как они преобразованы

**CompliBench:** официальный
[UCSB-NLP-Chang/CompliBench](https://github.com/UCSB-NLP-Chang/CompliBench), commit
`593543022f67914e7ec9a312b7fa39c8a75e508a`, Apache-2.0.
Исходный архив скачан, его SHA/размер проверены; внешний Python-код не исполнялся.

За gold взята ровно опубликованная логика `convjudge/evaluation/metrics.py::build_truth`:
аннотированные assistant turns считаются non-violation; принадлежность `mistakes`
делает текущий ход violation. Новых оценок судьи или переоценки меток нет.
Несовпадение ролей, дубли индексов или отсутствующая аннотация вызывают ошибку
подготовки, а не автоматическую отрицательную метку.

Модель получает **исходные** oracle `assistant_guidelines`, категории 2 и 3,
в production-совместимом `<policy>` и role-маркерах. Категория 1 исключается так же,
как в исходной оценке CompliBench. `assistant_guidelines_shuffled`, `mistakes`,
`violation_directives`, persona, phase/key/category-аннотации сообщений и gold
не попадают в model input. История включает только role/content предыдущих
сообщений; текущий assistant turn вынесен в response; будущих сообщений нет.
Предыдущие реальные ответы, включая ошибочные, сохраняются.

Это **prefix/current-turn адаптация**, а не воспроизведение оригинальных метрик
CompliBench на полном разговоре. В исходной задаче иной scope нарушений и нет
реальных tool executions: успешное выполнение может описываться текстом. Guardian
может иначе оценивать materiality и достаточность подтверждения выполнения.
Не следует исправлять gold по ответам нашей модели или выдавать benchmark F1
за прогноз закрытой платформы. Такие расхождения разбираются отдельно.

**Разделение:** целиком по `domain + intent_name`; все workflow_index, варианты
мутаций и ходы одного семейства остаются вместе. В каждом домене одно семейство
зарезервировано под pilot, два под dev, семь под eval. SHA-based порядок фиксируется
seed `guardian-eval-family-v1-20261018`. Семейство airlines/loyalty_account_assistance,
на котором проверялся формат, принудительно оставлено в dev. Будущих результатов
модели при выборе состава не было. Это разделение intent-семейств внутри доменов,
а не независимые домены: общие condition-triggered policies переиспользуются.

Проверены точные совпадения модельных входов между основными разделами и с
историческими данными: пересечений нет. Проведён ограниченный аудит близких
диалогов: NFKC/casefold, числа маскируются, 5-словные shingles, точный Jaccard >=.85
для полных диалогов. Найдено 0 пар; при наличии таких пар builder объединяет
их семейства до split. Это не гарантия отсутствия всех семантических дублей.

**Особенность insurance:** исходный
[`selection_manifest.json`](https://github.com/UCSB-NLP-Chang/CompliBench/blob/593543022f67914e7ec9a312b7fa39c8a75e508a/data/insurance/selection_manifest.json)
прямо описывает предпочтение GPT-5-correct случаев; также есть model-based удаления.
Оба manifest сохранены в `upstream_audit`. Поэтому insurance анализируется отдельно
как дополнительный срез. Основной внешний срез airlines+healthcare содержит
**1136 eval-ходов / 14 семейств**, из них 359 положительных; insurance —
757 ходов / 7 семейств, из них 214 положительных. Общий результат всех трёх доменов
тоже показывается, с явным указанием upstream selection.

**Guardian-регрессии:** все 399 исходных строк прежнего MANIFEST найдены и сверены
по SHA; 397 имеют текущую gold-метку. Две ext_tau2 строки без gold занесены в
`EXCLUSIONS.json`, не превращены в NO. Gold читается из исторического revision
`403d811e79b388fbd11c209020e6ea76573e2564`; valid46 labels зафиксированы отдельно
с SHA исходного локального файла. Полные пути/хэши источников указаны в MANIFEST.
355 групп — proxy по точному prompt, а не подтверждённые task families.

**PolicyGuardBench:** скачан только официальный public test.json (12000 строк),
[Rakancorle1/PolicyGuardBench](https://huggingface.co/datasets/Rakancorle1/PolicyGuardBench),
revision `c7672703c1f27268300615afc0f78a845f5a342e`; dataset card заявляет Apache-2.0.
Отобраны 300 индексов фиксированным hash-порядком без чтения model results.
Gold относится к summary всей траектории. Поэтому он сохранён в отдельной схеме,
без преобразования в gold последнего хода и без участия в основном сравнении.

**Предложенный Opus τ³-bench:** проверен официальный
[sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench), revision
`96a3ef92329baf908ffe9dfe188cea34e8701d2a`. Его задачи/reward не дают автоматически
gold ошибки именно текущего хода. Сбор нового размеченного корпуса из этих задач
требует отдельной аннотации траекторий; он не объявлен выполненным. Новые платные
rollouts и большая синтетическая генерация не запускались. Исторические tau2
с уже имеющейся текущей разметкой включены в regression_seen.

## Проверки до GPU

Использованы локальные tokenizer.json/tokenizer_config.json/config.json текущих
весов Qwen3.6 AWQ, Transformers **5.8.0**; SHA файлов записаны в TOKEN_PREFLIGHT.
Активный parser импортирован из `Guardian-judge-open-review40-20261018/src`.
Общие caps как в текущем open profile: max_model_len 49152, maximum primary input
47096, hard input 49150, prepass output reserve 384. Это максимальный quality cap,
а не адаптивный тайминг-план production.

| Раздел | Максимум primary / prepass input tokens | Обрезано / policy обрезано | Ошибки prepass/final подготовки |
|---|---:|---:|---:|
| Compli pilot | 2368 / 2775 | 0 / 0 | 0 / 0 |
| Compli dev | 3036 / 3503 | 0 / 0 | 0 / 0 |
| Compli eval | 4948 / 5489 | 0 / 0 | 0 / 0 |
| Regression | 46261 / 47225 | 2 / 0 | 0 / 0 |
| Pilot32 | 46261 / 47225 | 2 / 0 | 0 / 0 |

Исходные CSV не сокращались: обрезка относится только к отдельному preflight
через существующий legacy renderer. В quality-run фактический сохранённый input
одной строки должен быть одинаковым для сравниваемых способов агрегации.
Обнаружено 10 mechanical hard на label-1 регрессиях и 0 на label-0; на Compli hard
не было. Это проверка wiring/доступности входов, не измерение модельного качества.
Реальные notes, доставка notes, exactness scoring, runtime и VRAM пока не измерены.

## Воспроизведение и запуск

Python stdlib + Git; downloads только public pinned data, менее 11 MB:

```powershell
python scripts/prepare_judge_eval_data_20261018.py --out A:/Guardian-submissions/judge-eval-data-rebuild --source-cache A:/Guardian-submissions/judge-eval-data-20261018/sources --download
python scripts/prepare_judge_eval_data_20261018.py --verify A:/Guardian-submissions/judge-eval-data-rebuild
```

Builder требует новый output-каталог и отказывается молча перезаписывать manifest.
Без `--download` используются только ранее проверенные source-cache файлы.

CPU token preflight в уже настроенном окружении, без загрузки модели:

```powershell
$env:PYTHONPATH = 'C:/Users/Igor/Guardian-judge-open-review40-20261018/src'
& 'A:/Guardian-submissions/cascade-build-20261011/u2-build-venv/Scripts/python.exe' scripts/preflight_judge_eval_data_20261018.py --data A:/Guardian-submissions/judge-eval-data-rebuild --tokenizer A:/Guardian-weights/qwen36-awq
python -m unittest tests.test_judge_eval_data tests.test_transcript tests.test_judge_transcript_integration -v
```

После распаковки на Linux, из подготовленного Git checkout, с фактическими путями:

```bash
export PYTHONPATH="$PWD/src"
python scripts/prepare_judge_eval_data_20261018.py --verify /data/guardian-judge-eval-data-v1
python scripts/eval_judge_valid.py \
  --input /data/guardian-judge-eval-data-v1/pilot32/inputs.csv \
  --labels-file /data/guardian-judge-eval-data-v1/pilot32/labels.jsonl \
  --config submission/JUDGE_OPEN_REVIEW40.json \
  --model /models/qwen36-awq --rates 0.30,0.40 --seconds 7200 \
  --out /runs/pilot32-open
```

7200 с — явно увеличенный deadline диагностического quality-пилота, не конкурсный
runtime. На меньшей GPU max_num_seqs/batched_tokens задаются отдельной копией
конфига и фиксируются в receipt; контекст не уменьшается ради размещения.
Никаких новых аренд/отправок эта подготовка не выполняет.

Оценки overall и final сохраняются одним прогоном для последующего сравнения
overall / MAX / final. Основная заранее выбранная пара: final .40 против MAX .40;
.30 и overall — диагностика. Final-only при техническом отказе не превращается в
модельное NO: нужны all-row результаты с объявленным fallback и отдельный
exact-intersection. Внешние benchmark и Guardian-регрессии не смешиваются в одну
«универсальную F1». GPU harness для этого полного сравнения и сами модельные
измерения — следующий этап; подготовка данных не считается их выполнением.

**Статус:** DATA_PREPARED / CPU_PREFLIGHT_PASSED / GPU_NOT_RUN.
