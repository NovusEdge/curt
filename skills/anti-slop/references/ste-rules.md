# Technical clarity

This file is a practical editing reference. It does not implement or certify
ASD-STE100 and does not require controlled English for general writing.

Keep a procedure's actor, trigger, condition, action, and consequence clear.
Preserve defaults, ordering, uncertainty, requirement strength, and exact syntax.
Use consistent technical terms. Expand shorthand when a reader cannot recover
its meaning from nearby context.

Keep related clauses together when their connection matters:
> If the server returns 429, wait for Retry-After before retrying; if the header
> is absent, wait 30 seconds.

Split a sentence when its nested clauses make the conditions hard to follow.
There is no word limit, ban on compound tense, or one-fact-per-sentence rule.
Passive voice is useful when the actor is unknown or irrelevant; name the actor
when its identity changes the reader's action.

For comments, explain an external constraint, ordering dependency, or reason
the code cannot express. Do not restate the code or invent a reason for it.

<!-- anti-slop: ignore-file -->
