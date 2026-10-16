# Encoder retrieval A/B, 2026-10-16

[Отчёт и ограничения](../../docs/judge_20261013/ENCODER_AB_20261016.md).

CPU-only сравнение обычного U2 и того же U2 с настоящим локальным MiniLM. Нужны Torch
2.10.0, Transformers 5.8.0 и pandas с поддержкой Parquet, а также заранее скачанный
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` ревизии
`e8f8c211226b894fcb81acc59f3b34ba3efd5f42`. Скрипты используют offline-загрузчик текущего judge
и явно добавляют `src` этого checkout в путь импортов. Нужны исходные столбцы valid:
`id`, `prompt`, `response`, `label`, `explanation`. Метки и объяснения используются только
в последующей инспекции, не в поиске.

Из корня репозитория, с Python указанного окружения:

```powershell
python experiments/encoder_ab_20261016/compare_retrieval.py --input valid.parquet --encoder-dir A:/Guardian-weights/u2-minilm-e8f8c211 --output A:/Guardian-submissions/encoder-ab-repeat
python experiments/encoder_ab_20261016/probe_encoder.py --input valid.parquet --encoder-dir A:/Guardian-weights/u2-minilm-e8f8c211 --output A:/Guardian-submissions/encoder-ab-repeat/encoder-diagnostics.json
```

Сравнение по умолчанию читает `submission/JUDGE_CONFIG.json`, меняет `context_mode` только
в памяти эксперимента на `u2_dense`. Чтобы прочитать точную конфигурацию из собранного ZIP,
добавьте `--source-zip A:/Guardian-submissions/guardian-judge-qwen36-awq-u2dense-5c4c82af.zip`.
Альтернативный JSON-конфиг задаётся `--config`. Для повтора выберите новую папку: существующие
результаты не перезаписываются. Веса Qwen, GPU и сеть этим скриптам не нужны.

`compare_retrieval.py` сначала запускает dense с холодным прикладным кэшем и бюджетами
из конфигурации (в опубликованном эксперименте 5/300 секунд), затем lexical. Сохраняются
полные исходные цитаты и пакеты, времена, причины fallback, различия выбранных единиц и
хэш данных. Инициализация энкодера измеряется отдельно. Сохранение полных диагностических
пакетов входит во время проходов; это не время инференса Qwen.

`probe_encoder.py` проверяет несколько небольших многоязычных примеров, поведение на
разных ID и отрицаниях, одинаковость векторов при различии за пределами первых двух окон,
а также число запросов из проверяемых ответов, чей хвост не помещается в окна.
Это диагностические примеры, не оценка точности и не новый независимый validation set.

В `results/` опубликованы компактные JSON-результаты исходного полного прогона 46 строк.
Полные транскрипты и подробные пакеты не дублируются в Git. Наличие источника не означает,
что Qwen правильно применит правило; отсутствие цитаты не доказывает отсутствие информации
в исходном диалоге. Прирост F1 не измерен. Изменений production-кода и упаковки в этом
эксперименте нет.
