# ADR-001: The ceiling is decided before retrieval

Status: accepted

## Context

A retrieval augmented pipeline has two stages that can lose an answer. The chunker
can cut it in half, and the retriever can fail to return the chunk that holds it.
Every metric in common use measures the pair together, on the chunks the chunker
produced, and reports one number.

That number cannot separate the two stages, and the reason is structural rather
than a matter of implementation quality. The metric is a function of the retrieved
chunks. Two questions that failed for entirely different reasons, one because no
chunk holds the answer whole and one because the chunk that does was ranked
eleventh, present identically to any such function.

## Decision

Compute the chunker's contribution first, separately, and with no model involved.

`ceiling.py` takes a chunking and a labelled answer span and asks whether any
chunk holds the span whole. That is an interval question with an exact answer.
Aggregated over the corpus it is the containment ceiling: the highest span
complete recall any retriever can reach on that chunking.

Both reports print the ceiling before any retrieval figure, because that is the
order the finding has. The ceiling is fixed by a decision already made, and every
retrieval number underneath it is conditional on that decision.

## Why this is the strongest claim in the repository

The ceiling bounds every retriever, not merely the ones tested. A retriever cannot
return a chunk that was never made, so the bound holds for BM25, for a dense
encoder, for a reranker, and for a method nobody has written yet.

That property is what makes the repository's central number robust to its largest
limitation. ADR-003 records that a dense transformer encoder was never run here,
because the model weights host was unreachable. The ceiling bounds it anyway.

The bound is also tight, which is a separate claim and is measured rather than
argued. An oracle that ranks by overlap with the answer attains the ceiling on
every chunking in the plan, with a worst absolute difference of 0.0. A loose bound
would have been much weaker: it would have said the ceiling is unreachable rather
than that it is the reachable maximum.

## Alternatives considered

**Report one blended metric and note the caveat in prose.** Rejected because the
caveat is the finding. Across 13 chunkings, 1661 of 1663 failures were the
chunker's and 2 were the retriever's, and a blended number would have presented
that as a retrieval result.

**Attribute failures statistically, by comparing retrievers.** Rejected as both
weaker and more expensive. Running several retrievers and attributing the residual
gives an estimate with an error bar, where the offsets give the answer.

**Require a real corpus before making any claim.** Rejected because it would have
removed the exactness rather than improving it. A real corpus has approximate
answer spans, and the argument here depends on the span being exact. ADR-002
covers that, and the README states which claims a generated corpus cannot support.

## Consequences

The audit needs labelled answer spans, which is a real cost: a team without them
gets the guarantee threshold arithmetic, which needs only an answer length
distribution, and not the ceiling.

The ceiling also costs nothing to compute. The whole sweep runs in under 10
seconds because there is no encoder in it. That turns out to be a selling point
rather than an implementation detail: the number that bounds every retriever a
team will ever try is available before it picks one.
