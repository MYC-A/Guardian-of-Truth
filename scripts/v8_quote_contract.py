"""Source-addressed quotes in plain text or decoded JSON policy fields.

Source support is not semantic applicability. No fuzzy/paraphrase matching.
"""
import json
import re

def norm(text):return ' '.join(text.split())

def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('DUPLICATE_POLICY_KEY')
        result[key]=value
    return result

def decoded_units(policy):
    if policy.count('<policy>')!=1 or policy.count('</policy>')!=1:return []
    raw=policy.split('<policy>',1)[1].split('</policy>',1)[0].strip()
    try:
        value=json.loads(raw,object_pairs_hook=unique_object,
            parse_constant=lambda x:(_ for _ in ()).throw(ValueError('NONFINITE_JSON')))
    except (ValueError,TypeError,RecursionError):return []
    result=[]
    def walk(item,path=()):
        if isinstance(item,dict):
            for key,value in item.items():walk(value,path+(key,))
        elif isinstance(item,list):
            for index,value in enumerate(item):walk(value,path+(index,))
        elif isinstance(item,str):
            pointer='/'+'/'.join(str(x).replace('~','~0').replace('/','~1') for x in path)
            result.append(dict(path=pointer,text=item,transform='JSON_DECODED_STRING'))
            if path and isinstance(path[-1],str):
                result.append(dict(path=pointer,text=path[-1]+': '+item,transform='IMMEDIATE_JSON_KEY_COLON_DECODED_STRING'))
    try:walk(value)
    except RecursionError:return []
    return result

def quote_support(quote,policy):
    if len(quote)<15:return None
    start=policy.find(quote)
    if start>=0:return dict(kind='RAW_LITERAL',span=[start,start+len(quote)])
    normalized=norm(quote)
    # Only whitespace changes; punctuation, amounts, identifiers and negations stay exact.
    tokens=list(re.finditer(r'\S+',policy));rendered='';mapping=[]
    for token in tokens:
        if rendered:rendered+=' ';mapping.append(token.start()-1)
        rendered+=token.group();mapping.extend(range(token.start(),token.end()))
    start=rendered.find(normalized)
    if start>=0 and normalized:
        return dict(kind='RAW_WHITESPACE_ONLY',span=[mapping[start],mapping[start+len(normalized)-1]+1])
    for unit in decoded_units(policy):
        position=norm(unit['text']).find(normalized)
        if position>=0 and normalized:
            return dict(kind='STRUCTURED_JSON_SOURCE',path=unit['path'],transform=unit['transform'],
                normalized_unit_span=[position,position+len(normalized)])
    return None

def admit_review(text,policy,was_truncated=False):
    if was_truncated:return False,'TRUNCATED',None
    lines=[x.strip() for x in text.strip().splitlines() if x.strip()]
    if len(lines)!=2 or not lines[0].startswith('Rule: ') or not lines[1].startswith('Evidence: '):return False,'INVALID_FORMAT',None
    quote=lines[0][6:].strip().strip('"\u201c\u201d')
    support=quote_support(quote,policy)
    if support is None:return False,'UNSUPPORTED_QUOTE',None
    if len(lines[1][10:].strip())<8 or re.search(r'\bUNKNOWN\b',lines[1],re.I):return False,'UNKNOWN',support
    return True,'VALID_SOURCE_NOT_SEMANTIC_PROOF',support
