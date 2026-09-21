#!/usr/bin/env python3
import inspect

import langextract as lx

print("lx.extract doc:", (lx.extract.__doc__ or "")[:500])
try:
    print("sig:", inspect.signature(lx.extract))
except Exception as e:
    print("sig err:", e)
# find the real extract module
print("module:", lx.extract.__module__)
mod = inspect.getmodule(lx.extract)
print("mod file:", mod.__file__)
src = inspect.getsource(lx.extract)
print("=== source head ===")
print(src[:2000])
