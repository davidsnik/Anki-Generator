"""Resource-bounded calculation checks with explicit domains, never general proofs."""

from __future__ import annotations

import ast
import json
import multiprocessing
import os
import random
import re
import tempfile
from pathlib import Path
from typing import Any

from .contracts import SymbolicCheck


class UnsafeExpression(ValueError):
    pass


def _result(verdict: str, status: str, reason: str, **details: Any) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "calculation_status": status,
        "reason": reason,
        "formal_proof": False,
        "claim_human_verified": False,
        "scope": "Bounded calculation only; "
        "source transcription and theorem assumptions are separate.",
        **details,
    }


def _calculate(check: SymbolicCheck) -> dict[str, Any]:
    import sympy as sp
    from sympy.matrices import MatrixBase

    if (
        len(check.variables) > 6
        or len(set(check.variables)) != len(check.variables)
        or any(
            not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,20}", v) or v in {"pi", "E", "I"}
            for v in check.variables
        )
    ):
        raise UnsafeExpression("Unsupported symbol declaration")
    declared: dict[str, dict] = {name: {check.domain: True} for name in check.variables}
    unresolved = []
    parsed_assumptions = []
    for condition in check.assumptions:
        match = re.fullmatch(r"\s*([A-Za-z][A-Za-z0-9_]*)\s*(>=|<=|!=|>|<)\s*0\s*", condition)
        if not match or match[1] not in declared or (check.domain != "real" and match[2] != "!="):
            unresolved.append(condition)
            continue
        if check.domain == "complex" and match[2] == "!=":
            declared[match[1]]["zero"] = False
            parsed_assumptions.append(condition)
            continue
        prop = {
            ">": "positive",
            ">=": "nonnegative",
            "!=": "nonzero",
            "<": "negative",
            "<=": "nonpositive",
        }[match[2]]
        declared[match[1]][prop] = True
        parsed_assumptions.append(condition)
    symbols = {name: sp.Symbol(name, **properties) for name, properties in declared.items()}

    def interval_domain_violations(variable, lower, upper) -> list[str]:
        """Establish supported assumptions on the entire closed evaluation set.

        SymPy may simplify using x>0 before substitution/integration. Checking only
        the simplified answer would incorrectly certify evaluations at x=0 or on
        a negative interval. Unsupported/improper endpoint cases stay unresolved.
        """
        violations = []
        for condition in parsed_assumptions:
            match = re.fullmatch(r"\s*([A-Za-z][A-Za-z0-9_]*)\s*(>=|<=|!=|>|<)\s*0\s*", condition)
            if match[1] != str(variable):
                continue
            relation = match[2]
            holds = {
                ">": lower.is_positive is True,
                ">=": lower.is_nonnegative is True,
                "<": upper.is_negative is True,
                "<=": upper.is_nonpositive is True,
                "!=": lower.is_positive is True or upper.is_negative is True,
            }[relation]
            if not holds:
                violations.append(condition)
        return violations

    functions = {
        "sin": sp.sin,
        "cos": sp.cos,
        "tan": sp.tan,
        "exp": sp.exp,
        "log": sp.log,
        "sqrt": sp.sqrt,
        "Abs": sp.Abs,
    }
    domain_restrictions = []

    def parse(text: str) -> Any:
        if len(text) > 1200:
            raise UnsafeExpression("Expression exceeds the bounded length")
        tree = ast.parse(text.replace("^", "**"), mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 180:
            raise UnsafeExpression("Expression exceeds the bounded syntax budget")

        def degree(node: ast.AST) -> int:
            if isinstance(node, ast.Name):
                return 1
            if isinstance(node, ast.Constant):
                return 0
            if isinstance(node, ast.BinOp):
                left, right = degree(node.left), degree(node.right)
                if isinstance(node.op, ast.Pow):
                    if (
                        not isinstance(node.right, ast.Constant)
                        or type(node.right.value) is not int
                    ):
                        raise UnsafeExpression("Only literal powers are supported")
                    value = left * abs(node.right.value)
                elif isinstance(node.op, (ast.Add, ast.Sub)):
                    value = max(left, right)
                else:
                    value = left + right
                if value > 16:
                    raise UnsafeExpression("Composed algebraic degree exceeds the safe budget")
                return value
            return max((degree(child) for child in ast.iter_child_nodes(node)), default=0)

        degree(tree)

        def visit(node: ast.AST, depth: int = 0) -> Any:
            if depth > 14:
                raise UnsafeExpression("Expression nesting exceeds budget")

            def child(item: ast.AST) -> Any:
                return visit(item, depth + 1)

            if isinstance(node, ast.Expression):
                return child(node.body)
            if isinstance(node, ast.Name):
                if node.id in symbols:
                    return symbols[node.id]
                if node.id == "pi":
                    return sp.pi
                if node.id == "E":
                    return sp.E
                raise UnsafeExpression("Undeclared symbol")
            if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
                if len(str(node.value)) > 25 or not -1e12 <= node.value <= 1e12:
                    raise UnsafeExpression("Numeric literal exceeds bounds")
                return sp.Rational(str(node.value))
            if isinstance(node, ast.List):
                if (
                    not node.elts
                    or len(node.elts) > 6
                    or not all(isinstance(row, ast.List) for row in node.elts)
                ):
                    raise UnsafeExpression(
                        "Only rectangular matrix literals of at most 6x6 are supported"
                    )
                widths = [len(row.elts) for row in node.elts]
                if len(set(widths)) != 1 or not 1 <= widths[0] <= 6:
                    raise UnsafeExpression("Matrix rows have inconsistent dimensions")
                return sp.Matrix([[child(item) for item in row.elts] for row in node.elts])
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = child(node.operand)
                return value if isinstance(node.op, ast.UAdd) else -value
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in functions
            ):
                if len(node.args) != 1 or node.keywords:
                    raise UnsafeExpression(
                        "Only single-argument whitelisted functions are supported"
                    )
                value = child(node.args[0])
                if isinstance(value, MatrixBase):
                    raise UnsafeExpression("Scalar functions do not accept matrices")
                if (
                    node.func.id == "sqrt"
                    and check.domain == "real"
                    and value.is_nonnegative is not True
                ):
                    domain_restrictions.append(f"{value} >= 0")
                if (
                    node.func.id == "log"
                    and check.domain == "real"
                    and value.is_positive is not True
                ):
                    domain_restrictions.append(f"{value} > 0")
                if (
                    node.func.id == "log"
                    and check.domain == "complex"
                    and value.is_zero is not False
                ):
                    domain_restrictions.append(f"{value} != 0")
                if node.func.id == "tan":
                    domain_restrictions.append(f"cos({value}) != 0")
                return functions[node.func.id](value)
            if isinstance(node, ast.BinOp) and isinstance(
                node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
            ):
                left, right = child(node.left), child(node.right)
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                if isinstance(node.op, ast.Div):
                    if right == 0:
                        raise UnsafeExpression("Division by zero")
                    if not isinstance(right, MatrixBase) and right.is_zero is not False:
                        domain_restrictions.append(f"{right} != 0")
                    return left / right
                if (
                    not isinstance(node.right, ast.Constant)
                    or type(node.right.value) is not int
                    or abs(node.right.value) > 8
                ):
                    raise UnsafeExpression("Only small literal integer powers are supported")
                if node.right.value < 0 and left.is_zero is not False:
                    domain_restrictions.append(f"{left} != 0")
                value = left**right
                if sp.count_ops(value) > 250:
                    raise UnsafeExpression("Expression operation budget exceeded")
                return value
            raise UnsafeExpression(
                "Unsupported expression syntax; no attributes or arbitrary functions are allowed"
            )

        return visit(tree)

    lhs = parse(check.lhs)
    operation = check.operation
    if operation == "matrix_shape":
        shape = ast.literal_eval(check.rhs)
        if (
            not isinstance(shape, (tuple, list))
            or len(shape) != 2
            or not all(type(v) is int for v in shape)
        ):
            raise UnsafeExpression("Expected matrix shape [rows, columns]")
        if not isinstance(lhs, MatrixBase):
            raise UnsafeExpression("Matrix shape requires a matrix literal")
        valid = tuple(shape) == lhs.shape
        return _result(
            "pass" if valid else "revise",
            "calculation_verified" if valid else "shape_mismatch",
            f"Actual matrix shape is {lhs.rows}x{lhs.cols}.",
            shape=list(lhs.shape),
        )
    rhs = parse(check.rhs)
    variable = symbols.get(check.variable or (check.variables[0] if check.variables else ""))
    if operation in {"differentiate", "integrate", "optimization_stationary"} and (
        variable is None or (check.variable is None and len(check.variables) != 1)
    ):
        raise UnsafeExpression("Declare the differentiation/integration variable")
    description = "Algebraic equality under the explicit supported domain"
    if operation == "differentiate":
        lhs = sp.diff(lhs, variable)
        description = "Symbolic derivative matches the proposed expression"
    elif operation == "integrate":
        if check.bounds:
            lower, upper = [parse(value) for value in check.bounds]
            if (
                lower.free_symbols
                or upper.free_symbols
                or not (lower.is_real and upper.is_real and lower <= upper)
            ):
                raise UnsafeExpression("Definite integration requires ordered real constant bounds")
            violations = interval_domain_violations(variable, lower, upper)
            if violations:
                return _result(
                    "uncertain",
                    "domain_unresolved",
                    "The integration interval leaves the declared domain; "
                    "assumption-dependent simplifications cannot verify this integral",
                    operation=operation,
                    assumptions_violated=violations,
                    evaluation_bounds=[str(lower), str(upper)],
                )
            lhs = sp.integrate(lhs, (variable, lower, upper))
            if lhs.has(sp.Integral, sp.Piecewise, sp.zoo, sp.oo, -sp.oo, sp.nan):
                return _result(
                    "uncertain",
                    "domain_unresolved",
                    "Integral is conditional, unevaluated or divergent",
                )
            description = "Bounded definite symbolic integral matches the proposed result"
        else:
            lhs, rhs = sp.diff(rhs, variable), lhs
            description = (
                "Differentiating the proposed antiderivative reproduces the integrand; "
                "additive constants are unspecified"
            )
    elif operation == "matrix_multiply":
        if not check.matrix_b:
            raise UnsafeExpression("Matrix multiplication needs matrix_b")
        second = parse(check.matrix_b)
        if not isinstance(lhs, MatrixBase) or not isinstance(second, MatrixBase):
            raise UnsafeExpression("Matrix multiplication requires literal matrices")
        if lhs.cols != second.rows:
            return _result(
                "revise",
                "shape_mismatch",
                "Inner matrix dimensions do not agree",
                left_shape=list(lhs.shape),
                right_shape=list(second.shape),
            )
        lhs = lhs * second
        description = "Matrix product, including shape consistency, matches"
    elif operation == "matrix_transpose":
        if not isinstance(lhs, MatrixBase):
            raise UnsafeExpression("Transpose requires a matrix")
        lhs = lhs.T
    elif operation == "matrix_determinant":
        if not isinstance(lhs, MatrixBase) or lhs.rows != lhs.cols or lhs.rows > 4:
            raise UnsafeExpression("Determinant supports square matrices up to 4x4")
        lhs = lhs.det()
    elif operation == "optimization_stationary":
        # RHS is the claimed stationary point; this checks f'(point)=0 only.
        if rhs.free_symbols or rhs.is_real is not True:
            raise UnsafeExpression("Stationary-point check requires a real constant candidate")
        violations = interval_domain_violations(variable, rhs, rhs)
        if violations:
            return _result(
                "uncertain",
                "domain_unresolved",
                "The proposed stationary point lies outside the declared domain",
                operation=operation,
                assumptions_violated=violations,
                evaluation_point=str(rhs),
            )
        lhs, rhs = sp.diff(lhs, variable).subs(variable, rhs), sp.Integer(0)
        description = (
            "Derivative vanishes at the stated point; "
            "minimum/maximum/global optimality is not established"
        )
    if isinstance(lhs, MatrixBase) != isinstance(rhs, MatrixBase):
        return _result("revise", "shape_mismatch", "A matrix and scalar cannot be equal")
    if isinstance(lhs, MatrixBase):
        if lhs.shape != rhs.shape:
            return _result("revise", "shape_mismatch", "Matrix result has a different shape")
        differences = [sp.simplify(value) for value in lhs - rhs]
        equal = all(value == 0 for value in differences)
        if any(not value.free_symbols and value.is_zero is False for value in differences):
            return _result(
                "revise",
                "calculation_mismatch",
                "Exact matrix calculation disagrees with the proposed result",
            )
    else:
        equal = sp.simplify(lhs - rhs) == 0
    details = {
        "operation": operation,
        "domain": check.domain,
        "assumptions_checked": parsed_assumptions,
        "unresolved_assumptions": unresolved,
        "domain_restrictions": sorted(set(domain_restrictions)),
    }
    if unresolved or domain_restrictions:
        return _result(
            "uncertain",
            "domain_unresolved",
            "Calculation has unsupported assumptions or unresolved domain restrictions",
            **details,
        )
    if equal and operation != "counterexample":
        return _result("pass", "calculation_verified", description, **details)
    # Counterexamples refute only the submitted calculation under declared domains;
    # failure to find one is never promoted into proof.
    if not isinstance(lhs, MatrixBase):
        rng = random.Random(0)
        sample_values = [
            sp.Integer(-3),
            sp.Integer(-1),
            sp.Rational(-1, 2),
            sp.Integer(0),
            sp.Rational(1, 2),
            sp.Integer(1),
            sp.Integer(2),
            sp.Integer(3),
        ]
        for _ in range(160):
            values = {}
            for symbol in symbols.values():
                allowed = [
                    v
                    for v in sample_values
                    if not (
                        symbol.is_positive
                        and v <= 0
                        or symbol.is_nonnegative
                        and v < 0
                        or symbol.is_negative
                        and v >= 0
                        or symbol.is_nonpositive
                        and v > 0
                        or symbol.is_nonzero
                        and v == 0
                    )
                ]
                values[symbol] = rng.choice(allowed)
            left, right = lhs.subs(values), rhs.subs(values)
            if left.is_finite is True and right.is_finite is True:
                difference = sp.N(left - right)
                if difference.is_real is True and abs(float(difference)) > 1e-8:
                    return _result(
                        "revise",
                        "counterexample_found",
                        "A numerical substitution contradicts the proposed calculation",
                        counterexample={str(k): str(v) for k, v in values.items()},
                        lhs_value=str(left),
                        rhs_value=str(right),
                        **details,
                    )
    return _result(
        "uncertain",
        "not_proven",
        "No conclusive bounded symbolic result or counterexample; this is not proof",
        **details,
    )


def _worker(data: dict, output: str) -> None:
    try:
        if os.name == "posix":
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024,) * 2)
            resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
        result = _calculate(SymbolicCheck.model_validate(data))
    except Exception:
        result = _result(
            "uncertain",
            "unsupported",
            "This calculation cannot be checked safely by the bounded symbolic grammar",
        )
    Path(output).write_text(json.dumps(result))


def check_identity(check: SymbolicCheck) -> dict[str, Any]:
    """Compatibility entry point for all typed bounded calculation operations."""
    with tempfile.TemporaryDirectory(prefix="anki-math-") as temporary:
        output = Path(temporary) / "result.json"
        process = multiprocessing.get_context("spawn").Process(
            target=_worker, args=(check.model_dump(), str(output))
        )
        process.start()
        process.join(8)
        if process.is_alive():
            process.terminate()
            process.join(1)
            if process.is_alive():
                process.kill()
                process.join(1)
            return _result(
                "uncertain", "resource_limit", "Symbolic calculation exceeded its time budget"
            )
        if process.exitcode != 0 or not output.is_file():
            return _result(
                "uncertain", "resource_limit", "Symbolic worker stopped at a resource limit"
            )
        return json.loads(output.read_text())
