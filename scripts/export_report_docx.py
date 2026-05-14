from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_MD = PROJECT_ROOT / "docs" / "个人期末实验报告_你负责部分.md"
TARGET_DOCX = PROJECT_ROOT / "docs" / "个人期末实验报告_你负责部分.docx"

IMAGE_RE = re.compile(r"!\[(?P<alt>.*?)\]\((?P<path>.*?)\)")


def _read_lines() -> list[str]:
    return SOURCE_MD.read_text(encoding="utf-8").splitlines()


def _split_table_row(line: str) -> list[str]:
    parts = [part.strip() for part in line.strip().strip("|").split("|")]
    return parts


def parse_markdown(lines: list[str]) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line:
            elements.append({"type": "paragraph", "text": "", "style": "Normal"})
            i += 1
            continue

        image_match = IMAGE_RE.fullmatch(line.strip())
        if image_match:
            img_path = image_match.group("path").strip().strip("<>").strip()
            alt = image_match.group("alt").strip()
            elements.append({"type": "image", "path": img_path, "alt": alt})
            i += 1
            continue

        if line.startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
            table_lines = [line]
            i += 1
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].rstrip())
                i += 1
            rows = [_split_table_row(row) for row in table_lines if row.strip()]
            if len(rows) >= 2 and all(set(cell.replace("-", "").replace(":", "").strip() or "-") == {"-"} for cell in rows[1]):
                header = rows[0]
                body = rows[2:]
            else:
                header = rows[0]
                body = rows[1:]
            elements.append({"type": "table", "header": header, "rows": body})
            continue

        if line.startswith("# "):
            elements.append({"type": "paragraph", "text": line[2:].strip(), "style": "Title"})
        elif line.startswith("## "):
            elements.append({"type": "paragraph", "text": line[3:].strip(), "style": "Heading1"})
        elif line.startswith("### "):
            elements.append({"type": "paragraph", "text": line[4:].strip(), "style": "Heading2"})
        elif line.startswith("#### "):
            elements.append({"type": "paragraph", "text": line[5:].strip(), "style": "Heading3"})
        elif line.startswith("- "):
            elements.append({"type": "paragraph", "text": "• " + line[2:].strip(), "style": "Normal"})
        elif line.startswith("> "):
            elements.append({"type": "paragraph", "text": line[2:].strip(), "style": "Quote"})
        else:
            elements.append({"type": "paragraph", "text": line, "style": "Normal"})
        i += 1
    return elements


CONTENT_TYPES_BASE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>
"""


PACKAGE_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""


STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
    <w:name w:val="Normal"/>
    <w:qFormat/>
    <w:rPr>
      <w:rFonts w:ascii="Times New Roman" w:eastAsia="宋体" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>
      <w:sz w:val="24"/>
    </w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Title">
    <w:name w:val="Title"/>
    <w:basedOn w:val="Normal"/>
    <w:qFormat/>
    <w:pPr><w:jc w:val="center"/></w:pPr>
    <w:rPr>
      <w:rFonts w:ascii="Times New Roman" w:eastAsia="黑体" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>
      <w:b/>
      <w:sz w:val="36"/>
    </w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/>
    <w:basedOn w:val="Normal"/>
    <w:qFormat/>
    <w:rPr>
      <w:rFonts w:ascii="Times New Roman" w:eastAsia="黑体" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>
      <w:b/>
      <w:sz w:val="32"/>
    </w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading2">
    <w:name w:val="heading 2"/>
    <w:basedOn w:val="Normal"/>
    <w:qFormat/>
    <w:rPr>
      <w:rFonts w:ascii="Times New Roman" w:eastAsia="黑体" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>
      <w:b/>
      <w:sz w:val="28"/>
    </w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading3">
    <w:name w:val="heading 3"/>
    <w:basedOn w:val="Normal"/>
    <w:qFormat/>
    <w:rPr>
      <w:rFonts w:ascii="Times New Roman" w:eastAsia="黑体" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>
      <w:b/>
      <w:sz w:val="26"/>
    </w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Quote">
    <w:name w:val="Quote"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr><w:ind w:left="720"/></w:pPr>
    <w:rPr>
      <w:i/>
    </w:rPr>
  </w:style>
</w:styles>
"""


def para(text: str, style: str = "Normal", center: bool = False) -> str:
    safe = escape(text)
    jc = '<w:jc w:val="center"/>' if center else ""
    return (
        f'<w:p><w:pPr><w:pStyle w:val="{style}"/>{jc}</w:pPr>'
        f'<w:r><w:rPr><w:rFonts w:ascii="Times New Roman" w:eastAsia="宋体" '
        f'w:hAnsi="Times New Roman" w:cs="Times New Roman"/></w:rPr>'
        f'<w:t xml:space="preserve">{safe}</w:t></w:r></w:p>'
    )


