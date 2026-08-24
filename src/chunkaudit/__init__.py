"""chunkaudit: the answers a chunker destroyed, which its own metrics cannot see.

A retrieval metric is computed on the chunks the chunker produced, so it cannot
see the answers the chunker destroyed. Every chunk holding part of an answer
counts as a hit, and no arrangement of hits says whether any single chunk could
have answered the question.

Whether a chunk holds an answer whole is a question about character offsets, so
it has an exact answer with no model in it. That gives a containment ceiling: the
highest span complete recall any retriever can ever reach on a chunking. It bounds
every retriever, including ones this package cannot run.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
