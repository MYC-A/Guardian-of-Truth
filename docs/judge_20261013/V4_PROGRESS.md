# V4 — текущее состояние 19.10.2026

Это продолжение поручения: исправления + новые данные + fresh-base LoRA + сравнение.
E2 завершён, опубликован отдельно в V3_E2_RESULTS.md. Здесь нет заявленного прироста
на закрытом тесте и нет нового готового ZIP. Новая LoRA пока не обучена.

## Уже проверено

- Native reference replay: airline50, retail99 полных и15 с ошибкой источника,
  telecom2285 полных задач. Ошибка reference не превращается в корректную метку.
- Новый natural pilot:4B12/12 за409.2с,8B12/12 за167.5с; суммарно682с с загрузками.
  24 траектории дали54 консервативно размеченных хода,8 положительных;145 текущих
  неоднозначных целей исключены. Это не54 независимые задачи. Максимальный
  prompt в генерации20191 токен, длина будущих обучающих входов ещё пересчитывается.
- Обнаружено отсутствие заголовка текущего ассистента в прежнем synthetic renderer.
  V4 исправляет формат; старые данные/измерения не переписываются.
- Подключён opt-in `bounded_turn_shape` к evaluator/submission supervisor, default false.
  В интегрированном CPU evaluator на397:101 hard-positive строк всего,0 hard на gold0;
  на dev520:0 hard.96 shape-findings на397 — это число находок, не отдельных строк.
  Исследовательский S2 ранее дал94 distinct shape строк на397,88 на real191,6 на valid46.
  На dev520 shape не снимает основную проблему ложных обвинений.
- Регрессии:44 passed,1 skipped (до последующих изменений добавляются адресные проверки).

## Работающие процессы

Сервер209.137.198.14:18293, только свои supervisor programs:

- `guardian-lab-v4-natural-expanded-r1`: конечный сбор4B затем8B,48 задач/seed-вариантов
  на модель; timeout7800с. Собственные model servers останавливаются между моделями.
  `/workspace/guardian-lab-20261018/v4-20261019/natural-series-expanded-v1`.
- `guardian-lab-v4-contrasts-v1`: CPU constructed-native contrasts, до180 исходных
  контекстов на домен, pool-cap160 до финального template-cap60; timeout2400с.
  `/workspace/guardian-lab-20261018/v4-20261019/contrasts-full-v1`.
  Protected entity preflight включён; полноценная деконтаминация ещё впереди.

Новый training protocol зафиксирован до обучения: V4_TRAINING_PROTOCOL.md.
До optimizer: окончить источники, source-audit, protected/old-holdout decontamination,
TRAIN-only lineage для legacy, freeze, измерить10 длинных forward/backward без updates.
Старое overnight-расписание выключено и к этой серии не относится.

## Локальные артефакты

`A:/Guardian-submissions/guardian-v4-20261019/`:

- `reference-all-v1.tar.gz`, SHA256
  `b1c2c5d8d207bbe16a4a47d1cc7aa1550b07458746479038b58c2a0ed7929f9f`;
- `natural-4b-pilot-v2.tar.gz`, SHA256
  `8d02af458ad320e72b648a11387ab2e0b563b043f0b7c7906b1e164d8a54607a`;
- `natural-8b-pilot-v2.tar.gz`, SHA256
  `0c7e428993031a35aac51bc19aca5f67379ab0e33f72bed2c85b3802e2c0e941`;
- `natural-pilot-json-v2/INDEX.json`: исходные tar member names -> Windows-safe filenames
  и SHA256. Неудачная прямая распаковка сохранена; tar проверен, исходные имена
  с `|`/`:` не были перенесены в Windows как пути;
- `natural-labels-pilot-v2/`, source-checked draft, ещё не TRAIN;
- `shape-integrated-seen397-v1/`, `shape-integrated-dev520-v1/`, opt-in config отдельно.

Human review недоступен, статуса ACCEPT нет. Новые данные не добираются дубликатами
и переименованиями ID. Число прошедших source/components/caps строк будет опубликовано
до обучения. Ошибки и исключённые строки сохраняются.