def make_table(header: list[str], rows: list[list[str]]) -> str:
    def cell(text: str, bold: bool = False) -> str:
        text = escape(text)
        b = "<w:b/>" if bold else ""
        return (
            "<w:tc><w:tcPr><w:tcW w:w=\"2400\" w:type=\"dxa\"/></w:tcPr>"
            "<w:p><w:r><w:rPr>"
            f"{b}<w:rFonts w:ascii=\"Times New Roman\" w:eastAsia=\"宋体\" w:hAnsi=\"Times New Roman\" w:cs=\"Times New Roman\"/>"
            "</w:rPr>"
            f"<w:t>{text}</w:t></w:r></w:p></w:tc>"
        )

    def row_xml(values: list[str], bold: bool = False) -> str:
        return "<w:tr>" + "".join(cell(v, bold) for v in values) + "</w:tr>"

    tbl_pr = (
        "<w:tblPr>"
        "<w:tblW w:w=\"0\" w:type=\"auto\"/>"
        "<w:tblBorders>"
        "<w:top w:val=\"single\" w:sz=\"8\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:left w:val=\"single\" w:sz=\"8\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:bottom w:val=\"single\" w:sz=\"8\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:right w:val=\"single\" w:sz=\"8\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:insideH w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:insideV w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"auto\"/>"
        "</w:tblBorders>"
        "</w:tblPr>"
    )
    return "<w:tbl>" + tbl_pr + row_xml(header, True) + "".join(row_xml(r) for r in rows) + "</w:tbl>"


def add_image(parts: list[str], rels: list[str], media: list[tuple[str, bytes]], image_path: Path, caption: str) -> None:
    if not image_path.exists():
        parts.append(para(f"[Missing image] {image_path.name}"))
        return

    rid = f"rId{len(rels) + 1}"
    media_name = f"image_{uuid4().hex}.png"
    rels.append(
        f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{media_name}"/>'
    )
    media.append((media_name, image_path.read_bytes()))

    with Image.open(image_path) as img:
        width_px, height_px = img.size

    max_width_emu = int(6.2 * 914400)
    width_emu = width_px * 9525
    height_emu = height_px * 9525
    if width_emu > max_width_emu:
        scale = max_width_emu / width_emu
        width_emu = int(width_emu * scale)
        height_emu = int(height_emu * scale)

    doc_pr_id = len(media) + 1000
    drawing = f"""
    <w:p>
      <w:pPr><w:jc w:val="center"/></w:pPr>
      <w:r>
        <w:drawing>
          <wp:inline distT="0" distB="0" distL="0" distR="0"
            xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
            xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
            xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
            <wp:extent cx="{width_emu}" cy="{height_emu}"/>
            <wp:docPr id="{doc_pr_id}" name="{escape(image_path.name)}"/>
            <a:graphic>
              <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
                <pic:pic>
                  <pic:nvPicPr>
                    <pic:cNvPr id="0" name="{escape(image_path.name)}"/>
                    <pic:cNvPicPr/>
                  </pic:nvPicPr>
                  <pic:blipFill>
                    <a:blip r:embed="{rid}"/>
                    <a:stretch><a:fillRect/></a:stretch>
                  </pic:blipFill>
                  <pic:spPr>
                    <a:xfrm><a:off x="0" y="0"/><a:ext cx="{width_emu}" cy="{height_emu}"/></a:xfrm>
                    <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
                  </pic:spPr>
                </pic:pic>
              </a:graphicData>
            </a:graphic>
          </wp:inline>
        </w:drawing>
      </w:r>
    </w:p>
    """
    parts.append(drawing)
    if caption:
        parts.append(para(caption, center=True))


def build_document() -> tuple[str, str, list[tuple[str, bytes]]]:
    lines = _read_lines()
    elements = parse_markdown(lines)
    body_parts: list[str] = []
    rels: list[str] = []
    media: list[tuple[str, bytes]] = []
    base_dir = SOURCE_MD.parent

    for el in elements:
        if el["type"] == "paragraph":
            body_parts.append(para(el["text"], el["style"]))
        elif el["type"] == "table":
            body_parts.append(make_table(el["header"], el["rows"]))
        elif el["type"] == "image":
            img_path = (base_dir / el["path"]).resolve()
            add_image(body_parts, rels, media, img_path, el["alt"])

    section = (
        "<w:sectPr>"
        '<w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1800" w:header="708" w:footer="708" w:gutter="0"/>'
        "</w:sectPr>"
    )
    body = "".join(body_parts) + section
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:o="urn:schemas-microsoft-com:office:office" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
        'xmlns:v="urn:schemas-microsoft-com:vml" '
        'xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:w10="urn:schemas-microsoft-com:office:word" '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
        'xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" '
        'xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk" '
        'xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml" '
        'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
        'mc:Ignorable="w14 wp14">'
        f"<w:body>{body}</w:body></w:document>"
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(rels)
        + "</Relationships>"
    )
    return document_xml, document_rels, media


def main() -> None:
    document_xml, document_rels, media = build_document()
    with ZipFile(TARGET_DOCX, "w", ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES_BASE)
        zf.writestr("_rels/.rels", PACKAGE_RELS)
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/styles.xml", STYLES)
        zf.writestr("word/_rels/document.xml.rels", document_rels)
        for media_name, media_bytes in media:
            zf.writestr(f"word/media/{media_name}", media_bytes)
    print(TARGET_DOCX)


if __name__ == "__main__":
    main()
