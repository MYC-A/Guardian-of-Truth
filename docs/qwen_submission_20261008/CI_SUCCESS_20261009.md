# Успешная CPU сборка runtime, 2026-10-09

Run: https://github.com/MYC-A/Guardian-of-Truth/actions/runs/37872100649
Runtime source commit: `6b1413f1064b58ccefef846a0a7050531354f139`.
GitHub conclusion: `success`. Два предыдущих отказа сохраняются как отдельная история.

Фактически выполнено:

- CUDA SM80 compile/link, RPATH audit, native library closure и pinned notice preflight.
- 50 Linux tests passed, включая POSIX signal ownership и реальный GCC linkage regression.
- Offline pip install, bundled native Python imports и public empty-input Parquet entrypoint.
- Полные valid46 raw replay для baseline179 и speed16-180 requests:0 mismatches.
- Те же два full46 replay внутри настоящего read-only Docker с отключённой сетью:
  все exact request identities и final binary/owner/accusations совпали.
- GitHub build attestation создана; bundle находится в artifact. Локальная
  криптографическая проверка этой подписи здесь не заявляется.

Граница проверки: native `llama-server --version` дал точную loader-ошибку
отсутствующего `libcuda.so.1`, сохранён статус `NOT_EXECUTED_MISSING_HOST_DRIVER`.
Stub не использовался для исполнения. GPU inference новой сборки: `NOT_EXECUTED`.
Replay не является новой оценкой Qwen, причиной обвинения по source или hidden F1.

Runtime:5947 files,1796501463bytes, manifest SHA256
`452841b4f55c27ee8904e4efdbd8efde1f90c85999a27061be508742a28f2add`.

Runtime tar:1155904194bytes, SHA256
`61bc6563c6f9068cd37c14efcd21fa8a6fb17b0ccba18faf0f461ec37b71d4c2`.

GitHub transport artifact:1157010908bytes, id11591208423, SHA256
`73a193fc779d24180d06a1a687a9e58450dc88f846e99e962950dc846d0e1db6`.

Дальше локальный supervisor скачивает transport, проверяет SHA/manifest и соединяет
его с настоящими проверенными весами на дискеA. Новая текущая phase:
`A:/Guardian-submissions/completion-6b1413f1/`. Финальный ZIP ещё не считается
готовым до `READY_VERIFIED_PACKAGING` и immutable packaging receipt.
