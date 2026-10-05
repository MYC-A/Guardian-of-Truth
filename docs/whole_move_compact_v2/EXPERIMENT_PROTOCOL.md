# Компактный whole-move контракт: отдельный follow-up

Первая богатая схема провалилась на всех6известных real cases:4ошибки literal
copy и2output truncations. Raw-ответы также содержат семантические ошибки;
исправление формата не доказывает правильность причин. Фазаv1 сохранена.

Новый общий интерфейс:

- Модель оценивает каждый native current target и даёт компактные source-ID
  ссылки, модальность, применимость, состояние условия, исключение и explanation.
  Код агрегирует ответы; пропуск/дубль/чужая цель отклоняются.
- Canonical citations, фактический native actor, исходный source text и hash
  формирует код. Модель не копирует эти метаданные. Ссылка доказывает только
  адресацию; смысл нормы/свидетельства остаётся MODEL_HYPOTHESIS.
- Prompt явно различает necessary/sufficient условия, qualified permission
  «may ... only if» и безусловное разрешение, source-defined persistence/expiry
  и взаимодействие всех действий хода. Новые бизнес-правила не добавляются.
- [bridge.py](../../experiments/whole_move_compact_v2/bridge.py) связывает
  исходный pack/resolve, admission и независимые generic required/type/enum
  проверки всех текущих calls. Положительная mechanical находка может дать
  ERROR при NO_ERROR/UNKNOWN/отклонении модели. Underlying stage сохраняется.
  Чистая schema не доказывает отсутствие нарушения бизнес-политики.

Это совместное изменение представления и общих семантических инструкций,
поэтому возможный прирост нельзя приписать только устранению copying.

## Замороженное сравнение

Используются все те же18входовv1:6известных valid +12author-controlled contrasts,
без отбора удачных строк по новым ответам. Это development follow-up после
наблюдения ошибокv1; внешним hidden holdout он не является.

Полные source packets совпадают сv1. Архивные BASELINE ответы переиспользуются
только при совпадении wire/model/protocol/raw hashes и повторном admission.
Новых baseline HTTP нет. Компактный variant использует тот же pinned model
`ministral-14b-2512`, temperature0 и cap3600.

План **18новых single-attempt HTTP, максимум140000tokens**, timeout120s.
Provider failure/unknown usage и model-ID mismatch останавливают новые вызовы;
повторов/смены модели нет. Ни исходный ввод, ни перечень current targets
не обрезаются. Context bound проверяется заранее. Output length явный failure.

До API фиксируются код, jobs, baseline cache, механические результаты,
evaluation sidecar, versions и оба protocol hashes. Parentv1 не перезаписывается.
Arms: BASELINE_CACHE, BASELINE_PLUS_MECHANICAL, COMPACT,
COMPACT_PLUS_MECHANICAL. Новый bridge общий и не содержит routing по бизнес-
именам или ID строк. Baseline mechanical overlay — code-only replay на тех же
положительных ограничениях, вычисленных ещё до первого API-прогона.

Причины анализируются независимо от бинарных совпадений. Подстановка code-owned
цитаты не делает модельное заключение формальным доказательством. Семантический
UNKNOWN и technical null преобразуются в0 и учитываются отдельно. Известные6
и authored12 отчёт разделяет; общего нового модельного F1 на46нет.
