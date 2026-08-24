# ADR-005: Every rate carries its denominator

Status: accepted

## Context

This repository publishes a lot of rates, and several of them are zero. Ten of the
thirteen chunkings have no retriever fixable failures at all. The oracle's
difference from the ceiling is zero on every configuration. The unattributable
count is zero everywhere.

A zero reported as a zero is an overclaim. Ten of thirteen chunkings having no
retriever fixable failure, measured over 360 questions, is a statement bounded by
what 360 questions can express. It is not evidence that the rate is below one in a
million.

## Decision

Three rules, two of them enforced by the type system rather than left to the
caller.

**A rate is a type, not a float.** `metrics.Rate` holds a numerator and a
denominator and exposes `value`, `floor`, `is_measured_zero` and
`samples_needed_for`. Every rate in every report is constructed through it, so the
denominator cannot be lost on the way to the page.

**A measured zero is reported with its floor.** The corpus has 360 questions, so
the floor is one in 360 and a measured zero supports "below 0.28 percent". exp05
prints the arithmetic for three stronger claims and how many questions each would
need, rather than leaving a zero to be read as an absence.

**A non finite rate serialises as null.** Two rates here are genuinely undefined
rather than zero: the share of failures a retriever could fix when nothing failed,
and the median share of an answer retrieved when there are no failures. Both come
out as a nan.

## The bug the third rule came from

A nan compares unequal to itself, so the determinism test failed on two sweeps
that were byte for byte identical in every other column. The first instinct was to
fix the test.

The test was right. A row that cannot be compared to itself is a row no downstream
check can trust, and `json.dumps` was writing the bare token `NaN`, which Python
reads back and nothing else does. `AuditRow.as_dict` now converts a non finite
float to null, which is both valid JSON and the truthful representation: the
number is missing, not zero.

## Alternatives considered

**Report zero and mention the corpus size in the README.** Rejected. The
denominator belongs next to the number, because the number is what gets quoted and
the README is what gets skimmed.

**Report confidence intervals on every rate.** Considered and deferred. It is the
better answer for a rate estimated from a sample of a population. Several rates
here are not estimates at all: the ceiling is exact for this corpus and chunking,
and an interval around it would suggest sampling error that does not exist. The
distinction between an exact rate and an estimated one is worth keeping visible,
and adding intervals uniformly would have blurred it.

**Substitute zero for nan and move on.** Rejected as the specific overclaim this
ADR exists to prevent. A share of no failures is not a share of zero.

## Consequences

Every table has a denominator in it or beside it, which is more to read.

The rule also shaped what the repository is willing to say. There is no claim here
of the form "this never happens", and there is one of the form "this did not
happen in 360 questions, which supports below 0.28 percent". The second is less
impressive and it is what the evidence carries.
