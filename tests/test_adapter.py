import json
import subprocess

from app.main import (
    _bbox,
    _exception_message,
    _load_images,
    _page_spec,
    _table_html,
    _to_content_list,
)


def test_bbox_is_returned_as_integer_array():
    assert _bbox({"bounding box": [1.2, 2.5, 3.7, 4]}) == [1, 3, 4, 4]
    assert _bbox({"bounding box": [1, None, 3, 4]}) == []


def test_bbox_is_converted_to_mineru_coordinates():
    element = {
        "page number": 1,
        "bounding box": [72.0, 700.0, 540.0, 730.0],
    }

    assert _bbox(element, {1: (612.0, 792.0)}) == [117, 78, 882, 116]


def test_mineru_bbox_is_clamped_to_zero_thousand():
    element = {
        "page number": 1,
        "bounding box": [-10.0, -20.0, 700.0, 900.0],
    }

    assert _bbox(element, {1: (612.0, 792.0)}) == [0, 0, 1000, 1000]


def test_full_page_bbox_snaps_to_mineru_edges():
    element = {
        "page number": 1,
        "bounding box": [0.0, 0.0, 468.85, 643.204],
    }

    assert _bbox(element, {1: (468.851, 643.204)}) == [0, 0, 1000, 1000]


def test_page_spec_converts_zero_based_inclusive_range():
    assert _page_spec(0, None) is None
    assert _page_spec(2, None, 10) == "3-10"
    assert _page_spec(0, 2) == "1-3"
    assert _page_spec(3, 3) == "4"


def test_content_list_matches_expected_wire_types():
    document = {
        "kids": [
            {
                "type": "heading",
                "content": "Title",
                "page number": 1,
                "bounding box": [1, 2, 3, 4],
            },
            {
                "type": "image",
                "source": "images/a.png",
                "page number": 2,
                "bounding box": [5, 6, 7, 8],
            },
        ]
    }
    content = _to_content_list(document)
    assert content[0] == {
        "type": "text",
        "text": "Title",
        "bbox": [1, 2, 3, 4],
        "page_idx": 0,
    }
    assert content[1]["type"] == "image"
    assert content[1]["img_path"] == "images/a.png"
    assert content[1]["page_idx"] == 1
    json.dumps(content, ensure_ascii=False)


def test_table_is_rendered_as_html():
    table = {
        "rows": [
            {
                "cells": [
                    {"row span": 2, "column span": 1, "kids": [{"content": "A&B"}]}
                ]
            }
        ]
    }
    assert _table_html(table) == (
        '<table><tr><td rowspan="2" colspan="1">A&amp;B</td></tr></table>'
    )


def test_images_are_returned_as_data_uri_from_task_directory(tmp_path):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    (image_dir / "figure.jpg").write_bytes(b"jpeg-data")
    (image_dir / "chart.png").write_bytes(b"png-data")

    images = _load_images({"kids": []}, tmp_path)

    assert images["figure.jpg"].startswith("data:image/jpg;base64,")
    assert images["chart.png"].startswith("data:image/png;base64,")


def test_nested_images_are_flattened_into_content_list():
    document = {
        "kids": [
            {
                "type": "list",
                "list items": [
                    {
                        "type": "list item",
                        "content": "item",
                        "kids": [
                            {
                                "type": "image",
                                "source": "images/nested.png",
                                "page number": 3,
                                "bounding box": [1, 2, 3, 4],
                            }
                        ],
                    }
                ],
            }
        ]
    }

    content = _to_content_list(document)

    assert any(item.get("img_path") == "images/nested.png" for item in content)


def test_called_process_error_includes_java_stderr():
    error = subprocess.CalledProcessError(
        1, ["java", "-jar", "parser.jar"], output="stdout detail", stderr="java detail"
    )

    message = _exception_message(error)

    assert "java detail" in message
    assert "stdout detail" in message
