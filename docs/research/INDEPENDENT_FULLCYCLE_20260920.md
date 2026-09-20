# Independent fullcycle line — access setup checkpoint (2026-09-20)

Branch: `research/independent-fullcycle-20260920` (base = `research/offline-20260919` @ `1755838`).
Agent: Super Z (independent full-cycle research line per directive 2026-09-20).

## Completed access setup

1. **Guardian Gateway 2.0 (ModelScope A10 server)** — all five smoke checks PASS:
   - `GET /health` → 200, `version 2.0`.
   - `GET /gpu` → `success=true, exit_code=0`, NVIDIA A10, 23 GiB VRAM, CUDA 12.4, no foreign GPU processes.
   - `GET /environment` → Python 3.11.11 (`/mnt/data/guardian/venv`), torch 2.9.1+cu128, `torch.cuda.is_available()=True`.
   - File roundtrip: PUT+GET `gateway_smoke.py` byte-identical (relative paths only; absolute paths rejected with 400).
   - Real GPU job: `SUCCEEDED, exit_code=0`, remote hostname `dsw-537551-56fdf888f9-dpqk5`,
     `CUDA: True`, `GPU: NVIDIA A10`, marker `GUARDIAN_GATEWAY_TEST_OK`.
   - TLS pinned by SHA256 fingerprint (mismatch → abort); `verify=False`/`curl -k` never used.
   - Note: `/jobs/{id}/logs` returns a single `{"stream", "content"}` object per call;
     client `guardian_client.py` merges stdout/stderr. `POST /jobs` HTTP 200 ≠ job success:
     always check `status` + `exit_code`.
2. **Persistent local access config** at `/home/z/my-project/guardian-access/` (mode 700):
   `token` (600), `server.crt`, `github_token` (600), `guardian_client.py`, `README.md`.
   Client covers health/gpu/environment/files/jobs + `wait_job`/`run_python` helpers;
   job_id-based status checking; no token in logs or remote URLs.
3. **GitHub**: repo reachable anonymously from server (clone/fetch); push done from local
   machine via credential helper (token never in remote URL, never committed).
4. **Keyless LLM APIs** smoke-tested OK (temperature 0): BlockRun.ai (`served nvidia/llama-3.2-11b-vision`),
   LLM7.io (`served codestral-latest`), Pollinations (`openai-fast` = gpt-oss-20b).
   Role: independent second/third opinion channels for theory building / critique / repair.

## Server inventory (read-only, no foreign worktree touched)

- Root `/mnt/data/guardian/`: `agent-workspace/` (mine), `results/` (B0/B3/B17 Codex artifacts),
  `models/` (granite-guardian-3.3-8b 16G; mistral-7b-instruct-v0.3), `hf_cache/hub` 14G
  (validated: BAAI/bge-m3, bge-reranker-v2-m3, cross-encoder/nli-deberta-v3-base,
  numind/NuExtract3-W4A16, fastino/gliner2.5-multi-v1, langextract), `venv/` (clingo 5.8.2,
  gliner, langextract, transformers 5.16.1), `gliner2_env/`, freeze-requirements.
- Foreign worktrees (DO NOT MODIFY): `Guardian-of-Truth-Offline-20260919`,
  `Guardian-research-a-83bbbb2`, `Guardian-research-b-f51f6fd`,
  `Guardian-research-d4baa86`, `Guardian-research-offline-20260920`.
  Global git safe.directory intentionally NOT added (shared environment).
- My isolated clone: `/mnt/data/guardian/agent-workspace/guardian-repo`,
  branch `research/independent-fullcycle-20260920`, local git identity set.

## Verified historical state (from docs/research of base branch)

- Offline baseline `--backend none` @ `923bb445`: public46 TP12 FP0 FN11 TN23, F1 .685714, 0.395 s CPU.
- Mistral direct BASE (public46, `ministral-14b-latest`, checkout `d4baa86`): TP20 FP10 FN3 TN13, F1 .7547.
- A0 structured judge: TP22 FP16 FN1 F1 .7213 (high recall, too many FP).
- A1 exact-grounding gate: 120/120 suspicions UNANCHORED → F1 0 (gate sound, producer broken).
- Historical combos (not comparable as ranking): R1 OR (Mistral AND GG-2B) F1 .824;
  legacy OR Granite F1 .722; closure-off C3 F1 .231; N5 replay F1 .276→.231 after sound lowering;
  exact-binding replay F1 0 (all inadmissible neural bindings).
- B0–B3 five-case real pilot: 0 representable rules through strict gate, all UNRESOLVED;
  NuExtract repair calls returned empty (B3 negative pilot); raw responses retained.
- superz/Full line (`research/superz-20260920`, synth32): C1 union TP7 FP0 F1 .609;
  C2m one-sided criticism destroyed union gains; A0-mistral direct judge F1 .889 > C1.

## Confirmed key constraints

- public46 = PUBLIC_SEEN dev set; no per-case rules, no thresholds tuned on it.
- Formal channel: `PROVED_ERROR` / `PROVED_NO_ERROR` / `UNRESOLVED` / `INCONSISTENT` stay
  separate from any probabilistic contest decision; no closed-catalog or
  `additionalProperties=false` premises without explicit source backing.
- Final submission must be offline (`scripts/predict.py --input … --output …`),
  ~30 min, <40 GB; no remote-Mistral dependency in the final path.
- Full benchmark runs on the server require separate user approval (server instruction §8).

## Next steps (proposed, in order)

1. Reuse sealed provider cache + variant CLI from base line; reproduce baseline on server clone.
2. Repair A1 grounding producer (114 offset mismatches) on frozen smoke cases; then A1 rerun.
3. Two generative critics for B (per directive §7.5: NuExtract stays extractor only);
   keyless APIs as independent critic candidates vs Mistral-side criticism.
4. Targeted small balanced slices before any full public46 rerun; per-case diff vs baseline.

## 2026-09-20 — Этап A выполнен: baseline воспроизведён на сервере

- Серверный клон (guardian-repo @ ad52ac7) синхронизирован, пакет установлен в venv.
- Offline baseline на public46: **TP12 FP0 FN11 TN23, F1 0.6857** — точное совпадение с задокументированным (artifacts: outputs/baseline_ifc/).
- ОСНОВНАЯ ИНФРАСТРУКТУРНАЯ НАХОДКА: /mnt/data/guardian/secrets/ недоступен для job-процессов (drwx------ root), MISTRAL_API_KEY в env отсутствует → Mistral-канал недоступен с сервера. Все IFC-раннеры строятся provider-agnostic (OpenAI-compatible): BlockRun (пул gpt-oss-120b, ~0.6s), Pollinations (gpt-oss-20b, ~15s), LLM7 (10 RPM) — проверены с сервера; Mistral подключается при появлении доступа без изменения кода.
- GPU свободен (A10, 0 MiB). Далее: направление A (s1/s2/s3 подозрения с grounding-repair-циклом), E3 Granite full46 параллельно.
