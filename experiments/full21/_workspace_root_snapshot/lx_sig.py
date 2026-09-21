
import inspect
import langextract as lx
import langextract.core.extract as ce
print('lx.extract:', inspect.signature(lx.extract))
print('core extract:', inspect.signature(ce.extract_sync if hasattr(ce, "extract_sync") else ce.extract))
