"""Ownership and phase regressions for the experimental reminder adapter."""
import json
import unittest
from target_frame_probe import request_with_target,target_frame,REMINDER
from test_source_search import case
from guardian_truth.source_search.id_contract import id_contract


class Tests(unittest.TestCase):
    def test_search_requests_an_action_and_keeps_original_messages(self):
        messages=[{'role':'system','content':id_contract('SEARCH')},{'role':'user','content':'existing source view'}]
        actual=request_with_target(messages,target_frame(case()))
        self.assertEqual(actual[:-1],messages)
        self.assertNotIn('Finding type',actual[-1]['content'])
        self.assertIn('This is SEARCH, not assessment',actual[-1]['content'])

    def test_final_keeps_identical_reminder_and_exact_examined_target(self):
        row=case();frame=target_frame(row)
        messages=[{'role':'system','content':id_contract('FINAL')}]
        actual=request_with_target(messages,frame)
        self.assertTrue(actual[-1]['content'].startswith(REMINDER+'\n'))
        payload=json.loads(actual[-1]['content'].split(REMINDER+'\n',1)[1])
        self.assertEqual(payload['evaluation_target']['raw_examined_response'],row['response'])
        self.assertTrue(all(e['source_id'].startswith('t') for e in frame['events']))


if __name__=='__main__':unittest.main()
