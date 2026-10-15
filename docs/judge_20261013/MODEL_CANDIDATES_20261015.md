# Специализированные модели для Guardian: проверенный список на 15.10.2026

## Что проверено

Публичные карточки, configs, ревизии, каталоги файлов и ограниченные заголовки safetensors.
Компактная квитанция: [MODEL_CHECKS_20261015.json](MODEL_CHECKS_20261015.json).
Полные веса не скачивались, полный SHA256 не проверялся, GPU-инференс не выполнялся.
Качество Guardian, русскоязычный перенос и время полного прогона — GPU_UNTESTED.

Предыдущая версия этого русского отчета в de5651d8 была повреждена при записи.
Ниже восстановлено содержание с основными ограничениями. Сырые локальные карточки лежат в
A:/Guardian-submissions/cascade-build-20261011/model-search-20261015/.
Удаленному агенту следует проверять источники по ссылкам и закрепленным ревизиям.

## Три основных кандидата для будущих отдельных экспериментов

### 1. PolicyGuard-4B — соблюдение политики

- Модель: https://huggingface.co/Rakancorle1/PolicyGuard-4B .
- Ревизия: f9060bd92c6f7d70170e1c5239131b10027cf375 .
- Статья: https://arxiv.org/html/2510.03485v2 .
- Страница авторов: https://rakanwen.github.io/policyguard-page/ .
- Qwen3-4B-Instruct-2507, полное SFT, Qwen3ForCausalLM.
- BF16 weights: 8 044 981 992 байта в двух safetensors. training_args.bin не нужен.
- Около 60 тыс. пар политика–траектория из WebArena. Shopping, Shopping Admin, GitLab, Reddit, Map.
- Вход: политика и действия. Выход violation/no_violation.
- F1 0.8759 относится к PolicyGuardBench, не к Guardian.
- Apache-2.0 по карточке; nongated. Прочитан валидный BF16 header первого файла через HTTP 206.

Близка проверке SOP, условий, запретов и последовательности. Ограничения: английские
стандартизованные браузерные действия, не длинные русские tau-диалоги.
Ошибка где-либо в траектории, предсказание будущего нарушения по prefix и нарушение текущего
хода — разные задачи. Не переносить прошлую ошибку в текущую метку автоматически.
Нельзя без проверки заменить родные labels на YES/NO и считать режим эквивалентным.
Парсер из карточки ищет no_violation; иной формат ответа нельзя молча превращать в positive.

### 2. ToolHACE Qwen3.5-2B Span — достоверность текста после инструментов

- Модель: https://huggingface.co/s-nlp/ToolHACE_qwen3.5_2B_span .
- Ревизия: d9a2f314bda2a280c408ac6b88289f59791572cf .
- Статья: https://arxiv.org/html/2610.17125v1 .
- Код: https://github.com/s-nlp/Tool-Call-HD .
- Qwen3.5-2B, полное SFT на 37 135 примерах, одна эпоха.
- Qwen3_5ForConditionalGeneration, BF16 weights: 4 426 558 864 байта.
- Валидный публичный safetensors header: 617 tensors, 2 213 241 664 параметра.
- Вход: TOOLS, USER, TOOL_OUTPUT, ANSWER. JSON errors с классом и цитатой.
- В карточке response P 0.9820 / R 0.7705 / F1 0.8635 на pinned ToolHACE test.
  Это не Guardian F1. Карточка использует test 11 637 строк; в статье другая версия, 11 606.

Модель проверяет answer_mismatch, overgeneration, missing_tool, undergeneration.
Родной predict.py действительно ГЕНЕРИРУЕТ JSON: temperature=0, max_tokens=600, thinking disabled.
Это не готовый однотокенный binary judge. В wrapper TP=1; пример TP=2 не означает требование двух GPU.

Ограничения:

- Обучение английское, обычно один тип ошибки на строку.
- Штатный USER обрезается до 1 200 символов, TOOL_OUTPUT до 6 000, ANSWER до 4 000.
  Нельзя автоматически переносить эти срезы на Guardian.
- Отдельного поля полной политики нет; корректные по схеме, но запрещенные политикой действия
  не являются основной задачей checkpoint.
