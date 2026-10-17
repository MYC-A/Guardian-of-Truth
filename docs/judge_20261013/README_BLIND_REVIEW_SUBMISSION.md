# Guardian-of-Truth — Qwen3.6 AWQ blind review, 17.10.2026

Полный Linux submission: веса, offline runtime, scripts/predict.py и полный бинарный output.

```bash
python scripts/predict.py --input /path/test.parquet --output /path/predictions.parquet
```

Вход CSV/Parquet: id,prompt,response; выход id,label в исходном порядке, включая повторные id.
Точка входа запускает встроенный Python через runtime/python/run_python.sh.
Модель cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit,
revision 00fcea2d3bcf5389b518d4fc082e5590e0ba4844, каталог model/judge.
Python 3.12.3, vLLM 0.19.1, Torch 2.10.0+cu128, Triton 3.6.0, Transformers 5.8.0.
Сеть не требуется. Не устанавливать/обновлять пакеты поверх встроенного runtime.

В этом архиве явно включён профиль D: legacy, overall@on → один blind → final,
одна загрузка модели. Резервный overall durable; final использует сохранённый фактический
primary context без дополнительного сокращения ради notes. Непоместившиеся notes
отбрасываются; непоместившийся checklist получает явную ошибку строки.
Если хотя бы одного exact final не хватает, весь рейтинг остаётся primary.
Hard override и квота .30 сохранены. Все входные строки получают бинарную метку;
технический fallback отдельно отмечается в логах и не считается модельным NO.

Лимиты от запуска predict.py: stop=1380 с, kill=1530 с, watchdog=1680 с.
Внешний лимит платформы 1800 с включает установку/холодный старт, и не подтверждён
одними CPU-тестами. Архив не запускает обучение, сервер HTTP или платные API.

Статус: CPU/структура проверены; GPU_UNTESTED. Прирост F1, blind delivery и runtime
на A100/закрытых данных не измерены. Упаковка полного ZIP не является доказательством
превосходства над overall или готовности пройти весь конкурсный вход по времени.
MANIFEST.json/JUDGE_MANIFEST.json содержат хэши runtime, кода, конфигурации и весов.
SHA исходников и подробная внешняя verification-квитанция выдаются рядом с архивом.
