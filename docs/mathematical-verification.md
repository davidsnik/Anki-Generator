# Bounded mathematical verification

`processing.mathematics.check_identity` retains its compatibility name while
supporting typed `SymbolicCheck.operation` values. Every result distinguishes its
calculation status from source transcription and human judgment. `formal_proof`
and `claim_human_verified` are always false. A passing calculation does not establish
that the mathematical claim, context, theorem assumptions or source reading is true.

| Operation | Checked behavior | Scope |
| --- | --- | --- |
| identity / simplify | Safe symbolic equivalence | Explicit declared symbols/domains; unresolved restrictions remain uncertain |
| differentiate | Derivative of `lhs` equals `rhs` with respect to `variable` | Algebraic and whitelisted scalar functions |
| integrate | Derivative of proposed antiderivative `rhs` reproduces integrand `lhs` | Additive constants are unspecified; this is an antiderivative check |
| integrate with bounds | Definite integral between ordered real constant bounds equals `rhs` | Supported variable assumptions must hold on the closed interval; divergent, conditional, piecewise or unevaluated results remain uncertain |
| matrix_multiply | Product of `lhs` and `matrix_b` equals `rhs` | Literal rectangular matrices up to 6x6; incompatible shapes are rejected |
| matrix_shape | Shape of `lhs` equals `[rows,columns]` in `rhs` | Dimension calculation only |
| matrix_transpose | Transposed `lhs` equals `rhs` | Literal matrices |
| matrix_determinant | Determinant equals `rhs` | Square matrices up to 4x4 |
| probability | Algebraic identity in declared probability symbols | Event independence and probability-model semantics still require reasoning/review |
| optimization_stationary | Derivative vanishes at the real constant point in `rhs` | Checks supported sign/nonzero assumptions at that point; does not establish general feasibility, a minimum, maximum or global optimality |
| counterexample | Deterministic bounded numerical substitutions | A found valid counterexample refutes the submitted calculation; absence is never proof |

The parser constructs SymPy objects from a restricted Python AST. It never calls
`eval`, `parse_expr`, or `sympify` on untrusted strings. Supported scalar functions
are `sin`, `cos`, `tan`, `exp`, `log`, `sqrt` and `Abs`; constants include `pi` and `E`.
Variables must be explicitly declared. Integer powers, expression length, syntax
nodes, nesting, composed degree, matrix size and numeric literals are bounded.
Attributes, arbitrary calls, comprehensions, imports and undeclared names are rejected.

Supported machine assumptions use an explicitly declared variable compared with
zero: `x>0`, `x>=0`, `x!=0`, `x<0`, or `x<=0`. Other assumption prose is retained as
unresolved, not guessed. Real and complex scalar domains are selectable. Divisions,
negative powers, square roots, logarithms and tangent introduce explicit domain
restrictions unless justified by supported symbol assumptions. For example,
`x/x=1` without `x!=0` stays uncertain; cancellation must not erase the excluded point.
Likewise `sqrt(x*x)=x` has a negative real counterexample unless positivity is stated.

Assumptions also constrain where a calculation may be evaluated. Before checking a
stationary point, the verifier establishes that the point satisfies supported
sign/nonzero assumptions on the selected variable. Before a definite integral,
those assumptions must hold throughout the closed interval. This check happens
before assumption-dependent simplifications can be used to certify the answer.
For example, `x/x` under `x!=0` cannot have a verified stationary-point calculation
at zero; `sqrt(x*x)` under `x>0` cannot be simplified to `x` and integrated over
`[-1,1]`. Such requests return `uncertain` / `domain_unresolved`, with the offending
assumptions and point/bounds retained. This does not establish the answer to a
different calculation over a larger domain. Improper integrals or excluded
endpoints are conservatively unresolved: even the finite integral of `x` from
zero to one is not certified under the strict assumption `x>0`; the corresponding
closed interval is supported under `x>=0`.

Checks run in spawned subprocesses with wall-clock, CPU and address-space budgets.
Timeouts, unsafe inputs and unsupported mathematics return uncertainty. Results use
`calculation_verified`, `counterexample_found`, `calculation_mismatch`, `shape_mismatch`, `domain_unresolved`,
`not_proven`, `unsupported` or `resource_limit`, alongside pass/revise/uncertain for
pipeline gating. Relevant source evidence, assumptions, substitutions and reasons
remain inspectable with the checked card revision. Independent factual,
pedagogical and mathematical model reviews remain separate stages; human review is
recorded separately and no revision limit converts uncertainty into approval.

Synthetic offline tests exercise correct/incorrect derivatives, integration,
matrices, probability arithmetic, stationary points, strict domains, branch errors,
counterexamples and adversarial syntax. They do not measure real-world theorem
verification or expert agreement on university material.

## Measured domain-boundary regression controls

The 2026-11-09 investigation preserved an untouched baseline and ran the same
developer engineering collector against both implementations. Its three authored
controls contain the two invalid-domain examples above and a valid integral of
`sqrt(x*x)` over `[1,2]` under `x>0`, with proposed result `3/2`.

| Control | Baseline decision | Improved decision |
| --- | --- | --- |
| Stationary point zero for `x/x`, with `x!=0` | `calculation_verified` | `domain_unresolved` |
| Integral of `sqrt(x*x)` over `[-1,1]`, with `x>0`, proposed result zero | `calculation_verified` | `domain_unresolved` |
| Integral of `sqrt(x*x)` over `[1,2]`, with `x>0`, proposed result `3/2` | `calculation_verified` | `calculation_verified` |

Expected control decisions changed from **1/3 to 3/3**. This is evidence that the
specific unsafe domain approvals were removed while the valid calculation still
works. It is not an academic accuracy rate, a university benchmark result, model
agreement or human validation. The collector calls the underlying bounded
calculation semantics; separate regression tests exercise the actual spawned
worker, resource limits and pipeline gating.

The immutable local artifacts are
`data/benchmarks/engineering/baseline-2026-11-09.json` and
`data/benchmarks/engineering/improved-2026-11-09.json`, with source hashes and a
readable `comparison.md`. They are Git-ignored developer outputs. Reproduce the
current offline controls with
`make benchmark-engineering ARGS='--output data/benchmarks/engineering/new-controls.json'`;
choose a new output path because existing measurements are not overwritten.