- Отсутствие факта в пакете не означает отсутствия факта в оригинальной истории.
- undergeneration recall 0.0423; неполнота ответа не всегда является нашей галлюцинацией.
- Генерируемые spans нужно проверять на дословное наличие в response.
- Лицензия fine-tuned checkpoint явно не указана в YAML карточки. Лицензия base сама по себе
  не устанавливает условия публикации дообученных весов.
- Версия Transformers при сохранении новее нашей. Регистрация архитектуры не доказывает
  успешную загрузку конкретного checkpoint в текущем runtime.

### 3. Pollux-4B-Judge — русский судья по заданному критерию

- Модель: https://huggingface.co/ai-forever/Pollux-4B-Judge .
- Ревизия: afc701120c7391789c12f03180b548a586448587 .
- Код: https://github.com/ai-forever/POLLUX .
- Qwen3ForCausalLM, BF16 weights: 8 044 982 080 байт.
- Проверен публичный header: 398 tensors, 4 022 468 096 параметров.
- Config max_position_embeddings=40960.
- Вход: инструкция, оцениваемый ответ, критерий, шкала, необязательный эталон.
- Обучена на русском, генерирует оценку и пояснение/рассуждение.
- Карточка приводит vLLM 0.19.0 и Transformers 5.3.0. У нас 0.19.1 и 5.8.0.
- MIT по карточке; nongated.

Заявленный macro F1 0.705 относится к классификации оценок POLLUX, не к binary hallucination F1.
Один критерий за запрос — основной режим. Несколько критериев одновременно авторы считают
вне intended use. Штатно это не один токен, требуется замер времени.
Не выдавать историю или политику за эталон правильного ответа.

В существующем guardian-judge-qwen36-awq-6540dc50UP1.zip проверена регистрация
Qwen3ForCausalLM и Qwen3_5ForConditionalGeneration. Архив не менялся.
Это проверка архитектур, не реального GPU запуска указанных моделей.

## Другие открытые кандидаты

### LettuceDetect v2 Qwen-2B

https://huggingface.co/KRLabsOrg/lettucedect-v2-qwen-2b
Ревизия 4511d95c6a5f24df1e810a097685d068208cb149.
BF16 weights 4 548 221 488 байт. LoRA SFT уже слита в Qwen3.5-2B; PEFT для инференса не нужен.
Возвращает JSON с ошибочными spans. Обучение включает tool-output, документы и agent-code.
В карточке tool-output example F1 0.907 на 617 примерах; это не Guardian.
Опубликована оценка на 14 языках, русского в языковой таблице нет.
Нет специального обучения на наших tau SOP. Кандидат к сравнению с ToolHACE, не доказанная замена.

### ToolRM Qwen3-4B

https://huggingface.co/RioLee/ToolRM-Gen-Qwen3-4B-Thinking-2507
https://github.com/lirenhao1997/ToolRM
Ревизия 44439f36eb4682c72435d30831eb41d4ca3e6bd9.
BF16 weights 8 822 894 504 байта, Qwen3ForCausalLM.
Критик использования инструментов по истории, схемам и ответам; есть pointwise prompt,
хотя основное обучение pairwise. Критерии штрафуют также избыточные вызовы и уточнения,
что шире определения ошибки Guardian. Thinking checkpoint; в примере max_tokens=8192.
Малый размер не доказывает прохождение дедлайна. CC-BY-NC-SA-4.0 по карточке.
Не путать с IBM ToolRM из arXiv:2509.11963: это другой проект и другие результаты.

### Agent Compass: есть LoRA на tau2, но другая целевая метка

https://huggingface.co/azlanmalikai/agent-compass-2b
Ревизия b99aa395e17c53f71104c88aa316089e179a0ee0.
Qwen3.5-2B-Base, LoRA r16 и отдельный head.pt, custom kev runtime.
v1 содержит 3 000 обучающих tau2 states и оценку на 3 832 held-out states.
p_success — итоговый успех задачи; stuck/progress — зацикливание/прогресс.
Не использовать 1-p_success как вероятность галлюцинации текущего ответа.

### HalluGuard

