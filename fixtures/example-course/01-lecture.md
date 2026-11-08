# Lecture 1: Conditional probability and indicator variables

This synthetic course uses a probability space with events A and B.

## Conditional probability

If P(B) > 0, then

\[
P(A \mid B) = \frac{P(A \cap B)}{P(B)}.
\]

Conditioning restricts attention to outcomes in B. The condition P(B) > 0 matters:
this elementary ratio does not define conditioning on an event of probability zero.

## Independence

Events A and B are independent exactly when

\[
P(A \cap B) = P(A)P(B).
\]

When P(B) > 0, independence is equivalent to P(A | B) = P(A).
Disjoint events of positive probability are not independent: their intersection
has probability zero while the product of their probabilities is positive.

## Bernoulli and indicator variables

A Bernoulli random variable X with parameter p in [0, 1] satisfies
P(X = 1) = p and P(X = 0) = 1 - p. Its expectation is E[X] = p.

For an event A, its indicator 1_A equals one on A and zero elsewhere, so
E[1_A] = P(A). Linearity of expectation gives E[X + Y] = E[X] + E[Y] for
integrable random variables X and Y; independence is not required.
