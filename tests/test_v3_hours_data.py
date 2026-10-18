import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from v3_prepare_hours_data import parse_calls,split_top,leaves
import pytest

def test_native_names_and_nested_literals_are_not_evaluated():
    calls=parse_calls('[Market Trends API(country="us", filters={"a": [1,2]}), file/from(from="x")]',['Market Trends API','file/from'])
    assert calls[0]['function']['arguments']['filters']=={'a':[1,2]}
    assert calls[1]['function']['arguments']=={'from':'x'}
    with pytest.raises((ValueError,SyntaxError)):
        parse_calls('[f(x=__import__("os").system("bad"))]',['f'])

def test_result_paths_distinguish_records():
    assert list(leaves({'records':[{'price':10},{'price':20}]}))==[
        ('$["records"][0]["price"]',10),('$["records"][1]["price"]',20)]
    assert split_top('x="a,b", y=[1,2]')==['x="a,b"','y=[1,2]']
