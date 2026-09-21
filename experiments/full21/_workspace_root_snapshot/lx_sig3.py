#!/usr/bin/env python3
import inspect

import langextract as lx
from langextract import core

print("extract_func:", lx.__dict__.get("extract_func"))
fn = lx.__dict__.get("extract_func")
if fn:
    print("sig:", inspect.signature(fn))
    print(inspect.getsource(fn)[:800])
# also check core.extract module
import langextract.core.extract as ce
for name in dir(ce):
    if not name.startswith("_") and callable(getattr(ce, name)):
        try:
            print(name, inspect.signature(getattr(ce, name)))
        except Exception:
            pass
