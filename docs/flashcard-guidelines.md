# Flashcard quality specification

This specification guides the implemented generation and independent review stages.
Refine it using a manually reviewed evaluation set,
recorded failure cases, and student feedback. Correctness takes precedence over
fluency, volume, or an automatic score.

## Requirements for every card

- **One retrieval target:** the learner should know what knowledge is being tested
  and what constitutes a complete answer. Split independent facts; retain a short
  tightly connected structure when splitting would remove essential meaning.
- **Unambiguous context:** state the relevant objects, domains, assumptions, and
  conventions. Avoid “this theorem,” unexplained symbols, and dependence on the
  previous card. A diagram may supply context if it is visible on the question.
- **Precise, concise answer:** include conditions and quantifiers needed for truth.
  Put intuition, proofs, examples, and optional derivations in a separate explanation
  field so the main answer remains assessable.
- **Faithful notation:** use consistent terminology and MathJax-compatible LaTeX
  (`\(...\)` inline, `\[...\]` displayed). Preserve subscripts, superscripts,
  operators, vector conventions, units, and logical scope. Check rendered output;
  visually similar symbols are not interchangeable.
- **Useful knowledge:** target definitions, distinctions, mechanisms, conditions,
  procedures, and transferable reasoning. Avoid trivial wording recognition, trivia,
  unsupported generalizations, and prompts so broad that self-grading is arbitrary.
- **Evidence:** attach the exact supporting document and location when available,
  including relevant figure/region references. Do not invent citations. Flag source
  conflict, uncertain transcription, and assumptions inferred beyond the source.
- **Reviewability:** keep factual verdict, pedagogical verdict, human status, and
  unresolved issues distinct. A plausible model answer is a candidate until checked.

Original diagrams should be preserved when spatial structure, a circuit, geometry,
or a graph materially helps understanding. Crops must retain needed labels, axes,
units, and context. Do not replace a precise source diagram with an invented image.
On image-based cards, avoid accidental answer cues and unreadable detail.

## Treatment by knowledge type

| Type | Recommended retrieval target | Frequent failure |
| --- | --- | --- |
| Definition | The defining properties under an explicit domain; a separate example/non-example if useful | Circular phrasing or omitting a universal quantifier |
| Theorem | A conclusion under stated hypotheses; separate applicability/assumption cards when useful | A true-looking conclusion with missing hypotheses |
| Conceptual distinction | Explain one mechanism or distinguish a named pair in context | “Explain everything about…” or answers requiring hidden conventions |
| Procedure | Choose a method, identify a critical step, or recall a short ordered procedure with applicability conditions | Memorizing a long worked solution without understanding method selection |
| Common mistake | Diagnose a concrete incorrect step and state the violated condition | Reinforcing a wrong claim without a clear correction |
| Cloze | Recover a meaningful term/condition in enough context to make one answer natural | Syntax cues, many unrelated blanks, or blanking an entire theorem |

Long proofs rarely fit a single card. Use a key lemma, the reason for a transition,
or the proof strategy, with enough assumptions to make the expected answer clear.
Some coherent targets require a small list (for example, the axioms of a named
structure); avoid splitting them into cards that lose their intended relationship.

## How exercises inform the deck

Exercise frequency and prerequisites are evidence of importance, not an automatic
card quota. Compare exercises with lecture goals and distinguish core topics from
incidental arithmetic. Extract method-selection cues, reusable invariants, important
boundary cases, and common mistakes. A worked solution can support a derivation
but can itself contain errors; verify it against definitions and assumptions.

Prefer “When is this method applicable?” or “Why does this step follow?” to asking
for the final numerical answer to exercise 7. Use small novel examples to test
transfer. Keep computational burden low enough that retrieval remains practical;
long multi-step problem solving belongs in separate practice material.

## Examples

The examples below demonstrate wording and answer quality. Production cards also
need actual source links and recorded verification; these examples do not assert
provenance to any university material.

### Mathematical definition

**Poor:** “What is continuity?” — “Small changes give small changes.”

**Better question:** For \(f:\mathbb R\to\mathbb R\), state continuity at
\(a\in\mathbb R\) using \(\varepsilon\) and \(\delta\).

**Answer:** For every \(\varepsilon>0\), there exists \(\delta>0\) such that
for every \(x\in\mathbb R\), \(|x-a|<\delta\) implies
\(|f(x)-f(a)|<\varepsilon\).

**Why:** The domain, point, and quantifier order are explicit. Intuition belongs
in the optional explanation, not in place of the definition.

### Theorem conditions

**Poor:** “Does a continuous function have a maximum?” — “Yes.”

**Better question:** If \(f:[a,b]\to\mathbb R\) is continuous and
\(a\le b\) are finite real numbers, must \(f\) attain a maximum?

**Answer:** Yes. It attains a maximum on the compact interval \([a,b]\).

**Optional explanation:** Compactness matters: \(f(x)=x\) on \((0,1)\)
has no maximum. A separate card can test why the missing endpoint matters.

### Probability and a common error

**Poor:** “What is \(P(A\mid B)\)?” — “\(P(A)\).”

**Better question:** For events \(A,B\) with \(P(B)>0\), what is the
definition of \(P(A\mid B)\)?

**Answer:** \(P(A\mid B)=P(A\cap B)/P(B)\).

**Optional explanation:** It equals \(P(A)\) when \(A\) and \(B\) are
independent. Do not collapse that assumption into the general definition.

### Programming procedure

**Poor:** “How does binary search work?” — a page of code and edge cases.

**Better question:** When searching a sorted ascending array, why can binary search
discard all entries left of and including the midpoint if the midpoint value is
less than the target?

**Answer:** Every discarded value is at most the midpoint value, so each is less
than the target.

**Why:** This tests the invariant behind one decision. Separate cards may test
sortedness, interval conventions, or termination; the answer does not depend on an
unstated implementation's index convention.

### Electrical engineering

**Poor:** “What is the capacitor impedance?” — “\(1/C\).”

**Better question:** Under the sinusoidal steady-state convention
\(e^{j\omega t}\), what is the impedance of an ideal capacitor with capacitance
\(C>0\) at \(\omega>0\), using the passive sign convention?

**Answer:** \(Z_C=1/(j\omega C)\), in ohms when \(\omega\) is in
rad/s and \(C\) in farads.

**Why:** The model, phasor convention, and operating regime make the formula precise.
An optional explanation can connect it to \(i=C\,dv/dt\).

### Cloze and transfer

**Poor:** “The answer to exercise 4 is {{c1::0.25}}.”

**Better:** For independent events \(A\) and \(B\),
\(P(A\cap B)=\) {{c1::\(P(A)P(B)\)}}.

The latter retrieves a reusable relationship under its stated condition. An
additional conceptual question should distinguish independence from disjointness
if that confusion appears in the course; repeating the same formula in several
wordings adds little value.

## Review and evaluation

Review the question before reading its answer: is the intended response clear?
Then check source fidelity, mathematical correctness, assumptions, answer scope,
rendering, and usefulness. Compare nearby cards for duplicates and missing targets.
Human corrections should record the defect category, not just replace the text.

Track factual accuracy, target coverage, ambiguity, redundancy, and human acceptance
rate on a held-out reviewed set. Define denominators and sampling rules; a high
score cannot excuse a known wrong card. Initial thresholds and reviewer agreement
should be established with the evaluation milestone in the [roadmap](roadmap.md).
