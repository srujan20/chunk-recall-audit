# ADR-002: Offsets rather than text

Status: accepted

## Context

An answer has to be represented somehow. The obvious choice is the text of the
answer, which is what every question answering dataset ships and what every
evaluation harness compares against.

Containment, though, is a question about position. Does this chunk, which covers
characters 4200 to 4600 of this document, hold all of the answer, which occupies
characters 4380 to 4790? Answering that from text means finding the answer inside
the chunk with a substring search.

## Decision

An answer is a half open character interval into a specific document. `Span` holds
two integers, `contains` and `overlaps` are interval comparisons, and the corpus
validates at construction that every answer lies inside its own document.

## The failure that made this non negotiable

A substring search finds the wrong copy whenever the corpus contains a near
duplicate, and this corpus contains near duplicates deliberately: every document
carries a distractor sentence with the question's key terms and none of its
answer. A text based containment check would have matched the distractor and
reported a hit.

There is a second, worse version of the same mistake, and this repository made it.
Spans were compared without checking they came from the same document. Offsets are
per document, so a chunk covering characters 0 to 800 of one document numerically
contains an answer at characters 100 to 500 of another. The result was a span
complete recall of 0.850 against a containment ceiling of 0.828.

That number could not be true. The ceiling is an upper bound by construction, so a
measured value above it is proof the measurement is wrong rather than news about
chunking. Both the fix and the invariant are now in the suite, and
`test_no_retriever_exceeds_the_ceiling` is the most valuable test in the
repository: it can only fail when a measurement is impossible.

## Alternatives considered

**Store the answer text and search for it.** Rejected for the near duplicate
reason above. It is also slower on long documents and gives no way to distinguish
two legitimate occurrences of the same answer.

**Store token indices rather than character offsets.** Rejected because the
tokeniser then becomes part of every published figure. Characters are the one unit
that every chunker, every retriever and every corpus agrees on.

**Store both, and check they agree.** Considered seriously, and rejected as a
weaker version of the invariant that already exists. The ceiling comparison
catches the same class of bug and catches more of it, because it is a statement
about the whole measurement rather than about one field.

## Consequences

The corpus must be generated or carefully annotated, which the README states as a
limitation rather than hiding.

Every comparison in `metrics.py` is fenced by the document identifier, and that
fencing is documented at the point of use rather than left as defensive coding, so
the next person to touch it knows what it prevents.
