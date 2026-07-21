#!/usr/bin/env python3
"""Generate a deterministic mixed-format corpus for ingestion benchmarks."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import textwrap
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


PAGE_WIDTH, PAGE_HEIGHT = A4
SEED_FACTS = [
    ("Orchid", "Johor Bahru", "17 minutes", "OPS-417"),
    ("Maple", "Singapore", "23 minutes", "OPS-523"),
    ("Cedar", "Kuala Lumpur", "31 minutes", "OPS-631"),
    ("Quartz", "Penang", "19 minutes", "OPS-719"),
    ("Harbor", "Cyberjaya", "27 minutes", "OPS-827"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default="benchmarks/ingestion/corpus",
        help="Output directory relative to the repository root",
    )
    parser.add_argument(
        "--profile",
        choices=("smoke", "standard"),
        default="smoke",
        help="Smoke is about 40 page-equivalents; standard is about 160",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing generated corpus directory",
    )
    return parser.parse_args()


def add_record(
    records: list[dict],
    path: Path,
    corpus_root: Path,
    category: str,
    pages: int,
    question: str,
    answer: str,
) -> None:
    records.append(
        {
            "relative_path": str(path.relative_to(corpus_root)),
            "filename": path.name,
            "category": category,
            "format": path.suffix.lower().lstrip("."),
            "page_equivalents": pages,
            "size_bytes": path.stat().st_size,
            "question": question,
            "expected_answer": answer,
        }
    )


def paragraph_text(project: str, location: str, target: str, code: str, page: int) -> str:
    return (
        f"Project {project} operates from {location}. Its documented recovery target is {target}. "
        f"The escalation code is {code}. Page {page} describes routine validation, ownership, "
        "change approval, evidence retention, and quarterly service reviews. The benchmark text "
        "is intentionally repetitive enough to produce realistic chunks while keeping every "
        "document's identifying facts unambiguous."
    )


def make_native_pdf(path: Path, pages: int, fact: tuple[str, str, str, str]) -> None:
    project, location, target, code = fact
    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    body.fontSize = 11
    body.leading = 16
    story = []
    for page in range(1, pages + 1):
        story.extend(
            [
                Paragraph(f"{project} Operations Handbook", styles["Title"]),
                Spacer(1, 8 * mm),
                Paragraph(paragraph_text(project, location, target, code, page), body),
                Spacer(1, 4 * mm),
                Paragraph(
                    "Control owners must record the incident identifier, affected service, "
                    "decision authority, and completion timestamp before closing an event.",
                    body,
                ),
            ]
        )
        if page != pages:
            story.append(PageBreak())
    SimpleDocTemplate(str(path), pagesize=A4).build(story)


def scan_page_image(
    fact: tuple[str, str, str, str], page: int, width: int = 1240, height: int = 1754
) -> Image.Image:
    project, location, target, code = fact
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=28)
    title_font = ImageFont.load_default(size=42)
    draw.text((90, 90), f"SCANNED RECORD: {project}", fill="black", font=title_font)
    text = paragraph_text(project, location, target, code, page)
    y = 190
    for line in textwrap.wrap(text, width=62):
        draw.text((90, y), line, fill=(25, 25, 25), font=font)
        y += 44
    draw.rectangle((80, 1150, 1160, 1510), outline=(80, 80, 80), width=3)
    draw.text((110, 1200), f"Recovery target: {target}", fill="black", font=font)
    draw.text((110, 1270), f"Escalation code: {code}", fill="black", font=font)
    draw.text((110, 1340), f"Primary location: {location}", fill="black", font=font)
    return image.rotate(0.35 if page % 2 else -0.25, fillcolor="white")


def make_scanned_pdf(path: Path, pages: int, fact: tuple[str, str, str, str]) -> None:
    images = [scan_page_image(fact, page) for page in range(1, pages + 1)]
    images[0].save(path, "PDF", save_all=True, append_images=images[1:], resolution=150.0)


def make_mixed_pdf(path: Path, pages: int, fact: tuple[str, str, str, str]) -> None:
    project, location, target, code = fact
    pdf = canvas.Canvas(str(path), pagesize=A4)
    for page in range(1, pages + 1):
        if page % 2:
            pdf.setFont("Helvetica-Bold", 18)
            pdf.drawString(25 * mm, PAGE_HEIGHT - 30 * mm, f"{project} Mixed Document")
            text = pdf.beginText(25 * mm, PAGE_HEIGHT - 45 * mm)
            text.setFont("Helvetica", 11)
            for line in textwrap.wrap(paragraph_text(project, location, target, code, page), 88):
                text.textLine(line)
            pdf.drawText(text)
        else:
            image = scan_page_image(fact, page, width=900, height=1273)
            temp = path.with_suffix(f".page-{page}.jpg")
            image.save(temp, quality=82)
            pdf.drawImage(str(temp), 15 * mm, 15 * mm, width=180 * mm, height=257 * mm)
            temp.unlink()
        pdf.showPage()
    pdf.save()


def make_table_pdf(path: Path, pages: int, fact: tuple[str, str, str, str]) -> None:
    project, location, target, code = fact
    styles = getSampleStyleSheet()
    story = [Paragraph(f"{project} Capacity Schedule", styles["Title"]), Spacer(1, 6 * mm)]
    rows = [["Site", "Recovery target", "Escalation code", "Monthly capacity"]]
    for index in range(1, 13):
        rows.append([location, target, code, f"{1200 + index * 37} requests/min"])
    table = Table(rows, repeatRows=1, colWidths=[42 * mm, 38 * mm, 35 * mm, 45 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDE7F0")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    for page in range(pages):
        story.append(table)
        story.append(Spacer(1, 5 * mm))
        story.append(Paragraph(f"Table control reference: {code}; schedule page {page + 1}.", styles["BodyText"]))
        if page + 1 != pages:
            story.append(PageBreak())
    SimpleDocTemplate(str(path), pagesize=A4).build(story)


def make_chart_pdf(path: Path, pages: int, fact: tuple[str, str, str, str]) -> None:
    project, location, target, code = fact
    pdf = canvas.Canvas(str(path), pagesize=A4)
    values = [42, 65, 58, 83]
    labels = ["Q1", "Q2", "Q3", "Q4"]
    for page in range(1, pages + 1):
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawString(25 * mm, PAGE_HEIGHT - 28 * mm, f"{project} Quarterly Availability")
        baseline = 65 * mm
        for index, value in enumerate(values):
            x = 35 * mm + index * 38 * mm
            height = value * 1.7 * mm
            pdf.setFillColor(colors.HexColor(["#2F6B8A", "#C75B39", "#4E8B57", "#76548A"][index]))
            pdf.rect(x, baseline, 24 * mm, height, fill=1, stroke=0)
            pdf.setFillColor(colors.black)
            pdf.setFont("Helvetica", 10)
            pdf.drawCentredString(x + 12 * mm, baseline - 7 * mm, labels[index])
            pdf.drawCentredString(x + 12 * mm, baseline + height + 3 * mm, str(value))
        pdf.setFont("Helvetica", 11)
        pdf.drawString(25 * mm, 42 * mm, f"Highest quarter: Q4 at 83 units. Location: {location}.")
        pdf.drawString(25 * mm, 35 * mm, f"Recovery target: {target}. Escalation code: {code}.")
        pdf.showPage()
    pdf.save()


def write_docx(path: Path, fact: tuple[str, str, str, str], paragraphs: int) -> None:
    project, location, target, code = fact
    texts = [
        f"{project} Office Procedure",
        f"Primary location: {location}",
        f"Recovery target: {target}",
        f"Escalation code: {code}",
    ]
    texts.extend(paragraph_text(project, location, target, code, i + 1) for i in range(paragraphs))
    document_xml = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>' for text in texts
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
            f"{document_xml}<w:sectPr/></w:body></w:document>",
        )


def write_xlsx(path: Path, fact: tuple[str, str, str, str], rows: int) -> None:
    project, location, target, code = fact
    values = [["Project", "Location", "Recovery target", "Escalation code"]]
    values.extend([[project, location, target, code] for _ in range(rows)])
    row_xml = []
    for row_index, row in enumerate(values, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            column = chr(64 + col_index)
            cells.append(f'<c r="{column}{row_index}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            '<sheet name="Recovery" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(row_xml)}</sheetData></worksheet>',
        )


def write_text_file(path: Path, fact: tuple[str, str, str, str]) -> None:
    project, location, target, code = fact
    if path.suffix == ".csv":
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["project", "location", "recovery_target", "escalation_code"])
            for _ in range(20):
                writer.writerow([project, location, target, code])
        return
    heading = f"# {project} Service Note\n\n" if path.suffix == ".md" else f"{project} Service Note\n\n"
    path.write_text(
        heading
        + f"Primary location: {location}\nRecovery target: {target}\nEscalation code: {code}\n\n"
        + "\n\n".join(paragraph_text(project, location, target, code, i + 1) for i in range(5)),
        encoding="utf-8",
    )


def make_image(path: Path, fact: tuple[str, str, str, str]) -> None:
    image = scan_page_image(fact, 1, width=1100, height=850)
    image.save(path)


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    output = (root / args.output_dir).resolve()
    if output.exists():
        if not args.force:
            raise SystemExit(f"Output exists: {output}. Use --force to replace it.")
        shutil.rmtree(output)
    output.mkdir(parents=True)

    multiplier = 1 if args.profile == "smoke" else 4
    records: list[dict] = []

    category_specs = [
        ("native_pdf", 3 * multiplier, 3, make_native_pdf, ".pdf"),
        ("scanned_pdf", 2 * multiplier, 2, make_scanned_pdf, ".pdf"),
        ("mixed_pdf", 2 * multiplier, 3, make_mixed_pdf, ".pdf"),
        ("table_pdf", 2 * multiplier, 2, make_table_pdf, ".pdf"),
        ("chart_pdf", 2 * multiplier, 2, make_chart_pdf, ".pdf"),
    ]
    fact_index = 0
    for category, count, pages, builder, extension in category_specs:
        folder = output / category
        folder.mkdir()
        for index in range(1, count + 1):
            fact = SEED_FACTS[fact_index % len(SEED_FACTS)]
            fact_index += 1
            path = folder / f"{category}_{index:02d}{extension}"
            builder(path, pages, fact)
            project, location, target, code = fact
            question = f"What is the recovery target and escalation code for Project {project}?"
            add_record(records, path, output, category, pages, question, f"{target}; {code}")

    office_specs = [("docx", 2 * multiplier, 3), ("xlsx", 2 * multiplier, 2)]
    for category, count, pages in office_specs:
        folder = output / category
        folder.mkdir()
        for index in range(1, count + 1):
            fact = SEED_FACTS[fact_index % len(SEED_FACTS)]
            fact_index += 1
            path = folder / f"{category}_{index:02d}.{category}"
            if category == "docx":
                write_docx(path, fact, paragraphs=8 * pages)
            else:
                write_xlsx(path, fact, rows=25 * pages)
            project, location, target, code = fact
            add_record(
                records,
                path,
                output,
                category,
                pages,
                f"Which location and escalation code are listed for Project {project}?",
                f"{location}; {code}",
            )

    text_folder = output / "text"
    text_folder.mkdir()
    for index, extension in enumerate((".txt", ".md", ".csv") * multiplier, start=1):
        fact = SEED_FACTS[fact_index % len(SEED_FACTS)]
        fact_index += 1
        path = text_folder / f"text_{index:02d}{extension}"
        write_text_file(path, fact)
        project, location, target, code = fact
        add_record(
            records,
            path,
            output,
            "text",
            1,
            f"Where does Project {project} operate and what is its recovery target?",
            f"{location}; {target}",
        )

    image_folder = output / "image"
    image_folder.mkdir()
    for index in range(1, 2 * multiplier + 1):
        fact = SEED_FACTS[fact_index % len(SEED_FACTS)]
        fact_index += 1
        extension = ".png" if index % 2 else ".jpg"
        path = image_folder / f"image_{index:02d}{extension}"
        make_image(path, fact)
        project, location, target, code = fact
        add_record(
            records,
            path,
            output,
            "image",
            1,
            f"What escalation code appears in the image for Project {project}?",
            code,
        )

    manifest = {
        "profile": args.profile,
        "document_count": len(records),
        "page_equivalents": sum(item["page_equivalents"] for item in records),
        "documents": records,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with (output / "questions.jsonl").open("w", encoding="utf-8") as handle:
        for item in records:
            handle.write(
                json.dumps(
                    {
                        "filename": item["filename"],
                        "category": item["category"],
                        "question": item["question"],
                        "expected_answer": item["expected_answer"],
                    }
                )
                + "\n"
            )
    print(
        f"Generated {manifest['document_count']} documents and "
        f"{manifest['page_equivalents']} page-equivalents in {output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
