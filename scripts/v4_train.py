"""Fresh-base V4 training through the already measured finite L1 trainer."""
import hashlib
import json
from pathlib import Path
import sys
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).resolve().parent)]
import v3_train_hours as trainer
from v4_data import training_text


def main():
    out=Path(sys.argv[sys.argv.index('--out')+1])
    data=Path(sys.argv[sys.argv.index('--data')+1]);assert not out.exists()
    # The exact same forward/backward, optimizer, budget, receipts and paired
    # base/adapter evaluation; only the explicitly versioned renderer changes.
    trainer.training_text=training_text
    trainer.main()
    metadata=dict(renderer='v4_explicit_current_assistant_header',
        fresh_base=True,continued_v3_adapter=False,
        source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [Path(__file__),Path(trainer.__file__),Path(__file__).with_name('v4_data.py')]},
        frozen_sha256=hashlib.sha256((data/'FROZEN.json').read_bytes()).hexdigest() if (data/'FROZEN.json').exists() else None)
    (out/'V4_VERSION.json').write_text(json.dumps(metadata,indent=2)+'\n')


if __name__=='__main__':main()
