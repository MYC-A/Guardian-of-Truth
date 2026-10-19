# Экспериментальный ZIP смеси V4 — 19.10.2026

Архив собран и независимо проверен. По текущим измерениям предпочтение смеси
перед одной 35B не обосновано; это экспериментальный вариант по поручению пользователя.

- Файл: `guardian-judge-qwen36-v4-4b-blend40-fixes-2365fdc3-20261019.zip`.
- Локально: `A:/Guardian-submissions/guardian-judge-qwen36-v4-4b-blend40-fixes-2365fdc3-20261019.zip`.
- Размер: 38859030668 bytes, меньше 40000000000.
- SHA256: `89413e8624b4c858c60d845eb2f0229d27ef992b9f52ebdf7f147d73b0eab907`.
- Runtime source commit: `2365fdc3a9c0b2f294fada1eb7f78a798a1fb318`.
- Все 52654 файлов проверены сборщиком и отдельным verifier: bytes/SHA256/modes.
- Проверены shard indexes и payload bounds: 35B 95427 tensors, 4B 398, LoRA 504.
- Linux runtime и executable modes сохранены из исходного проверенного ZIP.
- Старый ZIP сохранён. Train/dev/gold/request caches в новый архив не добавлялись.

## Что запускается

35B AWQ с parser/mechanical fixes и отдельная Qwen4B с V4 LoRA, последовательно.
Ранги усредняются 50:50 только при полном N/N exact покрытии обеих моделей.
Квота .40, mechanical hard override; неполный auxiliary — глобальный fallback к 35B.
LoRA 4B не прикрепляется к 35B. Все веса находятся в ZIP; интернет не нужен.

## Качество и время

Свежий A6000 host-venv valid46: смесь TP17/FP1/FN6/TN22, F1 .8293;
контроль 35B с теми же fixes в том же прогоне TP18/FP0/FN5/TN23, F1 .8780.
Pipeline 696.77с, обе модели 46/46 exact, фактический rank_50_50.
Дополнительная стадия 4B на dev520: 520/520 exact за 197.65с при бюджете 240с.
Её scores со старыми 35B scores дали смеси F1 .6119 против .6289 у 35B;
это CPU replay, новая 35B на 520 повторно не запускалась.

Это GPU-проверка runtime-кода в host venv. Исполнение всего упакованного runtime
на GPU, полный private test и конкурсный A100 cold-start budget не подтверждены.
HUMAN_UNVERIFIED/EXPLORATORY сохраняется; архив не объявлен ACCEPT или приростом сабмита.

[Полный отчёт](V4_FINAL_RESULTS.md),
[проверка сборщика](v4_evidence/V4_BLEND_ARCHIVE_VERIFICATION.json),
[независимая проверка](v4_evidence/V4_BLEND_ARCHIVE_INSPECTION.json).
