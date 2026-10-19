# Экспериментальная сборка 35B + V4 LoRA и исправления — 19.10.2026

Пользователь явно поручил собрать ZIP смеси с исправлениями после сообщения
о смешанных результатах. Это отдельное разрешение собрать экспериментальный
кандидат поверх прежнего условия «не собирать без подтверждённого переноса».
Оно не превращает HUMAN_UNVERIFIED/quality/time gates в пройденные и не разрешает
автоматически отправлять архив на платформу. Исходный ZIP и production defaults сохраняются.

## Фиксированное поведение

- Current35B: закреплённая Qwen3.6-35B-A3B AWQ, overall/open answer audit/final,
  MAX доступных точных overall/final. Citation contract explicit; legacy context.
- Второй scorer: Qwen3-4B-Instruct-2507 cdbee75f17c01a7cc42f958dc650907174af0554,
  исходная BF16 база + неизменённый V4 adapter SHA4b06ca6a…0b14477, rank16/alpha32.
  Native vLLM LoRA; полный исходник без дополнительных hints, прежний prompt/template.
  Политика/история/текущий ответ не нормализуются по новому synthetic renderer.
- Два GPU worker последовательно:4B→35B; группа процессов4B убирается до35B.
  Одна GPU, без одновременного размещения двух engine и без result cache.
- При N/N точном покрытии обеих моделей: среднее percentile midranks50:50,
  затем квота .40 с одинаковым hard override. Полнота проверяется по позиции,
  не по ID: повторяющиеся ID допустимы. Частичный auxiliary не даёт смешанной шкалы:
  глобальный fallback на имеющийся35B score. Режим явно пишется в BLEND_DONE.
- Включены исправления парсера, source-bound date-gate и bounded_turn_shape.
  Неоднозначность/исключение не даёт нового обязательного обвинения. Hard может
  превысить квоту, как в существующем решении. Ранговые веса/квота не выбираются
  по valid46 или новым промежуточным метрикам.
- Время от entrypoint:4B до240с, stop1560с, kill1680с, watchdog1740с;
  внешний лимит1800с. Учитываются загрузки обоих engine. Пропуск4B не считается
  успешным исполнением смеси. Сохранённый35B/mechanical output остаётся доступным.

## До окончательной выдачи

1. CPU: midrank ties, изменение решения, hard-over-quota, auxiliary missing/
   duplicate/inexact/torn receipts, gold isolation, literal/duplicate/Unicode IDs,
   adapter на реальных вызовах интерфейса и exact YES/NO контракт, archive closure.
2. GPU после освобождения текущим frozen reference: production wrapper на valid46,
   оба scorer46/46 exact, фактический rank_50_50, выход id/label и whole-pipeline time.
   Одинаковый свежий35B с исправлениями — парный контроль внутри того же запуска.
   Это ограниченный regression run на A6000/host venv, не полный private/cold-start A100.
3. База4B скачивается по закреплённому public manifest; сверяются bytes и
   SHA256/git blob SHA1 каждого файла. Adapter сверяется с TRAINED receipt.
   Основная35B сверяется с моделью неизменённого проверенного source ZIP.
4. Сохранить прежний Linux runtime/loader/права. Все исходники — из release commit.
   ZIP <40000000000bytes, каждый member проверен по размеру/SHA/mode, независимый
   полный SHA архива, tensor shard indexes и полный набор базовых/adapter весов.
   Никаких train/dev/gold/request caches в runtime archive.
5. Отчёт должен содержать как положительные, так и отрицательные результаты.
   До измеренного выигрыша на платформе кандидат не объявляется улучшением сабмита.

## Известные результаты до сборки

Фиксированная смесь без нового shape по сохранённым scores: seen397 .7413 против
35B .7512; real191 .6544 против .6452; valid46 .8293 против .8293;
dev520 .6176 против .6289. Это EXPLORATORY и не основание обещать конкурсный рост.
Новые hints/native LoRA backend и включённые механические fixes измеряются отдельно.
