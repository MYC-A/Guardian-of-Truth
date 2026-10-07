# Lynx: исправление witness и парные метрики

Дата 2026-10-07. Ветка `fix/guardian-lynx-witness-20261007`.
Протокол фиксируется **до новых inference**. Historical v3 raw/metrics не меняются.
Production/default не меняются. Никаких платных API или новых downloads.

## Исправляемая ошибка

При проверке accusation document не содержал текущего response, о котором
говорит accusation. Neutral prompt view к тому же неполон на всех valid46.
Это ограничение адаптера, не доказательство слабости модели. Отдельно old
native grounding всего current turn не является полным policy checker.

Native model-card prompt и полный object codec сохраняются. Модель уже скачана:
Lynx70B IQ4_XS, revision581017200918, llama.cpp b11459. Карта оригинальной модели:
https://huggingface.co/PatronusAI/Llama-3-Patronus-Lynx-70B-Instruct
(8000 tokens, преимущественно English, factual consistency task). Русские
источники не переводятся дополнительной моделью.

## Входы, controls и budget

Все **46** исходных valid inputs, неизменный gold23/23. Source inventory берётся
из immutable data root403d811e. IDs/labels/causes gold не входят в prompts.

- Current turn: saved native v3 vs новая source view. QUESTION, ANSWER и
  native prompt неизменны; меняется только DOCUMENT. Current response никогда
  не входит в document собственного turn check.
- Qwen B2: все14 сохранённых accusations, включая единственную FP строку.
  Три document arms: old neutral prompt; old + complete observed current
  response; new source witness + complete observed current response.
- Distill:12 сохранённых valid46 accusations (A7/B2 5). Old проверка берётся
  из исторического v3 receipt, текст проверяется против исходного run record.
  Два новых arms аналогичны. Исходный reviewer technical class сохраняется:
  accusation с INVALID_JSON primary не превращается в пригодный prediction.
  Нет отрицательных gold строк с Distill accusation; FP rejection там неизмерим.

Верхняя оценка:46 +14×3 +12×2 = **112 новых запросов**, max_calls150,
workers8, temperature0, output600, actual input+reserved output≤8000 tokens.
Worst-case token ceiling150×8000=1.2M. Max_retries0. Одно выполнение фазы,
без выбора удачного повтора и без автоматического расширения бюджета.
Все новые attempts и actual usage пишутся в отдельный durable ledger.
Transport preflight использует /apply-template + /tokenize native server.
Length-limited response не даёт verdict даже при parseable object.

## Witness

Сначала весь original prompt: если actual tokenizer подтверждает fit, сохранять
его целиком. Иначе exact addressed source windows из всего original index:
rarity-weighted lexical query по current response и accusation, соседние окна,
повышенный приоритет последнего USER. Это **retrieval**, не доказательство
семантической связи или отсутствия события. Source role сохраняется из parser;
непарсенные spans доступны как unknown/raw. Результат содержит полный complement
непрочитанных ranges. Детерминированный порядок, UTF-8, исходные fingerprints.

Current response для accusation передаётся отдельно с code-owned inventory:
actor/kind/tool/source span. Наличие attempt не доказывает success, а содержание
утверждения ассистента не становится независимым свидетельством истины.
Answer accusation никогда не добавляется в DOCUMENT как факт.

Если full не помещается, проверяются frozen budgets48k/36k/24k/16k/8k bytes,
каждый через native tokenizer. Нет fit → CONTEXT_NOT_FIT; ничего не режется
молча. FAIL на неполном witness имеет support_status UNRESOLVED_WITH_GAPS;
PASS — MODEL_SUPPORTED_WITH_GAPS. Даже полный PASS — модельная оценка support,
не code policy proof. Исходный native SCORE сохраняется отдельно для диагностики.

## Метрики и критерий решения

Для old/new current-turn score публиковать TP/FP/FN/TN, precision/recall/F1,
coverage, technical rows, assignment bounds по отсутствующим decisions,
paired flips и full/selected source coverage. Диагностическая binary projection
**FAIL→ERROR; PASS→NO_ERROR** фиксирована заранее, но не меняет родную задачу
Lynx. Новый full valid46 обязателен; неудобные строки не удалять.

Для Qwen accusation arms: PASS сохраняет baseline ERROR; FAIL удаляет его;
technical→no_solution на данной positive prediction. Отдельный явно названный
control сохраняет baseline при technical/неполном witness. Показывать baseline,
три raw-filter arms и три controls. Считать lost/recovered binary TPs/FPs.
Positive binary label не доказывает истинность проверяемой cause. Полный cause
gold здесь не имеется, соответствующую accuracy не придумывать.

Принятие **как дополнительного фильтра** возможно лишь при полном пригодном
покрытии, отсутствии потерянных TP и устранении FP относительно Qwen B2 на этом
diagnostic наборе; этого всё равно недостаточно для изменения production.
Если критерий не достигнут, сохранить исправление witness и оставить Lynx
shadow/off. Не расширять порог после результатов. Valid46 development;
никакого утверждения о blind/general transfer по этой фазе.

## Воспроизводимость и запуск

Один новый isolated server worktree, собственный finite supervisor service.
Не трогать чужой untracked compare_first_circle.py. Модельный server занимает
только свободный loopback8081, выключается после сохранения результата.
Новые paths: outputs/guardian_lynx_witness_20261007/.

Сначала tests и независимый code review, commit+push кода/протокола. Затем
`python -m experiments.guardian_local_a100.run_lynx_witness`; после расчёта
автоматические score, commit+push и remote SHA read-back. Старый общий queue
и его DONE остаются историей. Отказы по отдельным checks видны в row status.
