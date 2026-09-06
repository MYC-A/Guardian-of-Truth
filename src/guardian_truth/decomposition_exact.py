"""Proof-safe default exact routing for the first decomposition experiment."""
from decimal import Decimal, InvalidOperation, localcontext
import re

from .decomposition import DeterministicProof, MaterialCheck


NUMBER=r'[+-]?(?:0|[1-9]\d*)(?:\.\d+)?'
MONEY=r'(?:[$\u20ac\u00a3\u20bd]\s*)?'
BOUND_LEFT=r'(?<![\w./:#-])'
BOUND_RIGHT=r'(?![\w.%/:-])'
BINARY=re.compile(BOUND_LEFT+rf'(?P<a>{MONEY}{NUMBER})\s*(?P<op>[+*])\s*'
                  rf'(?P<b>{MONEY}{NUMBER})\s*(?P<cmp>=|<|>)\s*'
                  rf'(?P<c>{MONEY}{NUMBER})'+BOUND_RIGHT)
COMPARE=re.compile(BOUND_LEFT+rf'(?P<a>{MONEY}{NUMBER})\s*(?P<cmp><|>)\s*'
                   rf'(?P<c>{MONEY}{NUMBER})'+BOUND_RIGHT)
AMBIGUOUS_CONTEXT=re.compile(
    r'(?i)(?:\b(?:date|day|month|year|id|identifier|flight|order|version|booking|ticket)\b|'
    r'рейс|заказ|верси|дата|месяц|год|идентификатор|номер)')


def _number(value):
    return Decimal(re.sub(r'[$\u20ac\u00a3\u20bd\s]','',value))


def _matches(fragment):
    matches=[('binary',match) for match in BINARY.finditer(fragment)]
    occupied={(match.start(),match.end()) for _,match in matches}
    matches += [('compare',match) for match in COMPARE.finditer(fragment)
                if (match.start(),match.end()) not in occupied]
    return matches


def resolve_exact(check: MaterialCheck, context):
    """Resolve only an explicit, self-contained arithmetic relation.

    Natural-language entity/value interpretation remains semantic. Dates, IDs,
    percentages, versions, division, subtraction, units and multiple expressions
    deliberately abstain in V1. The proof covers arithmetic truth only.
    """
    if not isinstance(check,MaterialCheck) or check.type != 'value': return None
    fragment=context.response[check.source.start:check.source.end]
    if AMBIGUOUS_CONTEXT.search(fragment): return None
    matches=_matches(fragment)
    if len(matches)!=1: return None
    kind,match=matches[0]
    try:
        with localcontext() as arithmetic:
            arithmetic.prec=80
            left=_number(match['a']); right=_number(match['c'])
            if kind=='binary':
                other=_number(match['b'])
                left=left+other if match['op']=='+' else left*other
            holds={'=':left==right,'<':left<right,'>':left>right}[match['cmp']]
    except (InvalidOperation,OverflowError,ValueError):
        return None
    relation='SUPPORTED' if holds else 'CONTRADICTED'
    reason=(f'Explicit arithmetic evaluates to {left}; relation {match.group(0)!r} is '
            +('true.' if holds else 'false.'))
    return DeterministicProof(relation,reason,(check.source,))
