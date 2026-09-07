import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'merge_architecture_runs.py'
SPEC=importlib.util.spec_from_file_location('merge_architecture_runs',SCRIPT)
MERGE=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MERGE)


class MergeArchitectureRunsTests(unittest.TestCase):
    def shard(self,root,name,start,identifier,gold,prediction,variant='strict'):
        directory=root/name;directory.mkdir()
        config={field:'same' for field in MERGE.CORE_FIELDS}
        config.update(variant=variant,selected_ids=[identifier],
                      row_window={'start_index':start,'row_count':1})
        row={'id':identifier,'label':gold,'prediction':prediction,
             'decision':{'used_fallback':False},'logical_llm_calls':1,'http_attempts':1,
             'elapsed_seconds':2,'review':{'semantic_usage':{'total_tokens':10},
                                           'unresolved':[]},'ledger':None}
        (directory/'configuration.json').write_text(json.dumps(config),encoding='utf-8')
        (directory/'report.json').write_text('{}',encoding='utf-8')
        (directory/'audit.jsonl').write_text(json.dumps(row)+'\n',encoding='utf-8')
        return directory

    def test_contiguous_compatible_shards_merge_and_recompute(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            first=self.shard(root,'a',0,'a',0,0)
            second=self.shard(root,'b',1,'b',1,1)
            config,rows,report=MERGE.merge([first,second])
            self.assertEqual(config['selected_ids'],['a','b'])
            self.assertEqual([row['id'] for row in rows],['a','b'])
            self.assertEqual(report['metrics']['f1'],1)
            self.assertEqual(report['metrics']['logical_llm_calls'],2)

    def test_gap_or_configuration_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            first=self.shard(root,'a',0,'a',0,0)
            gap=self.shard(root,'gap',2,'b',1,1)
            with self.assertRaises(ValueError): MERGE.merge([first,gap])
            changed=self.shard(root,'changed',1,'c',1,1,variant='baseline')
            with self.assertRaises(ValueError): MERGE.merge([first,changed])


if __name__=='__main__': unittest.main()
