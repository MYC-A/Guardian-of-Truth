# Независимый code/source review

Отдельный read-only агент lynx_witness_review проверил old native Granite contract, archive/public46 source identity, новый runner, score decoder и комбинации с Qwen. Независимо запущены8 tests: passed.

До inference исправлены4 замечания: hashes полных original prompt/response (включая пропущенную середину); проверка revision/shard inventory/SHA256/size против pinned HfApi download metadata; precision/recall в отчёте; fingerprints imported helpers. Actual dtype сохраняется. Финальный reviewer не нашёл блокирующих дефектов.

Native groundedness polarity и4800/7200-character bounds воспроизводят историческую конфигурацию. Строгий decoder отклоняет multiple/conflicting/partial score вместо выбора последнего tag. Полный finite score на16-token cap пригоден; cap/eos_seen сохраняются отдельно. Interrupted STARTED attempt не повторяется, None не становится NO_ERROR. Публикация допускает только новый exact output root, locks/tmp исключены.

Это независимая проверка кода и исторических источников, не новая независимая разметка causes или доказательство качества на hidden test.
