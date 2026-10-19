import json
import pytest
from guardian_truth.transcript import parse_document,parse_system
from guardian_truth.transcript.catalog import validate_arguments
from guardian_truth.judge.mechanical import analyze


def prompt(tools):return '\u27e6SYSTEM\u27e7\n<policy>\nBe helpful.\n</policy>\n[AVAILABLE TOOLS]\n'+json.dumps(tools)+'\n\u27e6USER\u27e7\nPlease check A1.'
def tool(schema):return dict(type='function',function=dict(name='lookup',description='Read the record.',parameters=schema))
def parse(tools):return parse_system(parse_document(prompt(tools))).catalog


def test_json_function_catalog_preserves_nullable_nested_refs_and_required():
    schema=dict(type='object',properties={'id':{'type':'string'},'count':{'type':['integer','null']},
        'rows':dict(type='array',items={'$ref':'#/$defs/Row'})},required=['id','rows'],additionalProperties=False,
        **{'$defs':dict(Row=dict(type='object',properties={'value':{'type':'integer'}},required=['value']))})
    c=parse([tool(schema)]);assert c.complete and c.get('lookup').understood
    assert not validate_arguments(c.get('lookup'),dict(id='A1',count=None,rows=[{'value':1}]))
    assert any(x.startswith('MISSING $.rows[0].value') for x in validate_arguments(c.get('lookup'),dict(id='A1',rows=[{}])))
    assert any(x.startswith('TYPE $.rows[0].value') for x in validate_arguments(c.get('lookup'),dict(id='A1',rows=[{'value':'wrong'}])))
    # JSON Schema defaults to allowing extra fields; do not invent closed keys.
    permissive=parse([tool(dict(type='object',properties={'id':{'type':'string'}}))]).get('lookup')
    assert not validate_arguments(permissive,dict(id='A1',extra=1))


def test_unsupported_flat_schema_names_known_but_schema_not_enforced():
    c=parse([tool({'id':{'type':'str'}})])
    assert c.complete and not c.get('lookup').understood
    assert not validate_arguments(c.get('lookup'),{'id':1})


def test_duplicate_and_partial_catalogs_cannot_prove_tool_unavailability():
    schema=dict(type='object',properties={})
    for tools in [[tool(schema),tool(schema)],[tool(schema),'unparsed'],[tool(schema),dict(type='unknown')]]:
        assert not parse(tools).complete
    text=prompt([tool(schema)]).replace('"name": "lookup"','"name":"lookup","name":"other"')
    assert not parse_system(parse_document(text)).catalog.complete
    strict=tool(dict(type='object',properties={'id':{'type':'string'}},required=['id']))
    assert not parse([strict,strict]).get('lookup').understood
    text=prompt([strict]).replace('"required": ["id"]','"required": [], "required": ["id"]')
    assert not parse_system(parse_document(text)).catalog.get('lookup').understood
    assert not analyze(text,'\u27e6ASSISTANT\u27e7\n\t\u2192 TOOL_CALL lookup: {}').hard


def test_json_catalog_current_call_validation_and_unknown_tool():
    p=prompt([tool(dict(type='object',properties={'id':{'type':'string'}},required=['id']))])
    r='\u27e6ASSISTANT\u27e7\n\t\u2192 TOOL_CALL lookup: {}'
    assert any(x.startswith('schema lookup: MISSING $.id') for x in analyze(p,r).hard)
    assert any(x.startswith('unavailable_tool missing') for x in analyze(p,r.replace('lookup:','missing:')).hard)


def test_remote_references_are_not_resolved_or_trusted():
    c=parse([tool(dict(type='object',properties={'id':{'$ref':'https://example.com/schema'}}))])
    assert c.complete and not c.get('lookup').understood


def test_schema_dialect_and_dynamic_references_are_not_reinterpreted():
    # Draft 7 ignores siblings of $ref; applying 2020 semantics would falsely
    # force an enum accusation on the valid string A1.
    schema={'$schema':'http://json-schema.org/draft-07/schema#','type':'object',
        'definitions':{'Id':{'type':'string'}},
        'properties':{'id':{'$ref':'#/definitions/Id','enum':['other']}}}
    spec=parse([tool(schema)]).get('lookup')
    assert spec.understood and not validate_arguments(spec,{'id':'A1'})
    for key in ('$dynamicRef','$recursiveRef'):
        c=parse([tool(dict(type='object',properties={'id':{key:'https://example.com/schema'}}))])
        assert not c.get('lookup').understood
    schema['$schema']='https://example.com/unknown-dialect'
    assert not parse([tool(schema)]).get('lookup').understood
