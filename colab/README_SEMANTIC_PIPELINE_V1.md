# Semantic Pipeline V1 — Google Colab quickstart

Use a **GPU** runtime (the verified target is Colab Free with Tesla T4). The setup script keeps Colab's stock PyTorch/CUDA stack and aborts if pip proposes replacing it.

## COLAB START

Cell 1:

```python
!git clone -b semantic-pipeline-v1 https://github.com/MYC-A/Guardian-of-Truth.git
%cd Guardian-of-Truth
!bash scripts/setup_colab_semantic_v1.sh
```

Cell 2 (the key is read without echo and is never put in a shell command):

```python
import os
from getpass import getpass

os.environ["MISTRAL_API_KEY"] = getpass("Mistral API key: ")
```

Cell 3 — choose paths:

```python
TEST_DIR = "/content/guardian_tests"
OUTPUT_DIR = "/content/guardian_outputs"
```

For Google Drive instead:

```python
from google.colab import drive
drive.mount("/content/drive")

TEST_DIR = "/content/drive/MyDrive/guardian/tests"
OUTPUT_DIR = "/content/drive/MyDrive/guardian/outputs"
```

Cell 4 — run the default A5 pipeline safely through `subprocess` (no fragile notebook shell interpolation):

```python
import subprocess

subprocess.run([
    "python", "scripts/run_semantic_pipeline_v1.py",
    "--input-dir", TEST_DIR,
    "--output-dir", OUTPUT_DIR,
    "--semantic-frontend", "v1",
    "--ablation", "A5",
    "--resume",
], check=True)
```

Input files are discovered recursively and may be `.jsonl`, `.json`, `.csv`, or `.parquet`. Every row needs `id`, `prompt`, and `response`; `label` is optional and crosses the gold firewall only after prediction.

To preload/verify the large checkpoints one at a time before the run:

```python
subprocess.run(["python", "scripts/preload_semantic_models_v1.py"], check=True)
```

For one-case debugging, append `--case-id`, followed by the exact ID. Readable artifacts appear under `OUTPUT_DIR/traces/<safe_case_id>/`. An interrupted command can be run again unchanged: `--resume` reuses content-addressed stage caches and completed cases.

The legacy frontend remains available with `--semantic-frontend current`. Optional layers use `--enable-gliner` and `--enable-langextract`; both are off in A5.
