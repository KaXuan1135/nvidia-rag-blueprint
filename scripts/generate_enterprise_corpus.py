#!/usr/bin/env python3
"""Generate deterministic multilingual enterprise documents for RAG benchmarks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
import textwrap
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from docx import Document
from docx.shared import Inches
from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from pptx import Presentation
from pptx.util import Inches as PptxInches
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


SEED = 20260723
COMPANY = "Asteria Meridian Group"
PAGE_WIDTH, PAGE_HEIGHT = A4
SCALE_SPECS = {
    "pdf": (300, 1400), "docx": (100, 150), "pptx": (60, 150),
    "txt": (200, 50), "md": (200, 50), "html": (100, 50),
    "json": (100, 50), "csv": (60, 150), "xlsx": (60, 200),
    "png": (150, 450), "jpeg": (200, 450),
}
STANDARD_COUNTS = {
    "pdf": 30, "docx": 10, "pptx": 6, "txt": 20, "md": 20,
    "html": 10, "json": 10, "csv": 6, "xlsx": 6, "png": 15, "jpeg": 20,
}
DOMAINS = [
    ("hr", "Employee Handbook", "Buku Panduan Kakitangan"),
    ("finance", "Travel and Expense Policy", "Dasar Perjalanan dan Perbelanjaan"),
    ("security", "Information Security Standard", "Standard Keselamatan Maklumat"),
    ("operations", "Operations Procedure", "Prosedur Operasi"),
    ("compliance", "Compliance and Privacy Policy", "Dasar Pematuhan dan Privasi"),
    ("procurement", "Vendor Management Procedure", "Prosedur Pengurusan Pembekal"),
    ("continuity", "Disaster Recovery Runbook", "Panduan Pemulihan Bencana"),
    ("support", "Customer Escalation Guide", "Panduan Eskalasi Pelanggan"),
    ("facilities", "Workplace Safety Procedure", "Prosedur Keselamatan Tempat Kerja"),
]
FACTS = [
    ("mileage_rate",
     "Mileage claims are paid at RM 0.85 per kilometre for the first 500 kilometres.",
     "Tuntutan perjalanan dibayar pada kadar RM 0.85 setiap kilometer bagi 500 kilometer pertama.",
     "RM 0.85/km for the first 500 km",
     "what is the mileage rate for the first 500 kilometres?",
     "apakah kadar tuntutan bagi 500 kilometer pertama?"),
    ("annual_leave",
     "Employees with at least three years of service receive 18 days of annual leave.",
     "Kakitangan dengan sekurang-kurangnya tiga tahun perkhidmatan menerima 18 hari cuti tahunan.",
     "18 days", "how many annual leave days apply after three years of service?",
     "berapa hari cuti tahunan diberikan selepas tiga tahun perkhidmatan?"),
    ("security_incident",
     "A suspected security incident must be reported to the Security Operations Centre within 30 minutes.",
     "Insiden keselamatan yang disyaki mesti dilaporkan kepada Pusat Operasi Keselamatan dalam masa 30 minit.",
     "Report to the Security Operations Centre within 30 minutes",
     "when and where must a suspected security incident be reported?",
     "bila dan kepada siapa insiden keselamatan mesti dilaporkan?"),
    ("expense_approval",
     "Hotel expenses above RM 800 per night require approval from the Finance Director.",
     "Perbelanjaan hotel melebihi RM 800 semalam memerlukan kelulusan Pengarah Kewangan.",
     "Finance Director approval", "who approves hotel expenses above RM 800 per night?",
     "siapa meluluskan perbelanjaan hotel melebihi RM 800 semalam?"),
    ("vendor_review", "Critical vendors must complete a risk assessment every 12 months.",
     "Pembekal kritikal mesti melengkapkan penilaian risiko setiap 12 bulan.",
     "Every 12 months", "how often must critical vendors complete a risk assessment?",
     "berapa kerap pembekal kritikal perlu melengkapkan penilaian risiko?"),
    ("recovery_target", "Tier-1 services have a recovery time objective of 45 minutes.",
     "Perkhidmatan Tier-1 mempunyai objektif masa pemulihan selama 45 minit.",
     "45 minutes", "what is the recovery time objective for Tier-1 services?",
     "apakah objektif masa pemulihan bagi perkhidmatan Tier-1?"),
    ("password", "Privileged accounts require a minimum password length of 16 characters and MFA.",
     "Akaun berkeistimewaan memerlukan kata laluan minimum 16 aksara dan MFA.",
     "16 characters and MFA", "what controls apply to privileged account passwords?",
     "apakah kawalan kata laluan untuk akaun berkeistimewaan?"),
    ("return_policy", "Enterprise hardware may be returned within 21 calendar days after delivery.",
     "Perkakasan perusahaan boleh dipulangkan dalam tempoh 21 hari kalendar selepas penghantaran.",
     "21 calendar days", "how long is the enterprise hardware return period?",
     "berapa lama tempoh pemulangan perkakasan perusahaan?"),
    ("safety", "A workplace injury must be reported to the site manager before the end of the same shift.",
     "Kecederaan di tempat kerja mesti dilaporkan kepada pengurus tapak sebelum tamat syif yang sama.",
     "Before the end of the same shift", "when must a workplace injury be reported?",
     "bila kecederaan di tempat kerja mesti dilaporkan?"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--profile", choices=("smoke", "standard", "scale"), default="smoke")
    parser.add_argument("--target-size-gb", type=float, default=3.0)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def make_profile(name: str, target_gb: float) -> tuple[dict[str, int], dict[str, int], tuple[int, int]]:
    if name == "smoke":
        return {key: 1 for key in SCALE_SPECS}, {key: 0 for key in SCALE_SPECS}, (900, 1273)
    if name == "standard":
        return STANDARD_COUNTS, {
            key: int(mb * 0.1 * 1024**2) for key, (_, mb) in SCALE_SPECS.items()
        }, (1100, 1556)
    base_gb = sum(mb for _, mb in SCALE_SPECS.values()) / 1024
    ratio = target_gb / base_gb
    return (
        {key: count for key, (count, _) in SCALE_SPECS.items()},
        {key: int(mb * ratio * 1024**2) for key, (_, mb) in SCALE_SPECS.items()},
        (1900, 2687),
    )


def language_for(index: int) -> str:
    slot = index % 10
    return "en" if slot < 4 else "ms" if slot < 7 else "mixed"


def content(index: int, language: str, blocks: int = 8) -> tuple[str, dict]:
    domain, en_title, ms_title = DOMAINS[index % len(DOMAINS)]
    key, en_fact, ms_fact, answer, en_prompt, ms_prompt = FACTS[index % len(FACTS)]
    title = en_title if language == "en" else ms_title if language == "ms" else f"{en_title} / {ms_title}"
    policy_id = f"AMG-{domain.upper()}-{1000 + index:04d}"
    effective = date(2026, 1, 1) + timedelta(days=index % 180)
    en_intro = (
        f"This controlled document applies to all {COMPANY} employees and contractors. "
        f"Document owner: {domain.title()} Department. Policy reference: {policy_id}."
    )
    ms_intro = (
        f"Dokumen terkawal ini terpakai kepada semua kakitangan dan kontraktor {COMPANY}. "
        f"Pemilik dokumen: Jabatan {domain.title()}. Rujukan dasar: {policy_id}."
    )
    lines = [title, f"Effective date / Tarikh kuat kuasa: {effective.isoformat()}"]
    lines += [en_intro, en_fact] if language == "en" else [ms_intro, ms_fact]
    if language == "mixed":
        lines = [title, f"Effective date / Tarikh kuat kuasa: {effective.isoformat()}",
                 en_intro, ms_fact, f"Operational note / Nota operasi: {en_fact}"]
    for number in range(blocks):
        ticket = f"{domain[:3].upper()}-{index:04d}-{number:03d}"
        en = (f"Control record {ticket}: The responsible manager reviews evidence, records approval, "
              "confirms the effective date, and retains the audit record for seven years. "
              "Exceptions must include a business justification and an expiry date.")
        ms = (f"Rekod kawalan {ticket}: Pengurus bertanggungjawab menyemak bukti, merekod kelulusan, "
              "mengesahkan tarikh kuat kuasa dan menyimpan rekod audit selama tujuh tahun. "
              "Pengecualian mesti mempunyai justifikasi perniagaan dan tarikh tamat.")
        lines.append(en if language == "en" else ms if language == "ms" else (en if number % 2 == 0 else ms))
    return "\n\n".join(lines), {
        "domain": domain, "title": title, "fact_key": key, "answer": answer,
        "en_prompt": en_prompt, "ms_prompt": ms_prompt, "effective_date": effective.isoformat(),
    }


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = Path("/usr/share/fonts/truetype/dejavu") / name
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def scanned_page(text: str, size: tuple[int, int], seed: int, quality: str) -> Image.Image:
    rng = random.Random(seed)
    width, height = size
    page = Image.new("RGB", size, (247, 246, 242))
    draw = ImageDraw.Draw(page)
    margin = int(width * 0.075)
    title_font, body_font = font(max(22, width // 35), True), font(max(16, width // 52))
    paragraphs = text.split("\n\n")
    y = margin
    draw.text((margin, y), paragraphs[0][:80], font=title_font, fill=(24, 42, 58))
    y += int(title_font.size * 2.2)
    wrap = max(48, int(width / body_font.size * 1.65))
    for paragraph in paragraphs[1:]:
        for line in textwrap.wrap(paragraph, width=wrap):
            if y > height - margin * 2:
                break
            draw.text((margin, y), line, font=body_font, fill=(30, 30, 30))
            y += int(body_font.size * 1.45)
        y += body_font.size
        if y > height - margin * 2:
            break
    draw.line((margin, height - margin, width - margin, height - margin), fill=(100, 110, 115), width=2)
    draw.text((margin, height - margin + 8), COMPANY, font=font(max(12, width // 80)), fill=(75, 75, 75))
    strength = {"clean": 3, "moderate": 8, "difficult": 14}[quality]
    noise = Image.effect_noise(size, strength).convert("L")
    page = Image.blend(page, Image.merge("RGB", (noise, noise, noise)),
                       {"clean": 0.025, "moderate": 0.045, "difficult": 0.075}[quality])
    shadow = Image.new("L", size, 245)
    ImageDraw.Draw(shadow).rectangle((0, 0, int(width * 0.06), height), fill=180)
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, width // 35)))
    page = Image.composite(page, Image.new("RGB", size, (210, 205, 196)), shadow)
    angle = rng.uniform(-1.1, 1.1) if quality == "clean" else rng.uniform(-3.8, 3.8)
    page = page.rotate(angle, Image.Resampling.BICUBIC, fillcolor=(188, 184, 176))
    if quality != "clean":
        page = page.filter(ImageFilter.GaussianBlur(0.35 if quality == "moderate" else 0.8))
        page = ImageEnhance.Contrast(page).enhance(0.97 if quality == "moderate" else 0.9)
    return page


def save_scan(path: Path, text: str, size: tuple[int, int], seed: int, quality: str, fmt: str) -> None:
    image = scanned_page(text, size, seed, quality)
    if fmt == "PNG":
        image.save(path, fmt, compress_level=2)
    else:
        image.save(path, fmt, quality=94, subsampling=0, optimize=False)


def native_pdf(path: Path, text: str, pages: int) -> None:
    pdf = canvas.Canvas(str(path), pagesize=A4, pageCompression=1)
    for page in range(pages):
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(20 * mm, PAGE_HEIGHT - 24 * mm, text.split("\n\n")[0][:70])
        body = pdf.beginText(20 * mm, PAGE_HEIGHT - 38 * mm)
        body.setFont("Helvetica", 9.5)
        for line in textwrap.wrap(text.replace("\n", " ") + f" Page record {page + 1}.", 105):
            body.textLine(line)
        pdf.drawText(body)
        pdf.setFont("Helvetica", 8)
        pdf.drawString(20 * mm, 15 * mm, f"{COMPANY} | Controlled copy | Page {page + 1}")
        pdf.showPage()
    pdf.save()


def scanned_pdf(path: Path, text: str, pages: int, size: tuple[int, int], seed: int, quality: str) -> None:
    images = [scanned_page(text + f"\n\nPage record {p + 1}", size, seed + p, quality) for p in range(pages)]
    images[0].save(path, "PDF", save_all=True, append_images=images[1:], resolution=170, quality=93)


def mixed_pdf(path: Path, text: str, pages: int, size: tuple[int, int], seed: int, quality: str) -> None:
    pdf = canvas.Canvas(str(path), pagesize=A4, pageCompression=1)
    temporary = path.with_suffix(".scan.jpg")
    for page in range(pages):
        if page % 2 == 0:
            body = pdf.beginText(20 * mm, PAGE_HEIGHT - 25 * mm)
            body.setFont("Helvetica", 9.5)
            for line in textwrap.wrap(text.replace("\n", " "), 105):
                body.textLine(line)
            pdf.drawText(body)
        else:
            save_scan(temporary, text, size, seed + page, quality, "JPEG")
            pdf.drawImage(str(temporary), 7 * mm, 7 * mm, width=196 * mm, height=283 * mm)
        pdf.showPage()
    pdf.save()
    temporary.unlink(missing_ok=True)


def text_file(path: Path, text: str, target: int, kind: str) -> int:
    target = max(target, len(text.encode()))
    with path.open("w", encoding="utf-8") as handle:
        handle.write('{"company":"' + COMPANY + '","records":[\n' if kind == "json"
                     else "<html><body><article>\n" if kind == "html" else "")
        number = 0
        while handle.tell() < target - 2048:
            if kind == "json":
                handle.write(json.dumps(
                    {"record_id": f"REC-{number:08d}", "content": text, "status": "approved"},
                    ensure_ascii=False,
                ) + ",\n")
            elif kind == "html":
                handle.write(f"<section><h2>Control {number}</h2><p>{text}</p></section>\n")
            else:
                heading = f"\n## Control {number}\n" if kind == "md" else f"\nControl {number}\n"
                handle.write(heading + text + "\n")
            number += 1
        handle.write('{"record_id":"END","status":"complete"}]}\n' if kind == "json"
                     else "</article></body></html>\n" if kind == "html" else "")
    return number


def csv_file(path: Path, text: str, target: int, seed: int) -> int:
    rng = random.Random(seed)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["record_id", "department", "amount_rm", "status", "policy_excerpt"])
        rows = 0
        while handle.tell() < max(target, 4096):
            writer.writerow([f"TXN-{seed:05d}-{rows:08d}", DOMAINS[rows % len(DOMAINS)][0],
                             f"{rng.uniform(10, 5000):.2f}", ("approved", "pending", "rejected")[rows % 3],
                             text[:600]])
            rows += 1
    return rows


def xlsx_file(path: Path, text: str, target: int, seed: int, scan: Path) -> int:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Policy Register"
    sheet.append(["record_id", "department", "effective_date", "status", "policy_excerpt"])
    rows = max(100, min(35000, target // max(700, len(text.encode()) // 2)))
    for row in range(rows):
        sheet.append([f"POL-{seed:05d}-{row:06d}", DOMAINS[row % len(DOMAINS)][0],
                      f"2026-{row % 12 + 1:02d}-{row % 28 + 1:02d}",
                      ("active", "review", "superseded")[row % 3], text[:1100]])
    image_sheet = workbook.create_sheet("Document Scan")
    image_sheet.add_image(XLImage(str(scan)), "A1")
    workbook.save(path)
    return rows


def office_file(path: Path, fmt: str, text: str, scan: Path) -> None:
    if fmt == "docx":
        document = Document()
        document.add_heading(text.split("\n\n")[0], 0)
        for paragraph in text.split("\n\n")[1:]:
            document.add_paragraph(paragraph)
        document.add_picture(str(scan), width=Inches(5.8))
        document.save(path)
        return
    presentation = Presentation()
    for slide_number in range(4):
        slide = presentation.slides.add_slide(presentation.slide_layouts[5])
        slide.shapes.title.text = f"{text.splitlines()[0]} - {slide_number + 1}"
        slide.shapes.add_picture(str(scan), PptxInches(1), PptxInches(1.4), width=PptxInches(8))
    presentation.save(path)


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def make_document(root: Path, fmt: str, index: int, count: int, target_total: int,
                  size: tuple[int, int], seed: int) -> tuple[dict, dict]:
    language = language_for(index)
    text, fact = content(index, language, 10)
    quality = ("clean", "moderate", "difficult")[index % 3]
    extension = "jpg" if fmt == "jpeg" else fmt
    doc_id = f"AMG-{fmt.upper()}-{index + 1:05d}"
    folder = root / "documents" / fmt
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{doc_id.lower()}.{extension}"
    canonical = root / "ground_truth" / "documents" / f"{doc_id}.md"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text(text + "\n", encoding="utf-8")
    target = target_total // count if count else 0
    pages, rows = 1, 0
    helper = root / ".working" / f"{doc_id}.jpg"
    helper.parent.mkdir(parents=True, exist_ok=True)
    save_scan(helper, text, size if target else (900, 1273), seed + index, quality, "JPEG")

    if fmt == "pdf":
        source = "native" if index % 5 < 2 else "scanned" if index % 5 < 4 else "mixed"
        pages = (8 + index % 6) if target else (2 + index % 4)
        if source == "native":
            native_pdf(path, text, pages)
        elif source == "scanned":
            scanned_pdf(path, text, pages, size, seed + index, quality)
        else:
            mixed_pdf(path, text, pages, size, seed + index, quality)
    elif fmt in {"png", "jpeg"}:
        source = "scanned"
        save_scan(path, text, size, seed + index, quality, "PNG" if fmt == "png" else "JPEG")
    elif fmt in {"docx", "pptx"}:
        source = "native"
        office_file(path, fmt, text, helper)
        pages = 4 if fmt == "pptx" else 1
    elif fmt == "xlsx":
        source = "native"
        rows = xlsx_file(path, text, target, seed + index, helper)
    elif fmt == "csv":
        source = "native"
        rows = csv_file(path, text, target, seed + index)
    else:
        source = "native"
        rows = text_file(path, text, target, fmt)
    helper.unlink(missing_ok=True)
    if source != "native":
        page_folder = root / "ground_truth" / "pages" / doc_id
        page_folder.mkdir(parents=True, exist_ok=True)
        for page in range(pages):
            (page_folder / f"page-{page + 1:04d}.txt").write_text(
                text + f"\n\nPage record {page + 1}\n", encoding="utf-8"
            )
    record = {
        "document_id": doc_id, "filename": path.name, "relative_path": str(path.relative_to(root)),
        "extension": path.suffix.lower(), "size_bytes": path.stat().st_size, "sha256": digest(path),
        "category": fact["domain"], "document_title": fact["title"], "language": language,
        "source_type": source, "page_count": pages, "word_count": len(text.split()),
        "row_count": rows, "image_quality": quality if source != "native" else None,
        "expected_ocr": source != "native", "version": 1 + index % 3,
        "effective_date": fact["effective_date"], "supersedes": None, "generation_seed": seed + index,
    }
    query_language = ("en", "ms", "mixed")[index % 3]
    prompt = fact["en_prompt"] if query_language == "en" else fact["ms_prompt"]
    prefix = ("According to company policy, " if query_language == "en"
              else "Menurut dasar syarikat, " if query_language == "ms"
              else "According to dasar syarikat, ")
    question = {
        "question_id": f"Q-{fmt.upper()}-{index + 1:05d}", "question": prefix + prompt,
        "query_language": query_language, "expected_answer": fact["answer"],
        "source_document_ids": [doc_id], "expected_pages": [1],
        "key_facts": [fact["fact_key"], fact["answer"]], "question_type": "policy_fact",
        "difficulty": quality if source != "native" else "standard",
    }
    return record, question


def write_reports(root: Path, profile_name: str, records: list[dict], elapsed: float) -> None:
    counts, sizes, languages, sources, qualities = Counter(), Counter(), Counter(), Counter(), Counter()
    for item in records:
        counts[item["extension"]] += 1
        sizes[item["extension"]] += item["size_bytes"]
        languages[item["language"]] += 1
        sources[item["source_type"]] += 1
        if item["image_quality"]:
            qualities[item["image_quality"]] += 1
    summary = {
        "profile": profile_name, "document_count": len(records),
        "total_size_bytes": sum(sizes.values()), "total_pages": sum(r["page_count"] for r in records),
        "total_words": sum(r["word_count"] for r in records), "total_rows": sum(r["row_count"] for r in records),
        "elapsed_seconds": round(elapsed, 3), "counts_by_extension": dict(counts),
        "bytes_by_extension": dict(sizes), "languages": dict(languages),
        "source_types": dict(sources), "image_quality": dict(qualities),
    }
    (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (root / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["extension", "documents", "bytes", "megabytes"])
        for extension in sorted(counts):
            writer.writerow([extension, counts[extension], sizes[extension], round(sizes[extension] / 1024**2, 3)])
    (root / "README.md").write_text(
        f"# Synthetic Enterprise Corpus\n\nProfile: `{profile_name}`\n\nDocuments: {len(records)}\n\n"
        f"Total size: {summary['total_size_bytes'] / 1024**3:.3f} GiB\n\n"
        "All information is deterministic and synthetic. Canonical text and page-level OCR "
        "ground truth are stored under `ground_truth/`.\n", encoding="utf-8",
    )


def main() -> int:
    options = parse_args()
    counts, targets, scan_size = make_profile(options.profile, options.target_size_gb)
    expected = sum(targets.values())
    print(f"Profile={options.profile}; files={sum(counts.values())}; target={expected / 1024**3:.2f} GiB")
    for fmt, count in counts.items():
        print(f"  {fmt:5s}: {count:4d} files, target {targets[fmt] / 1024**2:.1f} MiB")
    if options.dry_run:
        return 0
    root = Path(options.output_dir).resolve()
    if root.exists() and options.force:
        shutil.rmtree(root)
    elif root.exists() and any(root.iterdir()):
        raise SystemExit(f"Output directory is not empty: {root}; use --force")
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < max(expected * 1.5, 1024**3):
        raise SystemExit("Insufficient free disk space")
    started = time.monotonic()
    records, questions = [], []
    total_files = sum(counts.values())
    for fmt_number, (fmt, count) in enumerate(counts.items()):
        for index in range(count):
            record, question = make_document(
                root, fmt, index, count, targets[fmt], scan_size,
                options.seed + fmt_number * 100000,
            )
            records.append(record)
            questions.append(question)
            print(f"[{len(records):04d}/{total_files}] {record['relative_path']} "
                  f"{record['size_bytes'] / 1024**2:.2f} MiB", flush=True)
    (root / "manifest.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8"
    )
    (root / "questions.jsonl").write_text(
        "".join(json.dumps(question, ensure_ascii=False) + "\n" for question in questions), encoding="utf-8"
    )
    shutil.rmtree(root / ".working", ignore_errors=True)
    write_reports(root, options.profile, records, time.monotonic() - started)
    print(f"Generated {len(records)} files at {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