https://huggingface.co/lrsbrgrn/HalluGuard-Qwen3-4B
Ревизия 2bf3858f8bd0c22b0c410f6b0c855098727a2554.
Около 8.045 GB. LoRA + ORPO уже объединены, Qwen3ForCausalLM.
Проверка документ–утверждение с тремя классами и обоснованием. RAG-постановка,
а не соблюдение агентной политики; thinking mode. ToolHACE/LettuceDetect ближе к tool context.

## Проверенные по наличию, но менее подходящие адаптеры

- Jarvis710/agentjudge-v2: Qwen3-8B QLoRA. В карточке общий verdict слабый,
  kappa около нуля; tool_selection correlation -0.067. Красивые dimension scores не равны
  надежной binary метке.
- Edric2412/Qwen3-8B-Hallucination-Detector-LoRA: HaluEval, английский, question–answer,
  три класса включая UNCERTAIN; нет полноценной нашей политики/истории.
- williyam/hallucination-detector-agent-qwen3-0.6b: GRPO LoRA r16, source–passage,
  простые синтетические задачи. Перенос на длинные SOP не установлен.
- Aditi20/tool-guardrail-qwen3-0.6b-lora: вредоносные команды/prompt injection coding agents;
  другая метка.
- talha1234567/Agentic-Ai, AgentSight: DeBERTa + LoRA и context encoder, AgentHallu,
  512 tokens на шаг, custom .pth. Judgment macro F1 0.547 на маленьком тесте.
  Это локализация/детекция в другой постановке, не проверенная замена нашего judge.

## Дополнительные русскоязычные варианты

- AtesiT/qwen2.5-1.5b-ru-hallucination-detector:
  5b889a87add5bebff02aa34babad2caf067677db.
  Русская QLoRA слита, SberQuAD с автоматическими порчами. Карточка ограничивает вход
  512 токенами, ручной проверки разметки нет. F1 0.9833 на 485 примерах не переносится на наши диалоги.
- Feudor2/hallucination_bin_detector_v5.0:
  0137de8694efa5a61a4a6827675bc635d57bd435.
  YandexGPT-5-Lite-8B, LlamaForCausalLM, context 32768.
  Карточка не документирует prompt, данные и F1. Возможная связь с RusHallu-RAG
  не подтверждена одним совпадением архитектуры/автора.

## Статьи и карточки без подтвержденного публичного checkpoint

- ToolCritic arXiv:2510.17052: статья найдена, опубликованные веса в просмотренных источниках
  не установлены. Отсутствие результата по имени не доказывает отсутствие всех зеркал.
- HDM-4B-RL: статья найдена, прямые открытые веса не установлены.
- PolicyGuard KAIST arXiv:2606.29225, https://policyguard.github.io/:
  другая работа с code release forthcoming. Не путать с открытой UC Davis PolicyGuard-4B.
- etomoscow/tool-calling-hallucination-modernbert-large-crf-best:
  карточка/дерево видны, прямой config вернул 401, LFS SHA скрыт. Публичный доступ к весам
  не подтвержден. s-nlp CRF checkpoint в README прямо обозначен private.
- ssurface/tool-calling-hallucination-modernbert-base-unified-final:
  публичный encoder около 598 MB, 8k config, английский. Не CausalLM YES/NO judge.
  Заголовок vLLM в карточке сам по себе не доказывает поддержку token classification.
- NVFP4-варианты JEV/decider не считать готовыми для A100 без проверки backend.

## Что делать с этими находками

Это резерв на отдельные эксперименты. Текущая реализация по AGENT_HANDOFF_20261015.md
сохраняет Qwen3.6 AWQ и проверяет U2, без дополнительных model calls.
При будущем сравнении: родные input/output contracts, одинаковые строки, отсутствие gold leakage,
анализ русского языка/политик, токенов и cold-start runtime. Не объединять произвольным OR
и не усреднять несопоставимые scores без независимой проверки.

Модельные метрики выше принадлежат авторам и разным бенчмаркам.
Заголовок safetensors подтверждает доступ к части реального файла, не весь download/SHA256.
CPU/CI и регистрация архитектуры не подтверждают качество или скорость на A100.
