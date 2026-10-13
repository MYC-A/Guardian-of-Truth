"""Use platform Python/Torch/vLLM plus the pinned small compatibility overlay."""
import os
from pathlib import Path
import sys

def main():
    root=Path(__file__).resolve().parents[1]
    overlay=root/'compat/site-packages'
    if not overlay.is_dir():raise RuntimeError('COMPATIBILITY_OVERLAY_MISSING')
    sys.path[:0]=[str(overlay),str(root/'src'),str(root)]
    os.environ.update(PYTHONPATH=os.pathsep.join([str(overlay),str(root/'src'),str(root)]),
        PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',
        TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_XET='1',PYTHONUTF8='1')
    from scripts.qwen35_b2_runner import main as run
    run()

if __name__=='__main__':main()
