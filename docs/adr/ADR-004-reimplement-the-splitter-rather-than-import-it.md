# ADR-004: Reimplement the splitter rather than import it

Status: accepted

## Context

The chunker most pipelines reach for first is a recursive character splitter: try
a list of separators in order, take the first that yields pieces under the target
size, then glue consecutive pieces back together up to the target with some
overlap carried forward. It ships in the popular orchestration libraries and its
behaviour is documented.

This repository measures what chunkers destroy. So the chunker is not a dependency
here, it is the subject.

## Decision

Reimplement the documented behaviour in `chunking.recursive_spans`, and say in the
module docstring that it is a reimplementation rather than a port.

The reason is that a figure produced by an imported chunker is a statement about a
version number. "This configuration destroys 24 percent of answers" would mean
"destroys 24 percent as of the minor release installed on the machine that ran
CI", and a reader has no way to know which behaviour was measured. Reimplementing
it means the behaviour being measured is written down in the repository that
publishes the measurement.

## What is claimed and what is not

Claimed: this implementation splits at the coarsest separator that fits, merges
consecutive pieces up to the target size, carries the configured overlap forward,
and covers the input. Tests assert each of those.

Not claimed: byte for byte equivalence with any particular library. The README
says the recursive figures describe this implementation. Anyone wanting to audit
their own splitter can supply spans from it, because `ceiling.py` takes a
`Chunking` and does not care where the spans came from.

## Alternatives considered

**Import the library and pin the version.** Considered, and it is the pragmatic
choice for a production tool. Rejected here for the reason above, and for a
second: it would have added a large dependency tree to a package whose entire
runtime need is numpy and a YAML parser, in a repository whose selling point is
that the audit runs offline in under 10 seconds.

**Support only fixed and sentence windows, and skip recursive splitting.**
Rejected because recursive splitting is what most people are actually running, and
its results here are among the most useful in the plan: `recursive-800-600`
reaches a ceiling of 0.8278 against 0.7389 at eight hundred for a plain window of
the same size, because it respects sentence boundaries. Omitting it would have
left the comparison missing the option a reader is most likely to take.

**Wrap a pluggable interface and ship no chunker at all.** Rejected as scope. The
extension point already exists in the shape of `Chunking`, and shipping four
concrete strategies is what makes the comparison possible.

## Consequences

`recursive_spans` and its helper are the least glamorous code here and carry a
share of the test suite, because a bug in them silently changes every recursive
figure.

The reimplementation also made one behaviour explicit that is easy to miss when
importing: the overlap is carried from the end of the emitted chunk rather than
from the start of the next piece, which changes where boundaries land. Writing it
out forced that decision to be visible.
