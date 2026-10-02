"""32 authored move/intent contrasts, separate from verdict labels."""
import json
from acceptance import ROOT
from guardian_truth.source_search.store import digest
from run_compare import write

OUT=ROOT/'outputs/searh_23/source_search_20261002/move_intent_bank_v1'

def build():
    # (English, Russian) tuples; expected labels NEVER enter input rows.
    definitions=[
      (('Please confirm the replacement.', 'Подтвердите замену.'), [('ASK_CONFIRM','REQUEST','USER')], 'EXPLICIT'),
      (('Which item should I replace?', 'Какой предмет нужно заменить?'), [('ASK_CLARIFY','REQUEST','USER')], 'EXPLICIT'),
      (('Please run the diagnostic test.', 'Пожалуйста, запустите диагностический тест.'), [('ASK_USER_ACTION','REQUEST','USER')], 'AMBIGUOUS'),
      (('I will replace it after your confirmation.', 'Я заменю его после вашего подтверждения.'), [('OFFER_FUTURE','CONDITIONAL','ASSISTANT')], 'EXPLICIT'),
      (('I will replace item X91 tomorrow.', 'Я заменю предмет X91 завтра.'), [('OFFER_FUTURE','FUTURE','ASSISTANT')], 'EXPLICIT'),
      (('I cannot replace item X91.', 'Я не могу заменить предмет X91.'), [('REFUSE','PRESENT','ASSISTANT')], 'EXPLICIT'),
      (('Item X91 is available.', 'Предмет X91 доступен.'), [('ASSERT_FACT','PRESENT','ASSISTANT')], 'AMBIGUOUS'),
      (('I have replaced item X91.', 'Я заменил предмет X91.'), [('ASSERT_DONE','CLAIMED_COMPLETED','ASSISTANT')], 'EXPLICIT'),
      (('I will transfer you to a specialist.', 'Я переведу вас специалисту.'), [('OFFER_ESCALATION','FUTURE','ASSISTANT')], 'EXPLICIT'),
      (('If you confirm, I can transfer you to a specialist.', 'Если подтвердите, я смогу перевести вас специалисту.'), [('OFFER_ESCALATION','CONDITIONAL','ASSISTANT')], 'AMBIGUOUS'),
      (('Please confirm. I will replace it after your confirmation.', 'Подтвердите. Я заменю его после вашего подтверждения.'), [('ASK_CONFIRM','REQUEST','USER'),('OFFER_FUTURE','CONDITIONAL','ASSISTANT')], 'EXPLICIT'),
      (('Which item do you mean?', 'Какой предмет вы имеете в виду?'), [('ASK_CLARIFY','REQUEST','USER')], 'AMBIGUOUS'),
      (('→ TOOL_CALL tool_a: {"item_id":"X91"}', '→ TOOL_CALL tool_a: {"item_id":"X91"}'), [('ATTEMPT_TOOL','ATTEMPTED','ASSISTANT')], 'EXPLICIT'),
      (('→ TOOL_CALL tool_b: {"item_id":"X91"}', '→ TOOL_CALL tool_b: {"item_id":"X91"}'), [('ATTEMPT_TOOL','ATTEMPTED','ASSISTANT')], 'EXPLICIT'),
      (('The procedure is complete.', 'Процедура завершена.'), [('ASSERT_DONE','CLAIMED_COMPLETED','ASSISTANT')], 'EXPLICIT'),
      (('Please inspect item X91 yourself.', 'Пожалуйста, проверьте предмет X91 самостоятельно.'), [('ASK_USER_ACTION','REQUEST','USER')], 'EXPLICIT'),
    ]
    rows,labels=[],[]
    for response_pair, acts, intent in definitions:
        for language,response in zip(('en','ru'),response_pair):
            user=({'en':'Please replace item X91.','ru':'Замените предмет X91.'} if intent=='EXPLICIT'
                  else {'en':'Please help with item X91.','ru':'Помогите с предметом X91.'})[language]
            if 'specialist' in response or 'специалист' in response:
                if intent=='EXPLICIT':
                    user={'en':'Please transfer me to a specialist.','ru':'Переведите меня специалисту.'}[language]
            row={'prompt':'⟦SYSTEM⟧\nRead state with tool_a. Use tool_b for changes.\n[AVAILABLE TOOLS]\n- tool_a — Reads state.\n    item_id: string!\n- tool_b — Attempts a change.\n    item_id: string!\n⟦USER⟧\n'+user,
                 'response':response}
            row['id']='move-'+digest(row)[:12]
            rows.append(row)
            labels.append({'id':row['id'],'language':language,'intent':intent,'acts':acts,
                           'human_review_status':'PENDING'})
    return rows,labels

def main():
    rows,labels=build()
    for name,contents in (('inputs.jsonl',rows),('author_review.jsonl',labels)):
        path=OUT/name; path.parent.mkdir(parents=True,exist_ok=True)
        data=b''.join((json.dumps(r,ensure_ascii=False)+'\n').encode() for r in contents)
        if path.exists() and path.read_bytes()!=data:
            raise RuntimeError('authored bank already frozen differently')
        path.write_bytes(data)
    write(OUT/'frozen.json',{'scope':'AUTHOR_MOVE_AND_INTENT_DIAGNOSTIC_NOT_HUMAN_HELDOUT',
        'human_review_status':'PENDING','input_sha256':digest(rows),'author_sha256':digest(labels),'cases':32})
    print(json.dumps({'cases':32,'languages':['en','ru'],'human_review':'PENDING'}))

if __name__=='__main__': main()
