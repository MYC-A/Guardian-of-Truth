# Независимый code review основного ответа

Review выполнен субагентом `/root/archive_review` read-only по исходному логу,
коду public CLI/PrimaryReviewHook, production parser и контрастным fixtures.
Разметку или живые новые ответы модели reviewer не создавал.

Подтверждены и исправлены:

1. Диагностика повторного admission могла выводить содержимое validation error.
   Теперь выводятся категории, а raw transport detail/reply остаются в receipts.
2. Python whitespace normalization допускала NBSP/form-feed в JSON prefix.
   Допускается только JSON whitespace: space, tab, CR, LF.
3. Дубликат nested key мог скрыться в незавершённом объекте.
   Prefix scanner проверяет уже завершённые member names по каждому объекту,
   не смешивая равные keys разных объектов массива.
4. Первоначальная partial projection выполнялась только live, а shared
   finalize_trace повторно превращал её в technical null. Теперь одна функция
   заново извлекает решение из actual receipt и declared contract; cached binary
   и cached partial label не являются источником истины.
5. Исторический replay не обозначал reason-last control явно. Теперь
   contract/retry policy задаются флагами и включены в report.

После исправлений reviewer не обнаружил оставшихся блокирующих ошибок в проверенном
prefix/projection механизме. Его selected tests:66 passed,2 POSIX skipped.
Основной агент проверил более широкий selected set:71 passed,2 skipped,
а packaging verifier/archive отдельно:21 passed.

Это code review, не доказательство качества новой генерации.
Default не повторяет reviewer; восстановленный partial label не является
подтверждённой причиной. Для пустого ответа, отсутствующего enum, transport
failure или непройденного admission полного JSON гарантии результата нет.
Новый decision-first F1 и full-run time требуют новых GPU receipts.
