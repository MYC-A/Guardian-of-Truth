#!/usr/bin/env python3
"""FULL_21: read chain4/chain4b logs + GP metric summaries for archive."""
import json
import os

out = {}

def sh(cmd, t=30):
    return os.popen(f"timeout {t} " + cmd).read()

A = "/mnt/data/guardian/agent-workspace"
os.chdir(A)

out["chain4_gjudge"] = sh("tail -25 chain4_gjudge.log 2>/dev/null")
out["chain4_e3bverify"] = sh("tail -12 chain4_e3bverify.log 2>/dev/null")
out["chain4b_pjudge"] = sh("tail -25 chain4b_pjudge.log 2>/dev/null")
out["chain4b_pgjudge"] = sh("tail -25 chain4b_pgjudge.log 2>/dev/null")
out["chain4b_a4p"] = sh("tail -15 chain4b_a4p.log 2>/dev/null")
out["chain4b_a4gp"] = sh("tail -15 chain4b_a4gp.log 2>/dev/null")
out["chain4b_e9"] = sh("tail -10 chain4b_e9.log 2>/dev/null")
out["chain4b_e6"] = sh("tail -10 chain4b_e6.log 2>/dev/null")
out["q_blockrun_tail"] = sh("tail -6 q_extract_blockrun.log 2>/dev/null; echo ---; grep -c 'OK' q_extract_blockrun.log 2>/dev/null; grep -c 'FAILED' q_extract_blockrun.log 2>/dev/null")

print(json.dumps(out, ensure_ascii=False, indent=1))
