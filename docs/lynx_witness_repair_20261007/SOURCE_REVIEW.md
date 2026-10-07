# Независимая проверка ошибок старого Lynx

Reviewer: отдельный агент `lynx_witness_review`, read-only review Git blobs 064b2152, исходных valid.parquet и delivered packets. Новых модельных вызовов при этом анализе не было. Runtime не получает перечисленные IDs.

Исходная диагностическая turn-проекция FAIL→ERROR на всех valid46: TP9 / FP2 / FN14 / TN21, precision .8182, recall .3913, F1 .5294. Все46 views неполные, но это не объяснение каждой ошибки.

| Случай | Воспроизводимое наблюдение | Какой уровень ошибается |
|---|---|---|
| banking_knowledge task057 t2, FP | Нормальный ответ клиенту отвергнут за то, что он не является пересказом документа; исходный запрос и auth policy присутствуют | QUESTION адаптера: «What does the document say?» вместо запроса клиента |
| airline3 t4, FP | User claim Gold предпочитается tool-result membership silver; decisive data доставлены | Authority/conflict resolution модели |
| banking task005 t6, FN | Поля email/address в БД принимаются за независимую проверку клиентом; доставлены wrong initial email, один правильный phone, отсутствие сообщённых DOB/address | Смешение наблюдаемого состояния и выполненной обязательной процедуры |
| retail27 t10, FN | Accusation проверка говорит, что нет evidence двух одновременных calls; current response содержит2calls, но отсутствует в её DOCUMENT | Отсутствие проверяемого текущего действия в accusation witness; одно-call policy уже доставлена |
| retail106 t3, FN | B2 reasoning описывает выдуманный zip как нарушение, затем инвертирует смысл accusation и выдаёт FAIL. A для сходного ядра получает PASS | Model polarity/task confusion; full-object parser правильно читает SCORE |

У retail36 подтверждены пропущенные исходные item IDs, однако часть decisive no-op proposal/current значений доставлена. Это observed omission, а не доказанная единственная причина FN.

Вывод: v4 изолированно исправляет witness (включение current action для accusation и full original input при token fit). Он специально сохраняет старый QUESTION. v5 отдельно проверяет исправление QUESTION. Ни один из этих адаптерных фиксов сам по себе не гарантирует правильную применимость политики, приоритет источников, процедуру подтверждения или polarity. Native PASS означает модельную оценку factual support, не certificate compliance.
