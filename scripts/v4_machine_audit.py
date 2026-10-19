"""Blind, stratified V4 source audit; no optimization or human-review claim."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'src'),str(Path(__file__).resolve().parent)]
import v3_machine_audit as audit
from v4_data import judge_input


if __name__=='__main__':
    audit.judge_input=judge_input
    audit.main()
