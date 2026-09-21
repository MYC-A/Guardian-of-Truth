# big_researh — план исследований (2026-09-22)

Directive: BIG_RESEARH (AI Journey Contest 2026, Guardian of Truth).
Приоритет: реальные эксперименты и сохранённые результаты, не инфраструктура.

## База и обоснование выбора

- Рабочая ветка: **`big_researh`** (обязательное написание). База — `253bcd0`
  = `full_21/hybrid-research` (`4b073bc`) + preservation commit
  (незакоммиченное состояние предыдущего агента: S6 langextract runner + частичные
  records, mini mistral OpenAI server, think-v2, helper-скрипты, snapshot корня
  workspace из 143 файлов).
- Ветка сохранения: `big_researh-recovered-full21` (sha 253bcd0). Переименована из
  `big_researh/recovered-full21`: git механически не допускает одновременное
  существование `refs/heads/big_researh` и `refs/heads/big_researh/*`; приоритет —
  точное имя рабочей ветки из директивы. SHA и история не изменялись.
- Также опубликованы без изменений: `full_21/hybrid-research` (4b073bc),
  `full_21/archive-previous` (4b158e8).
- Почему эта база: рабочий конкурсный CLI (offline Guardian), структурный
  Guardian, побайтово воспроизведённый контроль (baseline OR old granite 8B,
  F1 .8889, 46/46 per-case согласование), runner режимов Granite (s3), графовый
  дайджест + абляции контекста (s5), claim-level verifier (s7), LangExtract S6
  (частично), NuExtract3/GLiNER2/BGE/NLI в кэше сервера, public46 label-free
  input, eval-протокол и per-case артефакты.

## Замороженный контроль (не подлежит подстройке под public46)

- Input: `outputs/full21/input/public46_label_free.csv`
  sha256 `9f6f5fc496d25e80a008adb589ddcb30fb681d0da131fb83c37fc220c5089e93`.
- Model: `/mnt/data/guardian/models/granite-guardian-3.3-8b-b3421eda`
  (ibm-granite/granite-guardian-3.3-8b).
- Config: criterion `groundedness`, think=false, max_context_chars=12000
  (head_tail_per_field), max_new_tokens=16, temperature 0, transformers backend.
- Контрольные метрики: granite standalone TP16 FP2 FN7 TN21 F1 .7805;
  **baseline OR granite TP20 FP2 FN3 TN21 F1 .8889**.
- Gold join только post-hoc; пропущенный/нетокенный случай остаётся missing,
  не 0. public46 — диагностический PUBLIC_SEEN набор, не holdout.

## Доступ к LLM (зафиксировано)

- Mistral API: файл `/mnt/data/guardian/secrets/mistral.env` существует
  (подтверждено предыдущими агентами через SSH-канал), но санкционированный
  канал исполнения (Guardian Gateway jobs, пользователь guardianagent) не может
  его читать: permission denied, root:root 0700. Симптом зафиксирован, секрет
  не раскрывается. Классификация: API-канал недоступен через текущий gateway.
- LLM-канал для LangExtract/Q/orchestrator: локальная
  `mistral-7b-instruct-v0.3` (уже скачана предыдущим агентом,
  `/mnt/data/guardian/agent-workspace/superz_models/mistral-7b-instruct-v0.3`,
  14G; подаётся через `experiments/full21/mini_openai_server.py` на
  127.0.0.1:8002/v1). Это не новая загрузка и не замена API «ради замены» —
  это использование уже существующего серверного ресурса при заблокированном
  API-канале, с зафиксированным симптомом.

## Этап I — доработка исследований со старой Granite (до Gate)

- I.A Контроль/режимы/бюджеты контекста — ЗАВЕРШЕНО предыдущей серией:
  s3 (6k/12k/24k/60k; answer_relevance .7442; evasiveness P=1.0 R=.1739;
  context_relevance неадекватен; think v1/v2 — честный негатив),
  s5 (граф-дайджест как judge-контекст — честный негатив, 21 FP),
  s7 (claim-verifier — recall-насыщение, слабый дискриминатор).
- I.B **S6 LangExtract — доделать**: resumable прогон на оставшихся кейсах
  public46 (records.jsonl уже содержит реальные span-verified извлечения),
  метрики coverage/span_ok/new_vs_graph по классам и доменам.
- I.C **NuExtract3-W4A16 — структурное извлечение** tool JSON и policy-условий;
  абляция G+N.
- I.D **Clingo/RuleIR — формальная проверка** по проверенным предпосылкам
  (clingo 5.8.2 в venv готов; RuleIR/symbolic binding из superz_fullcycle).
- I.E **P (предусловия) и Q (различающие вопросы)** — полноценные end-to-end
  прогоны, не только smoke.
- Абляции: G; G+L; G+N; G+L+N; verifier±evidence. Метрики: F1, coverage
  фактов, entity binding, missed exceptions, hallucinated obligations,
  technical failures, changed-decision count.

## Gate — Granite 4/4.1 (только после завершения Этапа I)

Найти официальный компактный checkpoint (не 30B): назначение, chat template,
risk modes, лицензия, VRAM ≤ 23GB, совместимость с A10. Smoke → сравнение на
единых входах/режимах/бюджетах с old granite. Решение по качеству на
независимых данных + стоимость + совместимость, не по новизне.

## Этап II — детерминированная маршрутизация проверок

Минимальный router без управляющей LLM: тип обязательства + доступные
источники → инструменты + основание + бюджет. Главный detector всегда остаётся
контрольным каналом. Метрика routing recall отдельно от F1.

## Этап III — агент-расследователь

Реестр обязательств/гипотез; оркестратор (локальная mistral) выбирает
проверочный вопрос и инструмент; evidence-controller валидирует provenance
независимо от оркестратора; итоговый aggregator различает подтверждение
основания и метку по ответу. Гипотеза III.B: поиск контрпримера к собственному
выводу. Бюджет: 3–6 шагов на подозрение, лимит токенов/времени, кэш по
input hash+model+prompt.

## Правила честного сравнения (фиксированы до прогонов)

- Per-case артефакты: git SHA, dataset hash, фактическая модель, prompt, режим,
  бюджет, raw outputs, TP/FP/FN/TN, coverage/failure rate, время/затраты.
- Неполные прогоны сравниваются только на общем подмножестве + отдельно
  coverage. Пропущенный случай ≠ метка 0.
- Никакого выбора архитектуры по лучшему F1 на public46 с объявлением его
  независимым результатом. Новые policy/независимый holdout — отдельно.
- Отрицательные результаты сохраняются как результаты.
