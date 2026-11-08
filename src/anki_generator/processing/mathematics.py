"""Small safe symbolic identity checks, never arbitrary Python/SymPy parsing."""

from __future__ import annotations

import ast
import re
from typing import Any

from .contracts import SymbolicCheck


class UnsafeExpression(ValueError):
    pass


def check_identity(check: SymbolicCheck) -> dict[str, Any]:
    """Check bounded rational/polynomial expressions with explicit symbols.

    No eval, sympify(string), parse_expr, imports, attributes or function calls.
    Domain assumptions are recorded but are not inferred as formal theorem proof.
    """
    import sympy

    if len(check.variables) > 6 or any(
        not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,20}", v) for v in check.variables
    ):
        return {"verdict": "uncertain", "reason": "Unsupported symbol declaration."}
    symbols = {name: sympy.Symbol(name) for name in check.variables}

    def parse(text: str) -> Any:
        if len(text) > 300:
            raise UnsafeExpression("Expression exceeds the symbolic-check limit.")
        tree = ast.parse(text.replace("^", "**"), mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 80:
            raise UnsafeExpression("Expression is too complex for a bounded identity check.")

        def complexity(node: ast.AST) -> int:
            if isinstance(node, ast.Name):
                return 1
            if isinstance(node, ast.Constant):
                return 0
            if isinstance(node, ast.Expression):
                return complexity(node.body)
            if isinstance(node, ast.UnaryOp):
                return complexity(node.operand)
            if isinstance(node, ast.BinOp):
                left, right = complexity(node.left), complexity(node.right)
                if isinstance(node.op, (ast.Add, ast.Sub)):
                    degree = max(left, right)
                elif isinstance(node.op, ast.Pow):
                    if (
                        not isinstance(node.right, ast.Constant)
                        or type(node.right.value) is not int
                    ):
                        raise UnsafeExpression("Only literal small powers are supported.")
                    degree = left * abs(node.right.value)
                else:
                    degree = left + right
                if degree > 8:
                    raise UnsafeExpression(
                        "Polynomial/rational degree exceeds the safe check budget."
                    )
                return degree
            raise UnsafeExpression("Unsupported expression syntax.")

        complexity(tree)

        def visit(node: ast.AST) -> Any:
            if isinstance(node, ast.Expression):
                return visit(node.body)
            if isinstance(node, ast.Name) and node.id in symbols:
                return symbols[node.id]
            if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
                if len(str(node.value)) > 25 or not (-1e12 <= node.value <= 1e12):
                    raise UnsafeExpression("Numeric literal exceeds limits.")
                return sympy.Rational(str(node.value))
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                result = visit(node.operand)
                return result if isinstance(node.op, ast.UAdd) else -result
            if isinstance(node, ast.BinOp) and isinstance(
                node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
            ):
                left, right = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                if isinstance(node.op, ast.Div):
                    if right == 0:
                        raise UnsafeExpression("Division by zero.")
                    return left / right
                if not right.is_Integer or abs(int(right)) > 8:
                    raise UnsafeExpression("Only small integer powers are supported.")
                return left**right
            raise UnsafeExpression(
                "Unsupported expression syntax; requires independent mathematical review."
            )

        return visit(tree)

    try:
        lhs, rhs = parse(check.lhs), parse(check.rhs)
        difference = sympy.cancel(lhs - rhs)
        if difference == 0:
            return {
                "verdict": "pass",
                "reason": "Symbolic equality holds where both expressions "
                "are defined; domain/assumptions still require independent review.",
                "formal_proof": False,
            }
        return {
            "verdict": "revise",
            "reason": "The proposed symbolic equality does not hold "
            "identically for the declared unconstrained symbols.",
            "formal_proof": False,
        }
    except (UnsafeExpression, SyntaxError, ValueError, TypeError, ZeroDivisionError):
        return {
            "verdict": "uncertain",
            "reason": "This expression cannot be checked safely by "
            "the bounded symbolic checker; independent review is required.",
            "formal_proof": False,
        }
