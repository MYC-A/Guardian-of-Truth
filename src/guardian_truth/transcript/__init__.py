"""Transcript parsing for Guardian of Truth (format of the AIJ 2026 task, verified on real rows).

    from guardian_truth.transcript import parse_document, parse_system, analyze_turn, analyze

parser.py     prompt/response -> Document (messages, events with exact spans, call/result pairing)
system.py     <policy>, [AVAILABLE TOOLS], current time, policy rules
catalog.py    tool specs, argument schema, validation
values.py     RU/EN numbers, dates, identifiers, token-bounded search
provenance.py where a value occurs and in which kind of source
features.py   hard / strong / weak findings, features and judge hints for the turn under review
io.py         Parquet/CSV input, Parquet output
audit.py      corpus statistics and per-rule precision on labelled data
"""
from .features import Findings, analyze, analyze_turn
from .parser import document_stats, parse_document
from .system import parse_system

__all__ = ['Findings', 'analyze', 'analyze_turn', 'document_stats', 'parse_document', 'parse_system']
