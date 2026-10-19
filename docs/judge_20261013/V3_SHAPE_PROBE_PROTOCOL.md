# S: проверка структурных потерь без изменения production

19.10.2026, после вопроса пользователя о V6, до подсчёта новых shape-метрик.
Причина на восьми real191 TP_LOST установлена по текущему коду: парсер видит
четыре mixed-text/call и один multiple-call, но добавляет weak/hints, не hard.
Тест test_several_calls_are_a_hint_not_a_label прямо закрепляет этот дизайн.
V6/v6fix не импортируется текущими judge_stage/submission/mechanical.

CPU-only исследование, исходные labels/scores/ZIP остаются неизменными.
Не подключать всю старую V6-систему и не добавлять LLM-вызовы для этого подсчёта.
Из source-only входа извлечь уже существующие weak-признаки
text_and_calls_against_policy/several_calls_against_policy и сохранить факты.
На seen397/real191/valid46 оценить ДИАГНОСТИЧЕСКИ:
S_quota: эти flags добавлены к hard и расходуют прежнюю .40 quota;
S_OR: flags добавлены после прежнего решения, без заполнения/удаления других
положительных. Показать оба для current35B и фиксированной M3, не выбирать
вариант по наилучшему F1. Показать TP gained/lost и FP removed/added, flagged
label0 IDs, исходные policy/turn hashes. Это проверка потенциала, не ACCEPT.

До вывода о безопасном hard gate проверить production-parser-compatible
контрпримеры: разрешено несколько вызовов; подтверждённый пользователь при
условном запрете; исключение для read-only; цитата старого запрета; запрет
только в user message; mixed text без запрета; plain unconditional positive.
Raw weak flags не считаются доказательством применимости даже при нуле FP
на397. Их нынешний regex ищет подстроки, не разрешает scope/exception/quotation.
Обязательные условия будущей интеграции: authoritative source, применимый
запрет с разрешёнными условиями/исключениями, правильный текущий assistant turn,
не считать текст tool-result сообщением пользователю. UNKNOWN сохраняет прежнее
решение. Изменять production и acceptance-протокол по этим метрикам запрещено.
