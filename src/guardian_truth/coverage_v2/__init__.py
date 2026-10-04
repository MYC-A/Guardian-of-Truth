"""Domain-agnostic evidence coverage: budgeted weighted facet cover.

See docs/coverage_v2/DESIGN.md. Public API: ``select_evidence``.
"""
from .selector import select_evidence, extract_facets, build_units

__all__ = ['select_evidence', 'extract_facets', 'build_units']
