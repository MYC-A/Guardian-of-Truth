"""Guardian Next: evidence-first monitoring experiments.

The package deliberately lives beside the frozen V5.3 implementation.  It may
reuse parsers and exact checks, but never changes their behaviour in place.
"""

from .records import FourValue

__all__ = ["FourValue"]
