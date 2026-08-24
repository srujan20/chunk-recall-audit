# ADR-003: The encoder this build could not reach

Status: accepted

## Context

The question people ask about chunking is a question about dense retrieval. A
repository on this subject with no transformer encoder in it invites the obvious
objection: perhaps a good embedding model finds the complete chunk anyway.

The environment this repository was built in cannot reach the model weights host.
A request to `huggingface.co` returns 403 through the egress allowlist. The
package installs; the weights do not download.

Three options followed. Pretend, by presenting a lexical vectoriser as a dense
encoder. Omit, by saying nothing about dense retrieval. Or state the boundary and
show why the central claim survives it.

## Decision

State it, in three places, and make the argument for why it does not matter to the
headline.

**In the code.** `sentence_transformer_rankings` is written, fenced behind an
optional extra, and listed in `WRITTEN_NOT_RUN` rather than in `RUNNABLE`. Its
argument validation runs above the import, so a caller passing an empty model name
hears about the name rather than about a missing package. A test makes the module
unimportable and asserts both behaviours.

**In the tool's own output.** `chunkaudit plan` prints "written and never run in
this environment" with a pointer to this ADR. A disclosure that lives only in a
document is a disclosure the user of the tool never sees.

**In the README**, in its own section rather than a footnote.

## Why the headline survives

The containment ceiling bounds every retriever. A retriever cannot return a chunk
that was never made, so the bound holds for a dense encoder exactly as it holds
for BM25. On 200 character chunks the ceiling is 0.2917, and that is the maximum a
transformer could reach, not an estimate of what one would reach.

The oracle result closes the argument. An oracle that ranks by overlap with the
answer attains the ceiling on every chunking, with a worst absolute difference of
0.0. Since the oracle already reaches the bound and a transformer cannot exceed
it, the space a transformer could occupy is fully described by numbers already in
this repository.

## What the missing encoder genuinely costs

One claim, and it is named rather than glossed. Claim 6 in the README reports that
changing the retriever moves span complete recall by at most 0.1972 while changing
the chunker moves it by up to 0.7917. That retriever range is measured over two
lexical methods. A dense encoder could plausibly widen it, particularly on the
sentence level chunkings where the hashed vectoriser does badly on short texts.
The ratio of 4 times as far is therefore an upper estimate of the chunker's
relative importance, not a settled figure.

That is the honest statement, and it is why the claim is worded as a comparison of
levers rather than as a dismissal of retrieval work.

## Alternatives considered

**Call the hashed vectoriser a dense encoder.** Refused. It hashes character n
grams into a fixed number of dimensions with inverse document frequency weighting.
That is a real retrieval method with real behaviour on morphology and misspellings,
and it is not a neural encoder, and no file in this repository says otherwise.

**Commit precomputed embeddings from a real model.** Would have been the right
answer, and it was not available: the weights could not be downloaded to compute
them.

**Drop dense retrieval from the design entirely.** Rejected because the code path
is worth having for the person who runs this with network access, and because the
ordering it forces, validation above the optional import, is worth having as
working code.

## Consequences

The dense path is unexercised. A user who installs the extra is the first person
to run those lines, and that is stated here rather than implied.

The repository is also honest in a way that is checkable: `RUNNABLE` and
`WRITTEN_NOT_RUN` are separate tuples, a test asserts the dense retriever is in
the second and not the first, and the CLI prints the distinction.
