# Live подготовка и замеры — 2026-10-10

Новый сервер пользователя: свободная A100-SXM4-80GB, driver580.173.02,
CUDA12.8.93, Ubuntu24.04/GLIBC2.39, Python3.12.3. Старый сервер не используется.
Исходный runtime код зафиксирован на `8911b35f`; decoder f498f864f/build11459.

Модель28 595 763 648bytes загружена **прямо с Hugging Face на сервер**;
revision71bc7b627595dc8a91039addd9c791ae548d6747, SHA256
aab65c67ef0dad127960efef9247f1832bca105faa1c7a052cc039b223cf86a1 подтверждён.
С ПК переданы только52 600 725bytes готового native engine, без весов;
tar SHA3f748999b9e59269768fc81350a4526bacafcc57d87c5d4510b3ccdd4f606771.
Из GitHub получен отдельный sparse checkout; Python dependencies pinned по
PINNED_VENDOR_FILES.json. Пользовательские secrets/env не опубликованы.

## Исправления подготовки, не результаты модели

Windows OpenSSH через инструмент зависал после первого вывода; Paramiko4.0.0
с проверкой существующего known_hosts дал нормальный bounded transport.
Распаковка один раз началась раньше завершения SFTP upload и упала EOF; добавлена
проверка полного размера/SHA native tar. При первом serving preflight неверно
размещён native root: ожидается `<root>/runtime/llama`, model — `<root>/model`.
Layout исправлен, failed probe directory сохранён отдельно. Это не prediction
failures; веса не менялись. Setup READY/model verification и downstream job
failure учитываются отдельно; статус FAILED в download_progress первого operator
не означает несовпадение SHA весов.

Один curl stream заменён4 strict Range streams с сохранением скачанного prefix.
Каждый проверяет206/Content-Range; готовый файл принимается только по full SHA.
После переключения скорость оказалась около33MB/s суммарно, не4x: сетевой лимит
остаётся. Переданный archive не пересобирается; system CUDA/driver не менялись.

## Замеры serving до valid inference

74 contract/recovery tests passed на сервере. Синтетические serving probes:
4 одновременных запросов, по256 generated tokens,8slots×32768, CPUthreads8.
Cold initialization и batch wall отдельно. Default aggregate82.06tokens/s;
explicit FlashAttention83.95tokens/s, около2.3% выше. Threshold принятия flag
до valid был10%, поэтому обе matched full arms используют **default**, не FAon.
Это короткий throughput probe на примерно490 input tokens/request, не измерение
полного B2 valid46 или40k-token workloads. Per-request decode около27tok/s при
4 активных запросах нельзя объявлять скоростью8-slot production.

CPU threads ограничены по quota/affinity до8 через LLAMA_ARG_THREADS,
LLAMA_ARG_THREADS_BATCH и OMP_NUM_THREADS; это общий serving профиль обеих arms.
Profile freeze записан до valid outputs. Никакие настройки не меняются в середине
legacy/compact сравнения.

## Запущенные фазы

1. Full valid46 legacy, затем compact, отдельные cold model processes,
   fresh in-memory inference caches. Same source/Q8/decoder/context/workers/recovery;
   разница только заявленный pre profile. Считаются full output, TP/FP/FN/F1,
   pre delivery/schema failures, raw/default recovery, tokens и wall.
2. После COMPLETE первой фазы, последовательно N0/RF full valid46. Оба R_fix-only
   без blind и F/S/P, одинаковая обвязка восстановления и serving. RF — faithful
   lexical reading-aid implementation `c290c178`, module SHA
   d4f7fbf2a54ae2a778fc7b97e90adbe8c115850859e9e6e2f4b85a89ec6ea9f6.
   Нет S1 quote-as-proof и нет retry monkeypatch из run_fast. Измерять RF против
   N0; сравнение скорости с B2 смешивает удаление стадий и эффект retrieval.
   Historical splitter теряет короткие/длинные qualified excerpts; full ordinary
   packet сохраняется, focus не certificate. English CUE bias не language parity.

RF не является semantic embedding/LSH: Counter TF-IDF cosine по word/chargrams,
без hashing/MinHash/index. Независимый reviewer это проверил по Git source.
Один полный repetition каждой пары — screening, не acceptance или hidden proof.
Нового независимого holdout пока нет. Source/gold/old raw outputs не редактируются.

Operator snapshots: `scripts/qwen_gpu_pilot_20261010/`. Supervisor держит jobs;
новый benchmark не занимает GPU до complete marker первого. Model servers
только localhost, их lifecycle принадлежит каждому запуску. Management services
Vast не изменены. Данные/логи сохраняются в `/workspace/guardian/pilot_20261010/`;
после завершения receipts выгружаются и scores проверяются локально.

## Уже проверенная граница контекста

В двух исходных archived valid46 B2 max reviewer input10 292/10 598tokens;
с completion budget1700 —11 992/12 298. Лимит8192 отклонил бы32/34 из46
reviewer requests. N0 может иметь другой профиль; его8k предположение не
переносится на B2. Для compact и других стадий использовать actual tokenizer
counts всего полного matrix. Текущая фаза32k остаётся неизменной.

## Следующий inference эксперимент

После текущих полных фаз: unchanged Q8 baseline vs `ngram-mod`, затем matching
MTP/DFlash по доступному бюджету. Pinned f498 имеет recurrent checkpoint/rollback
и target-sampler/grammar verification. Искусственный synthetic acceptance
запрещён в quality runs. Математический target sampling contract не гарантирует
bitwise одинаковых GPU outputs при иной batch/float geometry; нужны flips и
actual drafted/accepted counters, failures и whole cold wall.16rows — screening.
Q4_K_M и vLLM/AWQ — отдельные model/runtime variants, без обещания1.5x или прежнего
качества. Prefix cache/continuous batching уже существуют; проверить actual
hit/recompute на hybrid engine, не считать включение флага устранением всего prefill.

Primary references: [speculative docs](https://github.com/ggml-org/llama.cpp/blob/f498f864fbc0472004ee1c3616c1188c68eb157f/docs/speculative.md),
[server implementation](https://github.com/ggml-org/llama.cpp/blob/f498f864fbc0472004ee1c3616c1188c68eb157f/tools/server/server-context.cpp),
[target sampling](https://github.com/ggml-org/llama.cpp/blob/f498f864fbc0472004ee1c3616c1188c68eb157f/common/sampling.cpp),
[matching draft files](https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF/tree/71bc7b627595dc8a91039addd9c791ae548d6747).

Контроль legacy rep1 завершён; независимый пересчёт и промежуточные метрики:
[LIVE_RESULTS.md](LIVE_RESULTS.md). Остальные arms продолжаются; финального
paired verdict и принятия compact по этим данным пока нет.
