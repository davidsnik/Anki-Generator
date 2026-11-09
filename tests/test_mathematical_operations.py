"""Supported calculations, counterexamples, domain limits and resource-safe inputs."""

import pytest

from anki_generator.processing.contracts import SymbolicCheck
from anki_generator.processing.mathematics import check_identity


def run(operation="identity", lhs="x", rhs="x", variables=None, assumptions=None, **kwargs):
    return check_identity(
        SymbolicCheck(
            operation=operation,
            lhs=lhs,
            rhs=rhs,
            variables=variables if variables is not None else ["x"],
            assumptions=assumptions or [],
            purpose="Synthetic bounded-calculation regression",
            **kwargs,
        )
    )


@pytest.mark.parametrize(
    "operation,lhs,rhs,extra",
    [
        ("differentiate", "x**3+sin(x)", "3*x**2+cos(x)", {}),
        ("differentiate", "exp(x)", "exp(x)", {}),
        ("integrate", "2*x", "x**2", {}),
        ("integrate", "x**2", "1/3", {"bounds": ["0", "1"]}),
        ("matrix_multiply", "[[1,2],[3,4]]", "[[5],[11]]", {"matrix_b": "[[1],[2]]"}),
        ("matrix_transpose", "[[1,2,3],[4,5,6]]", "[[1,4],[2,5],[3,6]]", {}),
        ("matrix_determinant", "[[1,2],[3,4]]", "-2", {}),
        ("matrix_shape", "[[1,2,3],[4,5,6]]", "[2,3]", {}),
        ("optimization_stationary", "x**2", "0", {}),
        ("probability", "x+(1-x)", "1", {}),
    ],
)
def test_supported_calculations_report_scope_without_claiming_proof(operation, lhs, rhs, extra):
    result = run(operation, lhs, rhs, **extra)
    assert result["verdict"] == "pass", result
    assert result["calculation_status"] == "calculation_verified"
    assert result["formal_proof"] is False and result["claim_human_verified"] is False


def test_domain_cancellation_does_not_erase_excluded_points():
    uncertain = run(lhs="x/x", rhs="1")
    assert uncertain["verdict"] == "uncertain"
    assert uncertain["calculation_status"] == "domain_unresolved"
    assert "x != 0" in uncertain["domain_restrictions"]
    established = run(lhs="x/x", rhs="1", assumptions=["x!=0"])
    assert established["verdict"] == "pass"
    assert established["assumptions_checked"] == ["x!=0"]


def test_square_root_branch_and_log_domain_require_correct_assumptions():
    wrong = run(lhs="sqrt(x*x)", rhs="x")
    assert wrong["verdict"] == "revise" and wrong["calculation_status"] == "counterexample_found"
    assert float(wrong["counterexample"]["x"]) < 0
    assert run(lhs="sqrt(x*x)", rhs="x", assumptions=["x>0"])["verdict"] == "pass"
    assert run(lhs="log(x)", rhs="log(x)")["verdict"] == "uncertain"
    assert run(lhs="log(x)", rhs="log(x)", assumptions=["x>0"])["verdict"] == "pass"


def test_counterexample_search_is_deterministic_and_absence_never_becomes_proof():
    first = run("counterexample", "x**2", "x")
    second = run("counterexample", "x**2", "x")
    assert first == second
    assert first["verdict"] == "revise" and first["counterexample"]
    absent = run("counterexample", "sin(x)**2+cos(x)**2", "1")
    assert absent["verdict"] == "uncertain" and absent["calculation_status"] == "not_proven"


def test_matrix_shape_mismatch_and_wrong_derivative_are_refuted():
    matrix = run("matrix_multiply", "[[1,2]]", "[[1]]", matrix_b="[[1,2]]")
    assert matrix["verdict"] == "revise" and matrix["calculation_status"] == "shape_mismatch"
    derivative = run("differentiate", "x**2", "3*x")
    assert derivative["verdict"] == "revise" and derivative["counterexample"]


def test_unsupported_assumptions_advanced_claims_and_unsafe_syntax_stay_uncertain():
    assert (
        run(lhs="x", rhs="x", assumptions=["f is convex on a compact set"])["verdict"]
        == "uncertain"
    )
    for expression in ["__import__('os')", "x.__class__", "[x for x in range(100000)]", "x**10000"]:
        assert run(lhs=expression, rhs="0")["verdict"] == "uncertain"
    result = run("optimization_stationary", "x**3", "0")
    assert result["verdict"] == "pass"
    assert "optimality is not established" in result["reason"]
