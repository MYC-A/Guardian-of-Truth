#!/usr/bin/env python3
import inspect

from langextract.core import data

print("AnnotatedDocument fields:")
ad = data.AnnotatedDocument
try:
    print(inspect.signature(ad.__init__))
except Exception as e:
    print("err:", e)
for n in dir(ad):
    if not n.startswith("_"):
        print(" -", n)
print("Extraction fields:")
ex = data.Extraction
try:
    print(inspect.signature(ex.__init__))
except Exception as e:
    print("err:", e)
print("CharInterval:")
ci = getattr(data, "CharInterval", None)
if ci:
    print(inspect.signature(ci.__init__))
