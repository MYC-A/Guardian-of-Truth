# Частичный приём справок: три final-replay — 18.10.2026

**Доставка улучшилась, устойчивый прирост F1 не подтверждён. Production promotion
не выполнен.** Три пересчёта520 строк используют одни замороженные генерации;
это не1560 независимых задач и не три полных генеративных повтора.

| Final, квота .40 | Повтор1 | Повтор2 | Повтор3 |
|---|---:|---:|---:|
| Без справки | .583569 | .583569 | .577904 |
| Строгий приём всей справки | .628895 | .640227 | .645892 |
| Частичный приём валидных checks | .640227 | .645892 | .645892 |
| ΔF1 partial−strict | +.011331 | +.005666 | .000000 |

Во всех трёх partial−strict95% grouped CI включает0:
[-.010589,.031082], [-.004342,.014059], [-.010132,.010695].
Доставка strict392/520 (75.38%), partial460/520 (88.46%) во всех повторах.
68 ранее отклонённых документов содержат106 пригодных по структуре/ссылкам checks.
Строгие VALID notes не изменены; JSON со статусом TRUNCATED не восстанавливался.

На dev520 со строгими справками F1 выше, чем без справок, во всех трёх повторах.
Это положительный локальный сигнал; только6 семейств, данные использованы для
разработки. Основной внешний срез airlines+healthcare и insurance приведены
отдельно в per-run analyses. Нет доказательства переноса на конкурс или Guardian397.

## Повторяемость

Все1560 пар (arm,key) имеют идентичные input SHA и token SHA между тремя runs.
В каждом run получены все1560 свежих exact final scores: всего4680. Generation
не выполнялась заново. Точная нормализация YES/NO не означает побитовую устойчивость.

Максимальные расхождения log-odds относительно повтора1:

| Arm | Повтор2 | Повтор3 |
|---|---:|---:|
| no_notes | 1.500122 | 1.625073 |
| strict | 1.499704 | 1.624653 |
| partial | 1.999621 | 1.499964 |

При этом strict F1 меняется от .628895 до .645892, что больше максимального
наблюдаемого выигрыша partial над strict в отдельном повторе. Это не доказывает,
что весь эффект partial вызван шумом, но не позволяет выделить его как надёжную
доработку. Причина конкретного численного разброса не установлена; обвинять один
kernel, APC или quantization без отдельной проверки нельзя.

AUC/AP, .30, confusion matrices, fixes/breaks, per-domain results и runtime:
[общая JSON-сводка](NOTE_ADMISSION_REPLAY_RESULTS_20261018.json) и
[per-run analyses](evidence_a6000_20261018/). Выбор лучшего повтора или нового
порога не выполнялся. Dataset и generated notes повторно не считаются независимыми.

## Проверки и свидетельства

- Перед GPU verified stage-input file hash, actual durable primary row hash,
  сохранённые source/rendered/token hashes, прежние strict parse results и
  все520 прежних strict final inputs/delivery. Контракт row hash отличается от
  u2_context hash; initial replay preflight остановился до GPU, исправлен и
  покрыт regression test.
- Strict/partial/no_notes используют одинаковые source/checklist, batch16,
  engine/config/weights, hard input cap и exact scorer. Arm order ротируется по
  batch, APC включён. Это не чистый throughput benchmark между arms.
- 25 целевых тестов проходят на Windows и Linux; stdout/exit/version receipts
  сохранены. Production strict parser не менялся; partial отдельно в research module.
- Полный архив всех3 replay, prompts, scores, logs/VRAM и Linux test receipts
  скопирован off-box в `A:/Guardian-submissions/judge-gpu-a6000-20261018/`:
  `note-replay-series-receipts.tar.gz`, SHA256
  `8deb91b28ef1246af30d9a676242648d97c5640357b8f0fc7a0d6f35e5e8ce19`.
- Компактные4680 score receipts без текстов исходников находятся в
  `evidence_a6000_20261018/replay-exact-scores.jsonl.gz`.

Итог: техническая доработка работоспособна и повышает доставку, однако крупного
или устойчивого quality gain не показала. Следующая архитектурная гипотеза о
раздельном выборе применимого правила/проверке условий остаётся NOT_TESTED.
