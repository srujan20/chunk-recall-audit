"""Error types, separated so the CLI can map a failure to an exit code.

The distinction the exit codes exist to keep is between "the sweep's reported
best survived correction" and "the log cannot support an answer". A tool that
returns the same code for both is a tool whose zero means nothing.
"""

from __future__ import annotations


class SweepshrinkError(Exception):
    """Base class for every error this package raises deliberately."""


class UsageError(SweepshrinkError):
    """The caller asked for something the tool does not offer. Exit code 4."""


class UnanswerableError(SweepshrinkError):
    """The inputs are valid in form and cannot support an answer. Exit code 3.

    Raised for a corpus with no questions, an answer span that lies outside its
    document, or a chunking that produced no chunks for a document that has
    text in it.
    """


class PolicyError(SweepshrinkError):
    """The policy file is missing a key or holds a value out of range. Exit 4."""


class MissingDependencyError(SweepshrinkError):
    """An optional estimator family was asked for and is not installed. Exit 4.

    Raised for the sentence-transformers encoder, which is written and, in the
    environment this repository was built in, never run: the model weights host
    is not reachable. ADR-003 says which claim that affects, and why the headline
    claim is not one of them.
    """
