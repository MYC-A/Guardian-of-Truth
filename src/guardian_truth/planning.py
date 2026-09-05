"""Bounded planning in an EXPLICIT declarative model, never real tool execution.

A plan in this model is evidence for a semantic reviewer, not a proof that a
customer request is achievable in the real world or that escalation is wrong.
"""

from collections import deque
from dataclasses import dataclass, field
import json

from .checks import validate_fields
from .parsing import decode_json
from .rules import UNKNOWN, _Evaluator, _bounded_json, _keys, _validate_expr, _validate_operand
from .types import Event, Source


OPEN, CLOSE = '[GUARDIAN_PLANNING]', '[/GUARDIAN_PLANNING]'


@dataclass
class PlanAnalysis:
    status: str
    steps: list[dict] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    explored_states: int = 0
    issues: list[str] = field(default_factory=list)


def _state_expression(expression):
    """Translate only state/literal operands into the tested predicate engine."""
    if type(expression) is bool:
        return expression
    if not isinstance(expression,dict) or len(expression) != 1:
        raise ValueError('Invalid expression')
    op, value = next(iter(expression.items()))
    if op in ('all','any') and isinstance(value,list):
        return {op:[_state_expression(item) for item in value]}
    if op == 'not':
        return {op:_state_expression(value)}
    if not isinstance(value,list) or len(value) != 2:
        raise ValueError('Invalid expression')
    operands=[]
    for item in value:
        if not isinstance(item,dict) or len(item) != 1:
            raise ValueError('Invalid operand')
        if 'state' in item and isinstance(item['state'],str) and item['state']:
            operands.append({'context':[item['state']]})
        elif 'literal' in item:
            operands.append(item)
        else:
            raise ValueError('Invalid operand')
    return {op:operands}


def _state_hash(state):
    return json.dumps({key: {'unknown':True} if value is UNKNOWN else {'value':value}
                       for key,value in state.items()},sort_keys=True,ensure_ascii=False,allow_nan=False)


def analyze_plan(history, catalog, graph, *, max_depth=6, max_states=128):
    if type(max_depth) is not int or not 1 <= max_depth <= 32 or type(max_states) is not int or not 1 <= max_states <= 4096:
        raise ValueError('Invalid planning limits')
    blocks=[e for e in history if e.role=='system' and e.kind=='text' and (OPEN in e.text or CLOSE in e.text)]
    if not blocks:
        return None
    if len(blocks)!=1:
        return PlanAnalysis('unknown',issues=['planning_ambiguous_blocks'])
    event=blocks[0]
    if event.text.count(OPEN)!=1 or event.text.count(CLOSE)!=1:
        return PlanAnalysis('unknown',issues=['planning_invalid_block'])
    start,end=event.text.index(OPEN),event.text.index(CLOSE)
    if end <= start or end-start > 65536:
        return PlanAnalysis('unknown',issues=['planning_invalid_block'])
    source=Source('prompt',event.source.start+start,event.source.start+end+len(CLOSE))
    spec,valid=decode_json(event.text[start+len(OPEN):end])
    try:
        if (not valid or not _bounded_json(spec) or not _keys(spec,('version','initial','goal','actions'),('context',))
                or type(spec['version']) is not int or spec['version']!=1
                or not isinstance(spec['initial'],dict) or not 1 <= len(spec['initial']) <= 64
                or not isinstance(spec.get('context',{}),dict)
                or not isinstance(spec['actions'],list) or not 1 <= len(spec['actions']) <= 64):
            raise ValueError('Invalid planning model')
        goal=_state_expression(spec['goal'])
        if not _validate_expr(goal,[2048]): raise ValueError('Invalid goal')
        seen=set(); actions=[]
        for action in spec['actions']:
            if (not _keys(action,('id','tool','arguments','require','effects','outcome'))
                    or not isinstance(action['id'],str) or not action['id'] or action['id'] in seen
                    or not isinstance(action['tool'],str) or not action['tool']
                    or not isinstance(action['arguments'],dict)
                    or not isinstance(action['effects'],dict) or not action['effects']
                    or action['outcome'] not in ('guaranteed','conditional')):
                raise ValueError('Invalid action')
            seen.add(action['id'])
            for key,value in action['effects'].items():
                if key not in spec['initial'] or not isinstance(value,dict) or len(value)!=1:
                    raise ValueError('Invalid effect')
                if 'literal' not in value and not (isinstance(value.get('state'),str) and value['state'] in spec['initial']):
                    raise ValueError('Invalid effect')
            condition=_state_expression(action['require'])
            if not _validate_expr(condition,[2048]): raise ValueError('Invalid precondition')
            actions.append((action,condition))
        dummy=Event('assistant','call','',source,'planning_context',{},True)
        evaluator=_Evaluator(history,dummy,graph,spec.get('context',{}),source,False)
        state={}; sources=[source]
        for key,operand in spec['initial'].items():
            if not isinstance(key,str) or not key or not _validate_operand(operand) or 'arg' in operand:
                raise ValueError('Invalid initial state')
            result=evaluator.operand(operand)
            state[key]=result.value
            sources.extend(result.sources)
    except (ValueError,TypeError,KeyError,RecursionError):
        return PlanAnalysis('unknown',sources=[source],issues=['planning_invalid_model'])
    sources=list(dict.fromkeys(sources))
    queue=deque([(state,[],False)])
    visited={(_state_hash(state),False)}
    explored=0; incomplete=False; conditional_plan=None
    while queue:
        if explored >= max_states:
            return conditional_plan or PlanAnalysis('limit_reached',sources=sources,explored_states=explored,
                                                   issues=['planning_state_limit'])
        current,path,conditional=queue.popleft(); explored+=1
        evaluator=_Evaluator(history,dummy,graph,current,source,False)
        achieved=evaluator.expression(goal).value
        if achieved is True:
            plan_sources=list(dict.fromkeys(sources + [catalog.tools[step['tool']].source for step in path]))
            result=PlanAnalysis('conditional_plan' if conditional else 'plan_in_declared_model',
                                path,plan_sources,explored, ['planning_not_a_real_world_guarantee'])
            if not conditional: return result
            if conditional_plan is None: conditional_plan=result
            continue
        if achieved is UNKNOWN: incomplete=True
        if len(path)>=max_depth:
            incomplete=True
            continue
        for action,condition in actions:
            requirement=evaluator.expression(condition).value
            if requirement is UNKNOWN:
                incomplete=True
                continue
            if requirement is False: continue
            tool=catalog.tools.get(action['tool'])
            if tool is None or not tool.schema_understood:
                incomplete=True
                continue
            planned_call=Event('assistant','call','',source,action['tool'],action['arguments'],True)
            if validate_fields(action['arguments'],tool.fields,planned_call):
                incomplete=True
                continue
            next_state=dict(current)
            for key,operand in action['effects'].items():
                next_state[key]=operand['literal'] if 'literal' in operand else current[operand['state']]
            next_conditional=conditional or action['outcome']=='conditional'
            key=(_state_hash(next_state),next_conditional)
            if key in visited: continue
            visited.add(key)
            step={'action':action['id'],'tool':action['tool'],'arguments':action['arguments'],
                  'outcome':action['outcome'],'effects':action['effects']}
            queue.append((next_state,path+[step],next_conditional))
    return conditional_plan or PlanAnalysis('unknown' if incomplete else 'no_plan_in_declared_model',
                                           sources=sources,explored_states=explored,
                                           issues=['planning_not_a_real_world_guarantee'])
