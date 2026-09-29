"""Conservative scope vetoes. They never establish positive coreference."""
from __future__ import annotations

import re
from collections.abc import Callable


def explicit_atoms(text: str) -> set[str]:
    """Keep literal numeric/opaque tokens and uppercase one-letter labels.

    This is a negative signal only. No domain vocabulary or ID prefix list;
    matching atoms never prove that two mentions denote one occurrence.
    """
    return {token for token in re.findall(r'\b[A-Za-z0-9][A-Za-z0-9._:/-]*\b', text)
            if any(c.isdigit() for c in token)
            or (len(token) == 1 and token.isupper())}


def scope_conflict(left: list[str], right: list[str],
                   signature: Callable | None = None) -> bool:
    """A conflict in any pair cannot be hidden by an argument-less variant.

    Differing explicit atoms veto a merge. Where an existing proposer gives
    the same action signature, differing content arguments on BOTH sides
    veto its overlap heuristic too (including occurrence modifiers).
    One missing side remains unresolved; it is never positive scope proof.
    """
    for a in left:
        for b in right:
            aa, bb = explicit_atoms(a), explicit_atoms(b)
            if aa and bb and aa - bb and bb - aa:
                return True
            if signature is not None:
                pa, xa = signature(a)
                pb, xb = signature(b)
                if pa and pa == pb and xa and xb and xa - xb and xb - xa:
                    return True
    return False
