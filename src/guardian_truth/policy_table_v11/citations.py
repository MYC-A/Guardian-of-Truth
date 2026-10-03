"""Locate unambiguous source spans; presentation repair never supplies semantic evidence."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Citation:
    start: int
    end: int
    source_quote: str
    model_quote: str
    conversion: str


def locate_citation(quote, text):
    if not isinstance(quote, str) or not quote.strip() or not isinstance(text, str): return None
    def candidates(needle, whitespace=False):
        if whitespace:
            pieces = re.split(r'\s+', needle.strip())
            pattern = r'\s+'.join(map(re.escape, pieces))
        else: pattern = re.escape(needle)
        return [m.span(1) for m in re.finditer(r'(?=(' + pattern + r'))',text)]
    matches = candidates(quote)
    if len(matches) > 1: return None  # A first match is not a unique provenance anchor.
    conversion = 'EXACT'
    if not matches:
        matches = candidates(quote, True); conversion = 'WHITESPACE_ONLY'
    if not matches and re.search(r'\\[nr]', quote):
        # Repair only double-escaped line breaks, never general unicode escapes,
        # quote delimiters, casing, punctuation, spelling or semantic paraphrases.
        rendered = quote.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\r', '\n')
        matches = candidates(rendered, True); conversion = 'ESCAPED_LINE_BREAKS_AND_WHITESPACE'
    if len(matches) != 1: return None
    start,end = matches[0]
    return Citation(start,end,text[start:end],quote,conversion)


def locate_citation_span(quote, prompt_text):
    citation = locate_citation(quote, prompt_text)
    return (citation.start, citation.end) if citation else None
