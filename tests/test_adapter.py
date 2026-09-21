import json
import subprocess

from app.main import (
    _bbox,
    _element_text,
    _exception_message,
    _load_images,
    _page_spec,
    _sanitize_unicode,
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


def test_picture_elements_are_returned_as_images_with_description():
    document = {
        "kids": [
            {
                "type": "picture",
                "description": "一张柱状图",
                "page number": 1,
                "bounding box": [1, 2, 3, 4],
            }
        ]
    }

    content = _to_content_list(document)

    assert content == [{
        "type": "image",
        "img_path": content[0]["img_path"],
        "image_caption": ["一张柱状图"],
        "image_footnote": [],
        "bbox": [1, 2, 3, 4],
        "page_idx": 0,
    }]


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


def test_recognized_toc_items_keep_text_order_and_individual_boxes():
    document = {
        "kids": [
            {"type": "paragraph", "content": "1 安全警告 4", "page number": 2},
            {
                "type": "toc",
                "page number": 2,
                "bounding box": [10, 600, 500, 700],
                "toc items": [
                    {
                        "type": "toc item",
                        "content": "1.1 警告 4",
                        "page number": 2,
                        "bounding box": [10, 650, 500, 700],
                        "kids": [{"content": "1.1 警告 4"}],
                    },
                    {
                        "type": "toc item",
                        "page number": 2,
                        "bounding box": [10, 600, 500, 640],
                        "kids": [{"content": "1.2 注意 4"}],
                    },
                ],
            },
            {"type": "paragraph", "content": "2 概述 4", "page number": 2},
        ]
    }

    content = _to_content_list(document, {2: (600, 800)})

    assert [item["text"] for item in content] == [
        "1 安全警告 4", "1.1 警告 4", "1.2 注意 4", "2 概述 4"
    ]
    assert all(item["page_idx"] == 1 for item in content)
    assert content[1]["bbox"] == [16, 125, 833, 187]
    assert content[2]["bbox"] == [16, 200, 833, 250]
    assert _element_text(document["kids"][1]) == "1.1 警告 4\n1.2 注意 4"


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


def test_invalid_unicode_surrogates_are_replaced_before_response_encoding():
    payload = {
        "message": "before\udbc0after",
        "results": [{"md_content": "\ud800text", "content_list": "[]"}],
    }

    sanitized = _sanitize_unicode(payload)
    encoded = json.dumps(sanitized, ensure_ascii=False).encode("utf-8")

    assert "before�after" in encoded.decode("utf-8")
    assert sanitized["results"][0]["md_content"] == "�text"


def test_manual_nested_directory_keeps_children_between_parent_and_next_item():
    # Structure and coordinates from task 7eecd4ca's raw parser JSON.
    def item(text, box, kids=None):
        return {
            "type": "list item", "content": text, "page number": 2,
            "bounding box": box, "kids": kids or [],
        }

    children = {
        "type": "list", "page number": 2,
        "bounding box": [90.35, 633.613, 505.158, 699.097],
        "list items": [
            item("1.1 警告......4", [90.35, 664.813, 505.158, 699.097]),
            item("1.2 注意......4", [90.35, 633.613, 505.158, 667.897]),
        ],
    }
    document = {"kids": [{
        "type": "list", "page number": 2,
        "bounding box": [90.1, 602.413, 501.208, 730.297],
        "list items": [
            item("1 安全警告......4", [90.1, 696.013, 501.208, 730.297], [children]),
            item("2 概述......4", [90.1, 602.413, 501.208, 636.697]),
        ],
    }]}

    content = _to_content_list(document, {2: (595, 842)})

    assert [entry["text"] for entry in content] == [
        "1 安全警告......4", "1.1 警告......4", "1.2 注意......4", "2 概述......4"
    ]
    assert all(entry["page_idx"] == 1 for entry in content)
    assert content[1]["bbox"] == [151, 169, 849, 210]
    assert content[2]["bbox"] == [151, 206, 849, 247]


def test_deep_child_lists_preserve_pages_without_duplicating_text_or_images():
    figure = {"type": "image", "source": "images/deep.png", "page number": 3}
    leaf = {"type": "list", "list items": [{
        "type": "list item", "content": "2.2.1 正常运行条件", "page number": 3,
        "kids": [figure],
    }]}
    middle = {"type": "list", "list items": [{
        "type": "list item", "page number": 2,
        "kids": [{"type": "paragraph", "content": "2.2 工作条件"}, leaf],
    }]}
    document = {"kids": [{"type": "list", "list items": [{
        "type": "list item", "content": "2 概述", "page number": 2,
        "kids": [{"type": "paragraph", "content": "2 概述"}, middle],
    }]}]}

    content = _to_content_list(document)
    texts = [entry for entry in content if entry["type"] == "text"]

    assert [entry["text"] for entry in texts] == [
        "2 概述", "2.2 工作条件", "2.2.1 正常运行条件"
    ]
    assert [entry["page_idx"] for entry in texts] == [1, 1, 2]
    assert sum(entry.get("img_path") == "images/deep.png" for entry in content) == 1


def test_list_items_preserve_nested_paragraph_table_and_heading():
    document = {"kids": [{
        "type": "list", "page number": 7,
        "list items": [{
            "type": "list item", "page number": 7,
            "content": "1) 环境条件\n环境温度：+5 ℃ ～ +55 ℃；",
            "bounding box": [100, 600, 500, 700],
            "kids": [{
                "type": "paragraph", "content": "相对湿度：≤93%（40 ℃）。",
                "page number": 7, "bounding box": [110, 580, 400, 595],
            }],
        }, {
            "type": "list item", "content": "2) 能源条件", "page number": 7,
            "kids": [{
                "type": "table", "page number": 7,
                "bounding box": [80, 400, 520, 550],
                "rows": [{"cells": [{"kids": [
                    {"type": "paragraph", "content": "AC 380 V / 50 Hz"},
                    {"type": "image", "source": "images/cell.png", "page number": 7},
                ]}]}],
            }, {
                "type": "heading", "content": "2.2.2 非正常运行条件",
                "page number": 7, "bounding box": [80, 350, 350, 380],
            }],
        }],
    }]}

    result = _to_content_list(document, {7: (600, 800)})
    assert [entry["type"] for entry in result] == [
        "text", "text", "text", "table", "image", "text"
    ]
    assert result[1]["text"] == "相对湿度：≤93%（40 ℃）。"
    assert result[1]["bbox"] == [183, 256, 666, 275]
    assert "AC 380 V / 50 Hz" in result[3]["table_body"]
    assert result[3]["bbox"] == [133, 312, 866, 500]
    assert result[-1]["text"] == "2.2.2 非正常运行条件"
    assert all(entry["page_idx"] == 6 for entry in result)


def test_list_item_without_content_keeps_child_blocks_separate():
    table = {
        "type": "table", "page number": 4,
        "rows": [{"cells": [{"kids": [{"content": "燃油"}]}]}],
    }
    document = {"kids": [{"type": "list", "list items": [{
        "type": "list item", "page number": 4,
        "kids": [
            {"type": "paragraph", "content": "能源条件"},
            table,
            {"type": "heading", "content": "非正常运行条件"},
        ],
    }]}]}

    result = _to_content_list(document)

    assert [entry["type"] for entry in result] == ["text", "table", "text"]
    assert result[0]["text"] == "能源条件"
    assert "燃油" in result[1]["table_body"]
    assert result[2]["text"] == "非正常运行条件"
    assert all(entry["page_idx"] == 3 for entry in result)
