"""Production wiring and failure regressions; fake model is not F1 or timing evidence."""
import contextlib
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from guardian_truth.judge import answer_review as ar, blind_review as br
from guardian_truth.judge.decision import decide
from guardian_truth.judge.review_stage import merge_review_stats
from scripts import judge_stage, judge_submission, eval_judge_valid
from tests.test_judge_v3 import fake_vllm, FakeTok
from tests.test_judge_blind_review import rows, context, FakeLLM
from guardian_truth.judge.review_stage import run_review

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'submission/JUDGE_OPEN_REVIEW40.json').read_text())
S = br.validate_review_config(CONFIG)
NOTE = dict(checks=[dict(action='current action', fact='entity binding uncertain', rule='check condition',
                        exception='earlier consent may apply', support=['u0'], counter=[], assessment='UNKNOWN')],
            unknowns=['unverified fixture'])


class AuditHelpers(unittest.TestCase):
    def test_input_is_saved_context_answer_aware_and_offsets_are_exact(self):
        tok = FakeTok()
        row = rows(1)[0]
        row['response'] = '⟦ASSISTANT⟧\nCURRENT_ACTION_123\u2028\u2029\u0085'
        base = judge_stage.build_prompt(tok, row, 20000)[0]
        saved = dict(text=base, trimmed=False)
        pre = ar.prepare(tok, saved, S, 49144)
        self.assertIn('CURRENT_ACTION_123', pre['text'])
        self.assertIn('lawful interpretation', pre['text'])
        self.assertEqual(''.join(pre['source'][u['start']:u['end']] for u in pre['units']),pre['source'])
        self.assertTrue(all(0 <= u['start'] < u['end'] <= len(pre['source']) for u in pre['units']))
        status, parsed, report = ar.parse_notes(json.dumps(NOTE), 'stop', br.citable(pre['units']), S)
        self.assertEqual(status, 'VALID')
        block = ar.render_notes(parsed, pre, S)
        self.assertIn(br.sha(pre['source']), block)
        self.assertFalse(report['semantic_validation'])
        with self.assertRaisesRegex(ValueError, 'OVER_CAP'):
            ar.prepare(tok, saved, S, 10)

    def test_malformed_truncated_and_unknown_references_do_not_pass(self):
        for raw, finish in [('{}','stop'), ('','stop'), ('[]','stop'), (json.dumps(NOTE),'length'),
                            (json.dumps(NOTE).replace('u0','u999'), 'stop')]:
            self.assertIn(ar.parse_notes(raw, finish, ['u0'], S)[0], ('INVALID','TRUNCATED'))
        note = json.loads(json.dumps(NOTE))
        note['checks'][0].update(assessment='CONCERN', support=[])
        self.assertEqual(ar.parse_notes(json.dumps(note),'stop',['u0'],S)[0], 'INVALID')
        self.assertEqual(ar.parse_notes('{"checks":[],"unknowns":[]}', 'stop', [], S)[0], 'VALID')

    def test_config_cannot_silently_select_old_review(self):
        self.assertEqual(S['review_ranking'], 'max_exact')
        for updates in (dict(review_mode='blind'), dict(review_schedule='after_primary'),
                        dict(review_ranking='complete'), dict(require_exact_scores=False),
                        dict(review_input_reserve_tokens=0)):
            with self.assertRaises(ValueError):
                br.validate_review_config(dict(CONFIG, **updates))
            safe, error = judge_submission.normalize_profile(dict(CONFIG, **updates))
            self.assertIsNotNone(error)
            self.assertEqual(safe['review_mode'], 'off')


