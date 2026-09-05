import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CliTests(unittest.TestCase):
    def test_csv_roundtrip_and_audit_without_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, output, audit = root/'input.csv', root/'result.csv', root/'audit.jsonl'
            rows = [
                {'id':'0001', 'prompt':'⟦SYSTEM⟧\n[AVAILABLE TOOLS]\n- inspect — Read.\n⟦USER⟧\nПривет',
                 'response':'⟦ASSISTANT⟧\n→ TOOL_CALL nonexistent: {}'},
                {'id':'0002', 'prompt':'Hello', 'response':'Hello'},
            ]
            with source.open('w', encoding='utf-8', newline='') as stream:
                writer=csv.DictWriter(stream, fieldnames=['id','prompt','response'])
                writer.writeheader(); writer.writerows(rows)
            script = Path(__file__).resolve().parents[1]/'scripts'/'predict.py'
            run = subprocess.run([sys.executable, str(script), '--input',str(source),
                                  '--output',str(output), '--audit',str(audit)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            with output.open(encoding='utf-8', newline='') as stream: actual = list(csv.DictReader(stream))
            self.assertEqual(actual, [{'id':'0001','label':'1'}, {'id':'0002','label':'0'}])
            records = [json.loads(line) for line in audit.read_text(encoding='utf-8').splitlines()]
            self.assertFalse(records[0]['used_fallback'])
            self.assertTrue(records[1]['used_fallback'])
            self.assertIsNone(records[1]['probability'])
            self.assertTrue(records[0]['findings'][0]['sources'])


if __name__ == '__main__': unittest.main()
