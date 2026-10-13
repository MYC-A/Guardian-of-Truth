"""Wait for the pinned weight stage, then verify and publish the submission ZIP."""
import argparse
import json
from pathlib import Path
import sys
import time

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.build_qwen35_system_submission import finalize

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage',required=True);p.add_argument('--output',required=True)
    p.add_argument('--source-zip',required=True);p.add_argument('--wait-seconds',type=float,default=86400)
    args=p.parse_args();receipt=Path(args.stage+'.weights.json');deadline=time.monotonic()+args.wait_seconds
    print(json.dumps(dict(event='waiting_for_complete_verified_weights',stage=args.stage)),flush=True)
    while time.monotonic()<deadline:
        try:
            data=json.loads(receipt.read_text())
            if data.get('all_model_files_verified'):
                return finalize(args.stage,args.output,args.source_zip)
        except FileNotFoundError:pass
        time.sleep(10)
    raise TimeoutError('WEIGHT_DOWNLOAD_NOT_COMPLETE_WITHIN_WAIT_BUDGET')

if __name__=='__main__':main()
