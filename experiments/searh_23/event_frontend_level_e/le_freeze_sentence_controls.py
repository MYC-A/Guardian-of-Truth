"""New source-sentence/POS controls frozen before the alternate extractor."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
HERE=Path(__file__).parent
CASES=[
 ("e7_switch","Switch cell K. Check cell K's voltage before isolating cell K.",
  ["Switch cell K","Check cell K's voltage","isolating cell K"]),
 ("e7_stencil","Ink stencil Q. Press stencil Q only after the ink is dry.",
  ["Ink stencil Q","Press stencil Q","the ink is dry"]),
 ("e7_loom","Thread loom R. Start loom R once the thread is checked.",
  ["Thread loom R","Start loom R","the thread is checked"]),
 ("e7_cable","Splice cable 12. Test cable 12 before installing it.",
  ["Splice cable 12","Test cable 12","installing it"]),
 ("e7_tray","Plate sample 15. Count colonies after incubating sample 15.",
  ["Plate sample 15","Count colonies","incubating sample 15"]),
 ("e7_stamp","Stamp docket S. Send docket S after the stamp is verified.",
  ["Stamp docket S","Send docket S","the stamp is verified"]),
 ("e7_decimal","Measure a 3.5 mm gap. Close the housing after measuring the gap.",
  ["Measure a 3.5 mm gap","Close the housing","measuring the gap"]),
 ("e7_abbrev","Dr. Ito must sign the register. Release the lot after the register is signed.",
  ["sign the register","Release the lot","the register is signed"]),
 ("e7_quote","Display the label \"Stop. Wait.\" before opening the bay.",
  ["Display the label \"Stop. Wait.\"","opening the bay"]),
 ("e7_modal","The technician must remain seated until the train stops.",
  ["remain seated","the train stops"]),
]

def main():
 inputs=[{"id":cid,"policy":p} for cid,p,spans in CASES]
 gold={cid:[{"text":s,"start":p.index(s),"end":p.index(s)+len(s)} for s in spans] for cid,p,spans in CASES}
 frozen=HERE/"frozen"
 for name,data in (("sentence_inputs.json",inputs),("sentence_gold.json",gold)):
  path=frozen/name
  if path.exists(): raise RuntimeError(f'already frozen {path}')
  path.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8",newline="\n")
 manifest={"n_cases":len(inputs),"n_cores":sum(map(len,gold.values())),
  "scope":"new author-written source splitting/POS controls; quotes, abbreviation, decimal included",
  "arms":["old","global_anchored","source_sentence_anchored","source_sentence_plus_POS_hypothesis"],
  "hashes":{n:hashlib.sha256((frozen/n).read_bytes()).hexdigest() for n in ("sentence_inputs.json","sentence_gold.json")}}
 (frozen/"sentence_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8",newline="\n")
 print(json.dumps(manifest,indent=2))
if __name__=='__main__': main()
