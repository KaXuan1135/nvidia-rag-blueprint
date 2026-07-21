# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import zipfile
from pathlib import Path

from nvidia_rag.utils.spreadsheet import spreadsheet_to_markdown


def test_csv_to_markdown(tmp_path: Path):
    source = tmp_path / "travel.csv"
    source.write_text(
        'country,rate,notes\nMalaysia,0.85,"first 500 km"\nSingapore,0.70,"contains | pipe"\n',
        encoding="utf-8",
    )

    markdown = spreadsheet_to_markdown(source)

    assert "# Spreadsheet: travel.csv" in markdown
    assert "| country | rate | notes |" in markdown
    assert "| Malaysia | 0.85 | first 500 km |" in markdown
    assert "contains \\| pipe" in markdown


def test_xlsx_inline_and_shared_strings_to_markdown(tmp_path: Path):
    source = tmp_path / "recovery.xlsx"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as workbook:
        workbook.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            '<sheet name="Recovery" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        workbook.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        workbook.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<si><t>Project</t></si><si><t>ASTRA</t></si></sst>',
        )
        workbook.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>Target</t></is></c></row>'
            '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2"><v>4</v></c></row>'
            '</sheetData></worksheet>',
        )

    markdown = spreadsheet_to_markdown(source)

    assert "# Spreadsheet: recovery.xlsx" in markdown
    assert "## Sheet: Recovery" in markdown
    assert "| Project | Target |" in markdown
    assert "| ASTRA | 4 |" in markdown
