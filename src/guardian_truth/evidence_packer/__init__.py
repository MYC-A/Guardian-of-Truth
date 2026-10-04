"""Universal, budgeted evidence packing for single-move verification.

See ``packer.pack`` and docs/evidence_packer_v1/README.md.
"""
from .packer import PackerConfig, pack, build_units
from .embed import Embedder, FastEmbedEmbedder, NoEmbedder

__all__ = ['PackerConfig', 'pack', 'build_units', 'Embedder', 'FastEmbedEmbedder', 'NoEmbedder']
