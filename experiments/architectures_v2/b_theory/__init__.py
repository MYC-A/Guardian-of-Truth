"""Controlled Architecture B experiment boundary.

This package keeps model hypotheses separate from the existing RuleIR,
binder, compiler and Clingo proof core.
"""

from .contracts import Variant
from .orchestrator import run_case

__all__ = ["Variant", "run_case"]