class MaxReview(unittest.TestCase):
    def test_available_max_preserves_both_sources_without_global_gate(self):
        primary={0:8.,1:-2.,2:3.,3:-8.}
        final={0:-20.,1:12.,4:7.,5:float('nan'),6:True}
        used, mode, missing=br.select_ranking(primary, final, list(range(7)), 'max_exact')
        self.assertEqual(used,{0:8.,1:12.,2:3.,3:-8.,4:7.})
        self.assertEqual(mode,'max_exact_overall_final')
        self.assertEqual(missing,4)
        all_final={i:-100. for i in primary}
        self.assertEqual(br.select_ranking(primary,all_final,list(primary),'max_exact')[0],primary)
        self.assertEqual(br.select_ranking(primary,{},list(primary),'max_exact')[0],primary)
        self.assertEqual(br.effective_for_eval(CONFIG,primary,final,7)[0],used)

    def test_duplicate_invalidates_its_row_only_and_exact_reading(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'r.jsonl'
            data=[dict(key=0,review='final',final_score=4.,exact=True),
                  dict(key=1,review='final',final_score=7.,exact=True),
                  dict(key=1,review='final',final_score=8.,exact=True),
                  dict(key=2,review='final',final_score=9.,exact=False),
                  dict(key=3,score=100.,exact=False)]
            p.write_text(''.join(json.dumps(r)+'\n' for r in data))
            self.assertEqual(judge_submission.read_review_scores(p,isolate_duplicates=True),{0:4.})
            self.assertEqual(judge_submission.read_review_scores(p),{})
            self.assertEqual(judge_submission.read_scores(p,exact_only=True)[0],{})
        self.assertEqual(sum(decide(10,{},dict(enumerate(range(10))),.4)),4)
        self.assertEqual(decide(10,{0},dict(enumerate(range(10))),.4),[1,0,0,0,0,0,0,1,1,1])


class StageWiring(unittest.TestCase):
    def test_budget_projection_defers_without_writing_a_duplicate_final(self):
        ctx,out=context(FakeLLM(), 'open', rows(2), stop_at=100, clock=lambda:0)
        ctx.settings=S
        ctx.usage=judge_stage.Usage
        ctx.defer_on_budget=True
        ctx.timing={role:dict(prompts=2,prompt_tokens=100,generated_tokens=1,wall_seconds=10000.)
                    for role in ('prepass','final')}
        stats=run_review(ctx)
        self.assertEqual(stats['deferred_rows'],2)
        self.assertFalse(ctx.llm.calls)
        self.assertFalse(any(r.get('review')=='final' for r in out))
        ctx.defer_on_budget=False
        stats=run_review(ctx)
        self.assertEqual(stats['final_deadline'],2)
        self.assertFalse(ctx.llm.calls)

    def run_stage(self, bad=None, stop_seconds=600):
        with tempfile.TemporaryDirectory() as folder:
            work=Path(folder); source=work/'input.jsonl'; output=work/'scores.jsonl'
            data=rows(5)
            for i,row in enumerate(data):
                row.update(response='⟦ASSISTANT⟧\nCURRENT_%d'%i,label='GOLD_SECRET',explanation='GOLD_REASON')
            source.write_text(''.join(json.dumps(r)+'\n' for r in data))
            config=work/'config.json'; config.write_text(json.dumps(dict(CONFIG,chunk=2)))
            sent={}; modules=fake_vllm(sent); Base=modules['vllm'].LLM
            class Engine(Base):
                def generate(self,prompts,params,use_tqdm=False):
                    if params.max_tokens==1:
                        out=super().generate(prompts,params,use_tqdm)
                        if bad=='final' and any(br.CHECKLIST in p for p in prompts) and not sent.get('broke_final'):
                            sent['broke_final']=True;out[0].outputs=[]
                        return out
                    if hasattr(params,'allowed_token_ids'):
                        raise AssertionError('generation inherited answer token restriction')
                    self_test=judge_stage.read_jsonl(output)
                    primary=[r for r in self_test if 'score' in r and not r.get('review')]
                    if not primary: raise AssertionError('primary not durable')
                    sent.setdefault('primary_at_audit',[]).append(len(primary))
                    sent.setdefault('audits',[]).extend(prompts)
                    sent.setdefault('gen_params',[]).append(params)
                    out=[SimpleNamespace(prompt=p,prompt_token_ids=p.split(),outputs=[SimpleNamespace(
                        text=json.dumps(NOTE),finish_reason='stop',token_ids=[7,8])]) for p in prompts]
                    if bad in ('notes','truncated') and not sent.get('broke_notes'):
                        sent['broke_notes']=True
                        if bad=='notes':out[0].outputs[0].text='broken'
                        else:out[0].outputs[0].finish_reason='length'
                    return out
            modules['vllm'].LLM=Engine
            with patch.dict(sys.modules,modules),contextlib.redirect_stdout(io.StringIO()):
                judge_stage.main(['--input',str(source),'--output',str(output),'--model','fixture',
                                  '--config',str(config),'--stop-at',str(judge_stage.time.time()+stop_seconds)])
            records=judge_stage.read_jsonl(output)
            primary=judge_submission.read_scores(output,exact_only=True)[0]
            final=judge_submission.read_review_scores(output,isolate_duplicates=True)
            effective=br.effective_for_eval(CONFIG,primary,final,5)
        return records,sent,effective

    def test_per_chunk_delivery_saved_context_and_separate_sampling(self):
        records,sent,effective=self.run_stage()
        self.assertEqual(sent['primary_at_audit'],[2,4,5])
        self.assertEqual(effective[1],'max_exact_overall_final')
        self.assertEqual(sum(r.get('review')=='final' and r.get('exact') is True for r in records),5)
        self.assertEqual(sum(r.get('delivery')=='DELIVERED' for r in records),5)
        for text in sent['audits']:
            self.assertIn('CURRENT_',text)
            self.assertNotIn('GOLD_SECRET',text)
            self.assertNotIn('GOLD_REASON',text)
        for params in sent['gen_params']:
            self.assertEqual(params.temperature,0.)
            self.assertEqual(params.max_tokens,384)
        done=next(r for r in records if r.get('event')=='review_done')
        self.assertEqual(done['final_exact'],5)
        self.assertEqual(done['prepass']['prompts'],5)
        self.assertEqual(done['final']['prompts'],5)

    def test_failed_notes_or_final_do_not_erase_other_rows(self):
        for bad in ('notes','truncated','final'):
            records,sent,effective=self.run_stage(bad)
            self.assertEqual(len(effective[0]),5)
            self.assertEqual(effective[1],'max_exact_overall_final')
            if bad=='final':
                self.assertEqual(sum(r.get('review')=='final' and r.get('exact') is True for r in records),4)
            else:
                self.assertEqual(sum(r.get('delivery')=='DELIVERED' for r in records),4)

    def test_stop_deadline_starts_no_audit(self):
        records,sent,effective=self.run_stage(stop_seconds=-1)
        self.assertNotIn('audits',sent)
        self.assertFalse(effective[0])


class EvalWiring(unittest.TestCase):
    def test_eval_consumes_partial_review_max_and_40_quota(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'input.csv'
            with source.open('w',encoding='utf-8',newline='') as f:
                w=csv.writer(f);w.writerow(['id','prompt','response','label'])
                for i,row in enumerate(rows(4)):
                    w.writerow([str(i),row['prompt'],'⟦ASSISTANT⟧\nHello',i%2])
            def score_fixture(command,**kwargs):
                target=Path(command[command.index('--output')+1])
                data=[dict(key=i,score=-float(i),exact=True) for i in range(4)]
                data.append(dict(key=3,review='final',final_score=10.,exact=True))
                target.write_text(''.join(json.dumps(r)+'\n' for r in data))
                return 0
            with patch.object(eval_judge_valid.subprocess,'call',side_effect=score_fixture), \
                    contextlib.redirect_stdout(io.StringIO()):
                eval_judge_valid.main(['--input',str(source),'--out',str(root/'run'),'--model','fixture',
                                      '--config',str(ROOT/'submission/JUDGE_OPEN_REVIEW40.json')])
            result=json.loads((root/'run/summary.json').read_text())
            self.assertEqual(result['ranking'],'max_exact_overall_final')
            self.assertEqual(result['ranked_rows'],4)
            self.assertEqual(result['review']['final_scored'],1)


if __name__=='__main__':
    unittest.main()
