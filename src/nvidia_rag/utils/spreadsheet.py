# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Convert spreadsheet files into retrieval-friendly Markdown text."""

import csv
import os
import re
import zipfile
from io import StringIO
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree


_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def spreadsheet_to_markdown(path: str | os.PathLike[str]) -> str:
    """Render CSV or XLSX as Markdown while preserving the source filename."""
    spreadsheet_path = Path(path)
    extension = spreadsheet_path.suffix.lower()
    if extension == ".csv":
        return _csv_to_markdown(spreadsheet_path)
    if extension == ".xlsx":
        return _xlsx_to_markdown(spreadsheet_path)
    raise ValueError(f"Unsupported spreadsheet format: {spreadsheet_path.suffix}")


def _csv_to_markdown(path: Path) -> str:
    raw_data = path.read_bytes()
    try:
        text = raw_data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw_data.decode("latin-1")
    rows = list(csv.reader(StringIO(text)))
    return _document_markdown(path.name, [("Data", rows)])


def _xlsx_to_markdown(path: Path) -> str:
    with zipfile.ZipFile(path) as workbook:
        shared_strings = _read_shared_strings(workbook)
        rendered_sheets = [
            (sheet_name, _read_worksheet(workbook, sheet_path, shared_strings))
            for sheet_name, sheet_path in _read_workbook_sheets(workbook)
        ]
    return _document_markdown(path.name, rendered_sheets)


def _read_shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [
        "".join(node.text or "" for node in item.iter(f"{{{_MAIN_NS}}}t"))
        for item in root.findall(f"{{{_MAIN_NS}}}si")
    ]


def _read_workbook_sheets(workbook: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook_root = ElementTree.fromstring(workbook.read("xl/workbook.xml"))
    relations_root = ElementTree.fromstring(
        workbook.read("xl/_rels/workbook.xml.rels")
    )
    relation_targets = {
        relation.attrib["Id"]: relation.attrib["Target"]
        for relation in relations_root.findall(f"{{{_PACKAGE_REL_NS}}}Relationship")
    }

    sheets = []
    for sheet in workbook_root.findall(f".//{{{_MAIN_NS}}}sheet"):
        relation_id = sheet.attrib.get(f"{{{_REL_NS}}}id")
        target = relation_targets.get(relation_id)
        if not target:
            continue
        if target.startswith("/"):
            sheet_path = target.lstrip("/")
        else:
            sheet_path = str(PurePosixPath("xl") / target)
        sheets.append((sheet.attrib.get("name", "Sheet"), sheet_path))
    return sheets


def _read_worksheet(
    workbook: zipfile.ZipFile, sheet_path: str, shared_strings: list[str]
) -> list[list[str]]:
    root = ElementTree.fromstring(workbook.read(sheet_path))
    rows: list[list[str]] = []
    for row_element in root.findall(f".//{{{_MAIN_NS}}}row"):
        row: list[str] = []
        for cell in row_element.findall(f"{{{_MAIN_NS}}}c"):
            cell_index = _cell_column_index(cell.attrib.get("r", ""))
            while len(row) <= cell_index:
                row.append("")
            row[cell_index] = _cell_value(cell, shared_strings)
        rows.append(row)
    return rows


def _cell_column_index(reference: str) -> int:
    match = re.match(r"([A-Z]+)", reference.upper())
    if not match:
        return 0
    result = 0
    for character in match.group(1):
        result = result * 26 + ord(character) - ord("A") + 1
    return result - 1


def _cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(
            node.text or "" for node in cell.iter(f"{{{_MAIN_NS}}}t")
        )

    value_node = cell.find(f"{{{_MAIN_NS}}}v")
    value = value_node.text if value_node is not None and value_node.text else ""
    if cell_type == "s" and value:
        try:
            return shared_strings[int(value)]
        except (IndexError, ValueError):
            return value
    if cell_type == "b":
        return "TRUE" if value == "1" else "FALSE"
    return value


def _document_markdown(
    filename: str, sheets: list[tuple[str, list[list[str]]]]
) -> str:
    sections = [f"# Spreadsheet: {filename}"]
    for sheet_name, rows in sheets:
        sections.extend([f"## Sheet: {sheet_name}", _rows_to_markdown(rows)])
    return "\n\n".join(sections).strip() + "\n"


def _rows_to_markdown(rows: list[list[str]]) -> str:
    rows = [_trim_row(row) for row in rows if any(str(cell).strip() for cell in row)]
    if not rows:
        return "(empty sheet)"

    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    headers = [
        str(value).strip() or f"Column {index + 1}"
        for index, value in enumerate(normalized[0])
    ]
    lines = [_markdown_row(headers), _markdown_row(["---"] * width)]
    lines.extend(_markdown_row(row) for row in normalized[1:])
    return "\n".join(lines)


def _trim_row(row: list[str]) -> list[str]:
    trimmed = [str(value) for value in row]
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    return trimmed


def _markdown_row(row: list[str]) -> str:
    escaped = [
        str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")
        for value in row
    ]
    return "| " + " | ".join(escaped) + " |"
