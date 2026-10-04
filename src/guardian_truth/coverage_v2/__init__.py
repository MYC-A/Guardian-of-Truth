"""Domain-agnostic evidence coverage: budgeted weighted facet cover.

See ``selector`` for the deterministic phased heuristic and its limitations.
Public API: ``select_evidence``.
"""
from .selector import select_evidence, extract_facets, build_units

__all__ = ['select_evidence', 'extract_facets', 'build_units']
