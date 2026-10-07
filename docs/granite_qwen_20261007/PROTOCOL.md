# Granite3.3 native reproduction + Qwen

Пользователь попросил попробовать Granite и затем связку с Qwen. Отдельная research ветка, никаких paid API/default/production изменений. Полные valid46, одна быстрая реплика. Изученный development набор не объявляется blind holdout.

Модель ibm-granite/granite-guardian-3.3-8b, revision b3421eda4ba6fc9f9a71121d7e62de08827469a4, исходные BF16 safetensors, Transformers. Исторический native contract: assistant=bounded response, documents=[prompt_context=bounded prompt], guardian_config criteria_id=groundedness, think=False, tokenize=False/add_generation_prompt=True. Затем tokenization add_special_tokens=False. Никакой подмены native judge обычным JSON chat-reviewer.

Используется старый bound_pair:12000 **символов**, prompt4800/response7200, exact head/tail и explicit omission marker. Это сознательно усечённый historical control, не full input и не доказательство absence. Все bounds/raw requests сохраняются. Более длинный контекст — другой эксперимент, сейчас его нет.

Greedy generation, max_new_tokens16 как в архиве. yes=ungrounded/error1, no=0. Полный единственный score tag с optional EMPTY think и terminal EOS принимается; несколько tags, незавершённый tag, лишний текст — INVALID_NATIVE_SCORE. Архивные46 replies имеют завершённый score при16 generated tokens; достижение cap само по себе не делает законченный finite contract невалидным. Сохранять generated IDs, raw text, eos_seen и cap flag. Не увеличивать лимит задним числом. Actual input+16 проверяется по checkpoint context limit, без нового silent clipping.

Ровно46 возможных native inference attempts, durable STARTED/FINISHED ledger. Interrupted attempt не повторяется молча, binary=None. Timeout1200/job. No retries/no calibration/no judge calls. До inference code/protocol commit+push, hashes, freeze input jobs; после — raw, stage status, score, commit+push/read-back.

Архив Granite и Qwen B2 совпадают по46IDs/gold. Исторический label-free CSV точно равен valid.parquet по prompt/response. Уже offline измерено: Granite16TP/2FP/7FN F1.7805; Qwen13TP/1FP/10FN F1.7027; Qwen OR archived Granite20TP/2FP/3FN F1.8889. Это смешанный исторический diagnostic, не новый парный inference. Fresh Granite сравнить с архивом построчно; fresh OR/AND c тем же frozen Qwen считать отдельно. Qwen technical missing не превращать в0. OR сохраняет1 при другом unknown, AND сохраняет0; прочие неизвестные остаютсяNone с sensitivity bounds.

Основные метрики binary TP/FP/FN/TN/P/R/F1, technical coverage, fresh-vs-archive flips, paired newTP/newFP over Qwen, tokens/time/VRAM. Native groundedness не гарантирует policy applicability или правильную причину. Cause accuracy не измеряется без source adjudication. OR может сохранять FP; default не менять даже при совпадении archival.8889.

Источник native contract: https://huggingface.co/ibm-granite/granite-guardian-3.3-8b и docs/full21/CONTROL.md. Historical runner/gold/outputs не переписываются. Модель скачивается отдельно без inference; если места мало, можно удалить только завершённые собственные Lynx weights после подтверждённого push raw результатов, сохранив weight fingerprint. Download/setup receipt пишется отдельно. Inference только после отдельного code review.
