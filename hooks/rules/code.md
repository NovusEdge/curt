ANTI-SLOP CODE DIRECTIVE. You are editing source. Fit the change to the goal and keep the comments factual.

Serve the outcome with taste. The target is the right amount of code to reach the goal well: correct, clear, and complete. Weigh completeness as heavily as restraint. Over-building and cutting a needed corner are the same failure in opposite directions.
- Match the change to what the goal needs. A bug fix stays clear of unrelated cleanup. A feature keeps the depth the outcome requires.
- Edit an existing file before you create a new one.
- Do not add an abstraction (interface, wrapper, factory, helper) for one call site. Inline first. Abstract at the third repeat.
- Add error handling where the failure is real: user input, external APIs, any trust boundary. Skip a guard for a case that cannot happen.
- YAGNI stops speculative features. It keeps the tests, the boundary validation, and the refactoring the goal needs.

A comment earns its place by carrying a fact the code cannot show: why a branch exists, what breaks if an order changes, a constraint from outside this file.
- No narrator comments. Delete "this function handles the request" and any comment that paraphrases the line below it.
- No step numbering in comments ("Step 1:", "First,", "Next,"). The code is the steps.
- No deferral prose ("for now", "in a real implementation", "we could add this later"). Write the code, or a TODO with an owner.
- No hedging ("this should work", "hopefully", "in theory").
- No investigation narrative ("originally we tried", "as you requested", "note that we now"). That belongs in the commit message.
- A docstring states what the caller cannot infer from the signature. It does not repeat the parameter list.
- No defensive wrapper around code that cannot throw. No catch that swallows the error.
- Tests assert behaviour, not mocks. No "assert True", no asserting a value against itself, no "assert_called" as the only check.
- Write the test before the code. A test written after the code asserts what already runs, bugs included. A test written first defines the behavior the code must satisfy.
- Test behavior at boundaries, not every line. A pure function with no branches needs one test. A function with three branches needs three. Coverage measures lines that ran, not bugs that would be caught.

Comments follow the prose guidance too: clear conditions, accurate claims, and useful context.

<!-- anti-slop: ignore-file (this file quotes the banned patterns) -->
