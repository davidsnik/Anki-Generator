import pytest

from anki_generator.processing.contracts import EvidenceReference, SymbolicCheck
from anki_generator.processing.evidence import EvidenceIndex
from anki_generator.processing.mathematics import check_identity


def index(tmp_path):
    return EvidenceIndex(
        [
            {
                "id": "doc",
                "filename": "notes.pdf",
                "category": "notes",
                "extraction": {
                    "artifact_dir": "artifacts/doc",
                    "pages": [
                        {
                            "page_number": 1,
                            "width": 100,
                            "height": 200,
                            "text": "For x > 0, the function is increasing.",
                            "status": "complete",
                            "regions": [
                                {
                                    "id": "region-1",
                                    "image_path": "page.png",
                                    "bbox": [0, 0, 100, 200],
                                }
                            ],
                            "visual_interpretations": [
                                {
                                    "region_id": "region-1",
                                    "transcription": "a^2+b^2=c^2",
                                    "description": "right triangle",
                                    "uncertain": True,
                                }
                            ],
                        }
                    ],
                },
            }
        ],
        tmp_path,
    )


def ref(**overrides):
    return EvidenceReference(document_id="doc", page_number=1, quote="For x > 0", **overrides)


def test_actual_source_quote_required_and_math_symbols_preserved(tmp_path):
    evidence = index(tmp_path)
    assert evidence.validate([ref()]) == []
    assert evidence.validate([ref().model_copy(update={"quote": "For x >= 0"})])
    assert evidence.validate([ref().model_copy(update={"quote": "a fabricated quotation"})])


def test_missing_pages_regions_outside_bbox_and_empty_refs_blocked(tmp_path):
    evidence = index(tmp_path)
    for refs in [
        [],
        [ref().model_copy(update={"page_number": 2})],
        [ref(region_id="invented")],
        [ref(bbox=[0, 0, 1000, 1000])],
    ]:
        assert evidence.validate(refs)


def test_uncertain_vision_is_never_verified_as_source(tmp_path):
    evidence = index(tmp_path)
    assert (
        "uncertain"
        in evidence.validate(
            [ref(region_id="region-1").model_copy(update={"quote": "a^2+b^2=c^2"})]
        )[0]
    )


def test_known_media_resolves_and_invented_media_fails(tmp_path):
    evidence = index(tmp_path)
    media, errors = evidence.media(["doc:region-1"])
    assert not errors and media[0]["region_id"] == "region-1"
    assert evidence.media(["doc:missing"])[1]


@pytest.mark.parametrize(
    "lhs,rhs,verdict",
    [
        ("(x+y)**2", "x*x+2*x*y+y*y", "pass"),
        ("x*x-y*y", "(x+y)**2", "revise"),
        ("__import__('os').system('echo unsafe')", "0", "uncertain"),
        ("x.__class__", "0", "uncertain"),
        ("x**999999999", "0", "uncertain"),
        ("((x+y)**8)**8", "0", "uncertain"),
        ("x/0", "0", "uncertain"),
    ],
)
def test_symbolic_check_uses_bounded_ast_not_python_eval(lhs, rhs, verdict):
    result = check_identity(
        SymbolicCheck(
            lhs=lhs,
            rhs=rhs,
            variables=["x", "y"],
            assumptions=[],
            purpose="Test polynomial identity",
        )
    )
    assert result["verdict"] == verdict
    assert result.get("formal_proof") is False


def test_machine_text_cannot_override_uncertain_interpretation_of_same_original_region(tmp_path):
    evidence = index(tmp_path)
    problems = evidence.validate([ref(region_id="region-1")])
    assert any("uncertainty" in problem for problem in problems)
