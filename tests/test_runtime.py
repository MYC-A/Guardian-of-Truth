import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from guardian_truth.decision import decide
from guardian_truth.language import LanguageAnalyzer, LanguageConfig, RunBudget
from guardian_truth.llm_client import Completion, ConfigurationError
from guardian_truth.pipeline import Detector
from guardian_truth.runtime import make_detector
from guardian_truth.settings import load_env_file


def answer(ids):
    return {'verdict':'error','risk':0.9,'reason':'Material contradiction',
            'evidence_ids':ids,'claims':[{'text':'Candidate assertion','verdict':'contradicted',
                                        'reason':'Contradicted by source','evidence_ids':ids}],
            'requests':[],'plan':[]}


class RuntimeTests(unittest.TestCase):
    def test_rlm_actually_reads_new_source_and_revisits(self):
        class ReaderClient:
            def __init__(self): self.payloads=[]; self.target=None
            def complete(self,messages):
                payload=json.loads(messages[-1]['content']); self.payloads.append(payload)
                if self.target is None:
                    seen={e['id'] for e in payload['evidence']}
                    self.target=next(c['id'] for c in payload['catalog']['chunks'] if c['id'] not in seen)
                    output={'requests':[{'action':'read','ids':[self.target]}],'verdict':'unknown'}
                else:
                    assert self.target in {e['id'] for e in payload['evidence']}
                    output=answer([self.target])
                return Completion(json.dumps(output),{'total_tokens':10})
        client=ReaderClient()
        prompt='⟦SYSTEM⟧\nPolicy '+('unrelated ' * 1800)
        analyzer=LanguageAnalyzer(client,LanguageConfig(mode='rlm',max_rounds=2),budget=RunBudget(max_requests=2))
        review=Detector(semantic=analyzer).review(prompt,'An assertion')
        self.assertEqual(len(client.payloads),2)
        self.assertEqual(review.semantic_score,.9)
        self.assertEqual(len(review.reading_trace),2)
        self.assertEqual(review.semantic_usage['total_tokens'],20)
        self.assertEqual(review.semantic_usage['llm_calls'],2)
        self.assertEqual(decide(review,use_semantic=True).label,1)
        self.assertEqual(review.status,'unknown')

    def test_unknown_request_does_not_execute_code(self):
        class Fake:
            def complete(self,messages):
                return Completion(json.dumps({'requests':[{'action':'python','code':'raise RuntimeError()'}],
                                              'verdict':'unknown'}))
        review=Detector(semantic=LanguageAnalyzer(Fake(),LanguageConfig(mode='rlm'))).review('Context','Candidate')
        self.assertIn('language_no_read_progress',review.unresolved)
        self.assertIsNone(review.semantic_score)

    def test_supported_rules_are_integrated(self):
        policy={'version':1,'rules':[{'id':'minimum','tool':'reserve',
                                     'require':{'ge':[{'arg':['amount']},{'literal':1}]}}]}
        prompt='⟦SYSTEM⟧\n[GUARDIAN_RULES]\n'+json.dumps(policy)+'\n[/GUARDIAN_RULES]'
        response='⟦ASSISTANT_TOOL_CALL name="reserve"⟧\n{"amount":0}'
        review=Detector().review(prompt,response)
        self.assertEqual(review.status,'violation')
        self.assertIn('rule_precondition_violation',{f.code for f in review.findings})

    def test_env_file_does_not_override_process_env_or_execute(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'GROQ_API_KEY':'process-value'}):
            path=Path(folder)/'.env'
            path.write_text('GROQ_API_KEY=file-value\nOPENROUTER_API_KEY=router-value\n'
                            'GEMINI_API_KEY=gemini-value\nGUARDIAN_MODEL="local-model"\n'
                            'DANGEROUS=$(whoami)\n',encoding='utf-8')
            self.assertTrue(load_env_file(path))
            self.assertEqual(os.environ['GROQ_API_KEY'],'process-value')
            self.assertEqual(os.environ['GUARDIAN_MODEL'],'local-model')
            self.assertEqual(os.environ['OPENROUTER_API_KEY'],'router-value')
            self.assertEqual(os.environ['GEMINI_API_KEY'],'gemini-value')
            self.assertNotIn('DANGEROUS',os.environ)

    def test_local_switch_does_not_use_groq_credential(self):
        with patch.dict(os.environ,{'GROQ_API_KEY':'fake-secret'},clear=True):
            detector=make_detector(backend='local')
            self.assertEqual(detector.semantic.client.config.api_key_env,'GUARDIAN_LOCAL_API_KEY')

    def test_remote_provider_host_is_restricted(self):
        with self.assertRaises(ValueError):
            make_detector(backend='bad')
        from guardian_truth.llm_client import ConfigurationError
        with self.assertRaises(ConfigurationError):
            make_detector(backend='groq',base_url='https://unrelated.example/v1')

    def test_remote_providers_bind_distinct_credentials_and_hosts(self):
        credentials={'OPENROUTER_API_KEY':'router-test','GEMINI_API_KEY':'gemini-test'}
        with patch.dict(os.environ,credentials,clear=True):
            router=make_detector(backend='openrouter',model='vendor/model')
            gemini=make_detector(backend='gemini',model='gemini-test-model')
        self.assertEqual(router.semantic.client.config.base_url,'https://openrouter.ai/api/v1')
        self.assertEqual(router.semantic.client.config.api_key_env,'OPENROUTER_API_KEY')
        self.assertEqual(gemini.semantic.client.config.base_url,
                         'https://generativelanguage.googleapis.com/v1beta/openai')
        self.assertEqual(gemini.semantic.client.config.api_key_env,'GEMINI_API_KEY')
        with patch.dict(os.environ,credentials,clear=True), self.assertRaises(ConfigurationError):
            make_detector(backend='openrouter',model='x',base_url='https://api.groq.com/openai/v1')

    def test_saved_provider_aliases_are_supported_without_copying_keys(self):
        aliases={'OPENROUTE_API_KEY':'router-alias','OPENROUTE_MODEL':'vendor/alias',
                 'GEMENI_API_KEY':'gemini-alias'}
        with patch.dict(os.environ,aliases,clear=True):
            router=make_detector(backend='openrouter')
            gemini=make_detector(backend='gemini',model='gemini-model')
        self.assertEqual(router.semantic.client.config.api_key_env,'OPENROUTE_API_KEY')
        self.assertEqual(router.semantic.client.config.model,'vendor/alias')
        self.assertEqual(gemini.semantic.client.config.api_key_env,'GEMENI_API_KEY')

    def test_decomposed_runtime_is_explicit_and_defaults_remain_one_shot(self):
        with patch.dict(os.environ,{},clear=True):
            baseline=make_detector(backend='local')
            decomposed=make_detector(backend='local',semantic_protocol='decomposed',
                                     decomposition_max_checks=8,decomposition_group_size=3)
        self.assertEqual(baseline.semantic.name,'language:graph')
        self.assertEqual(decomposed.semantic.name,'language:decomposed')
        self.assertEqual(decomposed.semantic.config.max_checks,8)
        self.assertEqual(decomposed.semantic.config.group_size,3)

    def test_cli_local_http_end_to_end(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append((self.headers.get('Authorization'),payload))
                body=json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer(['prompt']))}}],
                                 'usage':{'total_tokens':20},'model':'fake-local'}).encode()
                self.send_response(200); self.send_header('Content-Length',str(len(body)))
                self.end_headers(); self.wfile.write(body)
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder); source=root/'in.csv'; output=root/'out.csv'; audit=root/'audit.jsonl'
                with source.open('w',encoding='utf-8',newline='') as stream:
                    writer=csv.DictWriter(stream,fieldnames=['id','prompt','response']); writer.writeheader()
                    writer.writerow({'id':'001','prompt':'The value is one.','response':'The value is two.'})
                script=Path(__file__).resolve().parents[1]/'scripts'/'predict.py'
                env=dict(os.environ,GROQ_API_KEY='fake-should-not-be-sent'); env.pop('GUARDIAN_LOCAL_API_KEY',None)
                run=subprocess.run([sys.executable,str(script),'--input',str(source),'--output',str(output),
                                    '--audit',str(audit),'--backend','local','--mode','direct',
                                    '--base-url',f'http://127.0.0.1:{server.server_port}/v1',
                                    '--env-file',str(root/'absent.env'),'--max-requests','1'],
                                   capture_output=True,text=True,env=env,timeout=10)
                self.assertEqual(run.returncode,0,run.stderr)
                record=json.loads(audit.read_text(encoding='utf-8'))
                self.assertEqual(record['label'],1); self.assertFalse(record['used_fallback'])
                self.assertEqual(record['status'],'unknown'); self.assertEqual(record['semantic_score'],.9)
                self.assertEqual(len(requests),1); self.assertIsNone(requests[0][0])
                payload=json.loads(requests[0][1]['messages'][-1]['content'])
                self.assertNotIn('label',payload); self.assertNotIn('id',payload)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)


if __name__ == '__main__': unittest.main()
