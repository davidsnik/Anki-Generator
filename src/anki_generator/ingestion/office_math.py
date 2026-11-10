"""Bounded native OMML transcription; unsupported notation stays explicitly unresolved.

This intentionally implements a small structural subset, not an Office renderer.
Fraction and script structure follows Microsoft's Open XML Math contracts:
https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.math.fraction
https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.math.superscript
"""

from __future__ import annotations

import json

from lxml.etree import _Element

MATH = "http://schemas.openxmlformats.org/officeDocument/2006/math"
WORD = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DRAWING = "http://schemas.openxmlformats.org/drawingml/2006/main"
COMPATIBILITY = "http://schemas.openxmlformats.org/markup-compatibility/2006"


class _UnresolvedMath(ValueError):
    pass


def _literal(value: str) -> str:
    # OMML text is literal source material, never an executable TeX command.
    escaped = {
        "\\": r"\backslash ",
        "{": r"\{",
        "}": r"\}",
        "_": r"\_",
        "^": r"\hat{}",
        "%": r"\%",
        "&": r"\&",
        "#": r"\#",
        "$": r"\$",
    }
    return "".join(escaped.get(character, character) for character in value)


def _render(element: _Element, budget: list[int], depth: int = 0) -> str:
    budget[0] -= 1
    if budget[0] < 0 or depth > 64:
        raise _UnresolvedMath("equation complexity limit")
    if not isinstance(element.tag, str):
        return ""  # XML comments carry no visible equation content.
    if not element.tag.startswith(f"{{{MATH}}}"):
        raise _UnresolvedMath("non-math equation content")
    tag = element.tag.rsplit("}", 1)[-1]

    def children() -> str:
        return "".join(_render(child, budget, depth + 1) for child in element)

    def argument(name: str, *, optional: bool = False) -> str:
        matches = element.findall(f"{{{MATH}}}{name}")
        if len(matches) != 1:
            if optional and not matches:
                return ""
            raise _UnresolvedMath(f"missing or repeated {name}")
        return _render(matches[0], budget, depth + 1)

    def expect_children(allowed: set[str]) -> None:
        if any(child.tag not in {f"{{{MATH}}}{name}" for name in allowed} for child in element):
            raise _UnresolvedMath(f"unsupported {tag} child")

    if tag == "t":
        if len(element.text or "") > 100_000:
            raise _UnresolvedMath("equation text limit")
        return _literal(element.text or "")
    if tag in {"oMath", "oMathPara", "e", "num", "den", "sub", "sup", "deg"}:
        return children()
    if tag == "r":
        expect_children({"rPr", "t"})
        properties = element.find(f"{{{MATH}}}rPr")
        value = "".join(
            _render(child, budget, depth + 1) for child in element if child.tag != f"{{{MATH}}}rPr"
        )
        if properties is not None:
            if any(child.tag != f"{{{MATH}}}sty" for child in properties):
                raise _UnresolvedMath("equation font or run styling")
            style = properties.find(f"{{{MATH}}}sty")
            if style is not None:
                command = {"p": "mathrm", "i": "mathit", "b": "mathbf", "bi": "boldsymbol"}.get(
                    style.get(f"{{{MATH}}}val")
                )
                if command is None:
                    raise _UnresolvedMath("unknown equation run style")
                value = "\\" + command + "{" + value + "}"
        return value
    if tag in {
        "oMathParaPr",
        "ctrlPr",
        "sSubPr",
        "sSupPr",
        "sSubSupPr",
        "mPr",
    }:
        return ""
    if tag == "rPr":
        if len(element):
            raise _UnresolvedMath("equation font or run styling")
        return ""
    if tag == "f":
        expect_children({"fPr", "num", "den"})
        kind = element.find(f"{{{MATH}}}fPr/{{{MATH}}}type")
        if kind is not None and kind.get(f"{{{MATH}}}val") not in {None, "bar"}:
            raise _UnresolvedMath("nonstandard fraction layout")
        return rf"\frac{{{argument('num')}}}{{{argument('den')}}}"
    if tag in {"sSub", "sSup", "sSubSup"}:
        expect_children({f"{tag}Pr", "e", "sub", "sup"})
        value = "{" + argument("e") + "}"
        if tag in {"sSub", "sSubSup"}:
            value += "_{" + argument("sub") + "}"
        if tag in {"sSup", "sSubSup"}:
            value += "^{" + argument("sup") + "}"
        return value
    if tag == "rad":
        expect_children({"radPr", "deg", "e"})
        degree = argument("deg", optional=True)
        hidden = element.find(f"{{{MATH}}}radPr/{{{MATH}}}degHide")
        if degree and hidden is not None and hidden.get(f"{{{MATH}}}val", "1") in {"1", "true"}:
            raise _UnresolvedMath("hidden nonempty radical degree")
        return rf"\sqrt[{degree}]{{{argument('e')}}}" if degree else rf"\sqrt{{{argument('e')}}}"
    if tag == "m":
        expect_children({"mPr", "mr"})
        rows = element.findall(f"{{{MATH}}}mr")
        if not rows:
            raise _UnresolvedMath("empty matrix")
        rendered = []
        columns = None
        for row in rows:
            if any(child.tag != f"{{{MATH}}}e" for child in row):
                raise _UnresolvedMath("unsupported matrix row content")
            cells = row.findall(f"{{{MATH}}}e")
            if not cells or columns not in {None, len(cells)}:
                raise _UnresolvedMath("inconsistent matrix dimensions")
            columns = len(cells)
            rendered.append(" & ".join(_render(cell, budget, depth + 1) for cell in cells))
        return r"\begin{matrix}" + r" \\ ".join(rendered) + r"\end{matrix}"
    raise _UnresolvedMath(f"unsupported {tag}")


def transcribe_math(element: _Element, warnings: set[str]) -> str:
    warnings.add(
        "Native Office mathematics recovered from OMML; font styling, layout and meaning "
        "remain unverified against the original document"
    )
    try:
        rendered = _render(element, [10_000])
        if len(rendered) > 100_000:
            raise _UnresolvedMath("equation text limit")
        return r"\(" + rendered + r"\)"
    except _UnresolvedMath as error:
        reason = str(error)
        warnings.add(f"Unresolved Office mathematics: {reason}; inspect the original equation")
        tokens = []
        length = 0
        for index, node in enumerate(element.iter()):
            if index >= 10_000 or length >= 1000:
                tokens.append("[visible-token preview truncated]")
                break
            if node.tag == f"{{{MATH}}}t" and node.text:
                tokens.append(node.text[: 1000 - length])
                length += len(tokens[-1])
        preview = json.dumps("".join(tokens))
        return f"[Unresolved Office mathematics ({reason}); visible tokens: {preview}]"


def paragraph_text(element: _Element, warnings: set[str]) -> str:
    """Preserve ordinary text and inline equations in document order."""
    if element.tag == f"{{{MATH}}}oMath":
        return transcribe_math(element, warnings)
    if element.tag in {f"{{{WORD}}}t", f"{{{DRAWING}}}t"}:
        return element.text or ""
    if element.tag in {f"{{{WORD}}}tab", f"{{{DRAWING}}}tab"}:
        return "\t"
    if element.tag in {f"{{{WORD}}}br", f"{{{DRAWING}}}br"}:
        return "\n"
    if element.tag == f"{{{COMPATIBILITY}}}AlternateContent":
        # The fallback normally repeats the same content as a raster. Keep the
        # preferred native branch once rather than duplicating its transcription.
        return paragraph_text(element[0], warnings) if len(element) else ""
    return "".join(paragraph_text(child, warnings) for child in element)
