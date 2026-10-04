"""Research-only multi-packet evidence access over the U2 packer.

Packets are exact original spans (U2 records). Row-global source IDs make
claims from different packets comparable. Nothing here decides a verdict."""
from .packets import (complementary, specialized, gap_packet, oracle_packet, unify, resolve_global,
                      union_view, overlap_stats, reference_spans_covered)
from .ledger import Ledger, from_reply, programmatic_check
from .controller import Controller, Question
