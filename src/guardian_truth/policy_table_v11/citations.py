"""Locate unambiguous source spans; presentation repair never supplies semantic evidence.

Matching is tiered. Each tier only removes *presentation* differences that LLM
copies routinely introduce (whitespace runs, typographic quotes, dashes, NBSP,
zero-width characters, double-escaped line breaks). Spelling, casing, punctuation
other than quote/dash glyphs, and paraphrase are never repaired. A quote must match
exactly one location: a first match is not a unique provenance anchor.
"""
from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class Citation:
    start: int
    end: int
    source_quote: str
    model_quote: str
    conversion: str


# Glyph classes that render identically to a reader but differ byte-wise.
_QUOTES = '"\'`«»‘’‚‛“”„‟‹›′″'
_DASHES = '-‐‑‒–—―−'
_INVISIBLE = '​‌‍⁠﻿­'
_QUOTE_CLASS = '[' + re.escape(_QUOTES) + ']'
_DASH_CLASS = '[' + re.escape(_DASHES) + ']'
_INVISIBLE_RE = re.compile('[' + _INVISIBLE + ']')


def _pattern(needle, glyphs=False):
    """Regex that accepts any whitespace run (\\s+) between tokens.

    With ``glyphs`` every quote glyph matches every quote glyph, every dash
    glyph every dash glyph, and invisible characters in the source are skipped.
    """
    needle = unicodedata.normalize('NFC', _INVISIBLE_RE.sub('', needle)).strip()
    skip = '[' + _INVISIBLE + ']*' if glyphs else ''
    out = []
    for piece in re.split(r'\s+', needle):
        chars = []
        for ch in piece:
            if glyphs and ch in _QUOTES: chars.append(_QUOTE_CLASS)
            elif glyphs and ch in _DASHES: chars.append(_DASH_CLASS)
            else: chars.append(re.escape(ch))
        out.append(skip.join(chars))
    return r'\s+'.join(out)


def _spans(pattern, text, flags=0):
    return [m.span(1) for m in re.finditer(r'(?=(' + pattern + r'))', text, flags)]


def locate_citation(quote, text):
    if not isinstance(quote, str) or not quote.strip() or not isinstance(text, str): return None
    variants = [(quote, '')]
    if re.search(r'\\[nrt]', quote):
        rendered = quote.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\r', '\n').replace('\\t', '\t')
        variants.append((rendered, 'ESCAPED_LINE_BREAKS_AND_'))
    exact = _spans(re.escape(quote), text)
    if len(exact) > 1: return None
    if len(exact) == 1:
        start, end = exact[0]
        return Citation(start, end, text[start:end], quote, 'EXACT')
    # Case is never repaired: identifiers such as 'abc' and 'ABC' are distinct.
    tiers = (('WHITESPACE_ONLY', False, 0), ('WHITESPACE_AND_GLYPHS', True, 0))
    for name, glyphs, flags in tiers:
        for needle, prefix in variants:
            if not needle.strip(): continue
            matches = _spans(_pattern(needle, glyphs), text, flags)
            if len(matches) > 1: return None  # Ambiguity never improves with looser tiers.
            if len(matches) == 1:
                start, end = matches[0]
                label = prefix + name if prefix else name
                if prefix and name == 'WHITESPACE_ONLY': label = 'ESCAPED_LINE_BREAKS_AND_WHITESPACE'
                return Citation(start, end, text[start:end], quote, label)
    return None


def locate_citation_span(quote, prompt_text):
    citation = locate_citation(quote, prompt_text)
    return (citation.start, citation.end) if citation else None
