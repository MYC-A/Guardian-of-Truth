# Проверка speed/guardian-fast-20261010

Проверенный снимок: `8bab353c`. Вывод: **полезная исследовательская ветка,
но готового ускоренного Qwen-решения и сопоставимого доказательства его качества нет**.
Runtime и production не менялись; новых HTTP/model/SSH вызовов нет.

## Что подтверждено

- После исключения старого L-варианта просмотрены1888 опубликованных строк
  современных local runs: binary==binary_rfix, owner==owner_rfix. Ни одного flip.
  Число1908 из FAST_RESULTS.md не воспроизводится по опубликованному снимку;
  нужен manifest точного множества. У старого L действительно8 flips, но это иной
  executor, поэтому он не опровергает результат современных F/S/P.
- В архивном Qwen valid46 AM без pre-pass:9TP/0FP/14FN/23TN,F1 .5625.
  B2 с blind pre-pass:13TP/1FP/10FN/22TN,F1 .7027. Single runs,development.
  Это противоречит переносу отрицательного результата API Ministral на Qwen.
- В Qwen B2 valid46 layer_trace содержит92 упоминания запросов, но64 уникальных
  key:policy extraction переиспользуется. Эти64 requests дают9424 completion
  tokens; pre-pass66401, R_fix38141. Удаление слоя убирает примерно8.3% выходных
  токенов этого архива, а не пропорционально «два вызова из четырёх».
- В том же Qwen архиве14/46 pre-passes действительно отброшены после генерации
  по byte cap. Избежать такой работы полезно; число17 из нового API эксперимента
  независимо не проверено.
- Prompt-only neutral view у Hook3 сохраняет blindness. MODEL_HYPOTHESIS и
  требование поддержки original packet сохранены. Новых business/tool/benchmark-ID
  правил в добавленных файлах не обнаружено.

## Ошибки и ограничения

| Где | Что проверено | Почему важно |
|---|---|---|
| hook_fast.py quote gate | quote_q2 принимает удалённое NOT; ref не проверяется, поиск по policy+declarations+history, затем ref удаляется | Утверждение «machine-verified verbatim» неверно. Есть только слабое совпадение текста, без источника/роли/условий |
| hook_fast.py HEADROOM |4000-byte резерв при отсутствии maxLength у string fields | Это heuristic, не доказательство, что injected output вместится. Наследуемый post-call fallback остаётся нужен |
| hook_fast.py view | neutral_view receipt/coverage теряются после удачного получения user | Не видно not-read gaps именно pre-pass; entity/computed propositions тоже не проверяются кодом |
| score_fast.py | missing IDs не проверяются, error/None исключаются, duplicates считаются повторно | Denominator и F1 могут искажаться. Это несовместимо с полным output/fallback0 контрактом |
| run_fast.py freeze | shared freeze_phase не хэширует experiments/guardian_fast; config не содержит review_max_tokens/backend/endpoint | Resume может смешивать разные prompts/бюджеты. Сами transport cache keys endpoint включают — это отдельная граница |
| run_fast.py retry | global monkeypatch transport.post с8 скрытыми HTTP retries | Ledger видит одну попытку и только последнее latency; backoff и предыдущие calls теряются. Repeated429 не останавливает profile |
| postverify.py | REFUTED может пройти без подтверждённых цитат; narrow witness сохраняет прежние ограничения | Потеря TP не доказывает бесполезность verifier вообще. Такое REFUTED — model hypothesis |
| postverify.py strict | nonempty pool может сохранить1 независимо от SUPPORTED | Латентная ошибка формулы. При обычном base_error раннем return pool отсутствует, поэтому влияние на опубликованные числа не доказано |
| submission | В новой ветке нет src/guardian_truth/submission | Это research runner, не новый конкурсный ZIP. Наша обработка отказов и fallback0 сюда не интегрированы |

Scorer probes:
missing positive без записи вообще исчезает из n и bad; explicit failed positive
учитывается какbad, но исключается изFN; duplicate successfulpositive учитывается
какдополнительныйTP. Полнота, retries и уникальность должны проверяться до scoring.

Новые `outputs/guardian_fast` raw receipts **не опубликованы в Git**. FAST_RESULTS
содержит только таблицу; самостоятельно пересчитать новые API F1, failures,
calls/tokens и сравнение причин пока невозможно. Времени A100/Qwen нет даже в
заявленных результатах: эксперименты выполнялись на Mistral API через endpoint
override. «Разницы меньше .05 — noise» не следует из одного повторённого примера.

## Что имеет смысл делать

1. Первой проверить Qwen **B2 без F-extraction**, сохранив blind pre-pass и
   прежний reviewer. Архивный replay поддерживает абляцию; live GPU выигрыш
   времени и перенос на новые rows ещё требуется измерить.
2. Сократить duplicate source payload, сохранив original source addresses,
   scope/coverage и необходимые witness spans. Compact quoted proposal полезен
   как hypothesis, но Q2 не должен называться точной source verification.
3. Исправить scorer/full expected set/retry ledger/freeze и опубликовать raw
   результаты. Для broken rows использовать согласованный explicit fallback0
   без exclusions; причины unvalidated классификаций хранить отдельно.
4. Прогнать кандидатов на одном Qwen/model/context/backend с равными настройками
   и несколькими repeats. Старые valid46/LB/tau2 здесь diagnostic, не новый blind test.

Решение: **сохранить идеи и код как exploratory; не переносить N0 default из
API Ministral на Qwen и не заменять текущий submission ZIP этой веткой**.
Независимый subagent review подтвердил fuzzy/polarity/ref и postverify границы;
основной агент проверил Git outputs, metric accounting, freeze и runtime path.
