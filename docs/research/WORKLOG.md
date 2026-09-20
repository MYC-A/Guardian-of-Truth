# Research Journal — agentz (Super Z), ветка research/agentz-20260920

Формат: гипотеза → конфигурация → результат → решение. Все числа — на моих зафиксированных данных; public46 = PUBLIC_SEEN (только диагностика).

## Окружение и ограничения (зафиксировано 2026-09-20)
- Песочница: 2 CPU, 3.9 GB RAM, БЕЗ GPU, БЕЗ SSH → сервер ModelScope недоступен из этого окружения (подключение только с машины пользователя; manual/connect_server.md выполнен быть не может).
- LLM-канал: z-ai-web-dev-sdk = GLM API (замена Mistral API; явно помечено: НЕ локальная модель, воспроизведение на локальной модели не гарантируется — по директиве п.9).
- Установлено: clingo 5.8.2, torch 2.14.0+cpu, transformers 5.17.0, lettucedetect, minicheck, langextract (+ собственный Ollama-шим → GLM).
- Granite Guardian (2B/8B): NOT_RUN — память песочницы 3.9GB < требуемых ~5-16GB. Честно зафиксировано, лёгкая альтернатива — GLM-judge + MiniCheck/LettuceDetect.
- Rust-митинг процессов: фоновые процессы убиваются между вызовами инструмента → шим LangExtract запускается в потоке процесса (in-process), все LLM-вызовы кэшируются sha256(system|prompt) в experiments/agentz_arch_v1/cache/.

## Датасеты
1. public46 (valid.parquet) — PUBLIC_SEEN, только диагностика. Мой парсер таймлайна: 276 пар call/response, все спаны roundtrip-верны.
2. synth_pairs.json — МОИ контролируемые пары (сгенерированы детерминированно, до любых прогонов): 10 категорий × EN/RU × 4 вариации × {bad,ok} = 160; dev=120, holdout=40 (стратифицированный сплит зафиксирован до настройки). Категории: stale_value, wrong_entity, attempted_done, exception_missed, threshold_direct, fabricated_value, actor_confusion, missing_arg, permission_done, temporal_skip.
3. AgentHallu dev-адаптация из benchmarks/agenthallu_v1 (ветка Codex; read-only, помечено как possibly-seen).

## Компоненты (реализовано и протестировано)
- timeline.py: ⟦SYSTEM/USER/ASSISTANT⟧ + →TOOL_CALL/←TOOL_RESPONSE, JSON-парсинг, span-точность 46/46.
- asp_lower.py: RuleIR-lite → ASP + Clingo. Регрессия 9/9 семантических кейсов: prohibition(+exception action_present/flag, порог), obligation(precondition), requirement(+exception), soundness: unknown flag → UNRESOLVED, action_absent без closure_premise → UNRESOLVED. Найдено и исправлено: (1) cmp unsafe variables; (2) стёртые flag_true_e; (3) requirement-нарушение игнорировало исключения; (4) prohibition не проверял условия применимости.
- spans.py: exact/normalized/fuzzy анкоринг цитат (на public46 A1: 92% подозрений анкорятся, 4/48 unanchored).
- langextract_runner.py: настоящий цикл LangExtract (промптинг, парсинг, difflib-выравнивание офсетов) над GLM API через Ollama-шим. Smoke: 3/3 извлечения с точными спанами на RU-политике.

## Эксперименты (GLM API, public46 = PUBLIC_SEEN)
| Вариант | Датасет | TP/FP/FN/TN | P | R | F1 |
|---|---|---|---|---|---|
| A0 прямой judge | public46 | 16/4/7/18 | .800 | .696 | **.744** |
| A1 цитаты | public46 | 19/14/4/9 | .576 | .826 | .679 |
| B1=A1 | public46 | =A1 | | | .679 |
| B2 механика | public46 | 19/13/4/10 | .594 | .826 | .691 |
| A0 | synth-dev (частично) | 2/0/2/3 | 1.0 | .5 | .667 (n=8) |

A1 (принудительные цитаты): recall .696→.826 (+.13), но FP 4→14 — моделивание «дать основание» усиливает обвинительную тенденцию. Это главный кандидат на лечение через B3-перекрёстную проверку.
B2 (детерминированный stale-fact + entity-чек): снял только 1 FP на public46 — механический канал работает (пример: refuted_stale), но judge-FP в основном другой природы (нужен B3).

## Локальные детекторы (CPU, без API)
| Детектор | Стратегия | Датасет | Порог | P | R | F1 |
|---|---|---|---|---|---|---|
| MiniCheck-RoBERTa-L | truncate | synth-dev | .5 | .52 | 1.0 | .686 |
| MiniCheck-RoBERTa-L | truncate | synth-dev | .3 (tuned dev) | .60 | .87 | **.708** |
| MiniCheck-RoBERTa-L | relevant(BM25-ish) | synth-dev | swept | .48 | .92 | .632 |
| MiniCheck EN-подвыборка | truncate | synth-dev | .3 | .64 | .90 | .750 |
| MiniCheck RU-подвыборка | truncate | synth-dev | .3 | .56 | .83 | **.667** |
| LettuceDetect (EN ModernBERT) | smoke | synth 8 | .5 conf | ловит stale-value span (conf .97), ~23s/чанк на 2-core CPU |

Выводы: (1) трюкация контекста у MiniCheck → поток FP (по директиве подтверждено); (2) max-агрегация по чанкам усугубляет FP (директива подтверждена: any-chunk-unsupported → обвинение); (3) RU-поддержка RoBERTa-версии слабее EN на ~8 F1-пунктов; (4) LettuceDetect — EN-only (kornw01-европейская версия удалена с HF; есть KRLabsOrg EN ModernBERT), RU неприменим напрямую.

## Ключевые наблюдения по архитектурам
1. Формальный канал (C) корректно ловит exception_missed (PROVED_ERROR с witness на bad-близнеце, NO_ERROR на ok-близнеце после фикса requirement-exceptions) — но качество теории LLM нестабильно: parse failures под троттлингом, мусорные правила (R1 "requirement refund" — выдуманное требование) → нужен C3-критик.
2. ASP-слой честно UNRESOLVED на claim-ошибках (stale_value, fabricated_value) — это зона каналов B/D, гибрид E обязателен.
3. Soundness соблюдён: ни одного false NO_ERROR в 9 кейсах регрессии; unrepresentable → UNRESOLVED, не stricter.

## Открытые вопросы / дальше
- B3 (LLM-перекрёстная проверка оснований) — код готов, ожидает API-квоту.
- C0/C1/C3 полные прогоны на synth-dev + public46; C5 divergence-отчёт.
- D (гипотезная формализация) — код готов.
- E-селекторы — код готов.
- synth-holdout (40) — трогать только после freeze конфигураций.
- AgentHallu прогон (объектив: переносимость на реальные траектории).
