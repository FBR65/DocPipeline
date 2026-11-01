"""B6 — Boxen der Layout-Engine werden in PDF-Punkte umgerechnet."""

from __future__ import annotations

from docpipeline.dual.engines import Variant
from docpipeline.dual.formats import Element
from docpipeline.dual.pipeline import DualPipeline


def _variant(dpi: int | None, boxes: tuple[Element, ...]) -> Variant:
    return Variant(
        name="dots-mocr",
        page_texts=("ACME",),
        text="ACME",
        boxes=(boxes,),
        tables=((),),
        dpi=dpi,
        pages_ocr=1,
    )


def test_pixel_boxes_are_scaled_to_points() -> None:
    boxes = (Element(1, (200.0, 400.0, 600.0, 800.0), "Text", "ACME"),)
    converted = DualPipeline._boxes_by_page([_variant(200, boxes)])
    assert converted[1][0].bbox == (72.0, 144.0, 216.0, 288.0)


def test_boxes_at_72_dpi_stay_unchanged() -> None:
    boxes = (Element(1, (10.0, 20.0, 30.0, 40.0), "Text", "ACME"),)
    converted = DualPipeline._boxes_by_page([_variant(72, boxes)])
    assert converted[1][0].bbox == (10.0, 20.0, 30.0, 40.0)


def test_degenerate_boxes_are_dropped() -> None:
    boxes = (
        Element(1, (50.0, 50.0, 50.0, 50.0), "Text", "leer"),
        Element(1, (10.0, 10.0, 20.0, 20.0), "Text", "ACME"),
    )
    converted = DualPipeline._boxes_by_page([_variant(100, boxes)])
    assert [box.text for box in converted[1]] == ["ACME"]


def test_page_without_usable_boxes_disappears() -> None:
    converted = DualPipeline._boxes_by_page(
        [_variant(200, (Element(1, (0.0, 0.0, 0.0, 0.0), "Picture", ""),))]
    )
    assert converted == {}


def test_text_layer_variant_contributes_no_boxes() -> None:
    layer = Variant(
        name="text_layer",
        page_texts=("ACME",),
        text="ACME",
        boxes=((Element(1, (0.0, 0.0, 9.0, 9.0), "Text", "ACME"),),),
        tables=((),),
        dpi=None,
        pages_ocr=0,
    )
    assert DualPipeline._boxes_by_page([layer]) == {}
