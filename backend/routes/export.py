import re
import io
from flask import Blueprint, request, jsonify, send_file
from backend.decorators import login_required

export_bp = Blueprint("export", __name__)


@export_bp.route("/api/export/docx", methods=["POST"])
@login_required
def export_docx():
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor

    data = request.get_json() or {}
    text = data.get("text", "").strip()
    title = data.get("title", "Optimized_Resume").strip()

    doc = Document()

    sections = doc.sections
    for section in sections:
        section.top_margin = Inches(0.6)
        section.bottom_margin = Inches(0.6)
        section.left_margin = Inches(0.6)
        section.right_margin = Inches(0.6)

    style = doc.styles['Normal']
    font = style.font
    font.name = 'Calibri'
    font.size = Pt(10.5)
    font.color.rgb = RGBColor(15, 23, 42)

    lines = text.split('\n')
    for line in lines:
        line_s = line.strip()
        if not line_s:
            continue
        if line_s.startswith('# '):
            p = doc.add_paragraph()
            run = p.add_run(line_s[2:].strip())
            run.font.size = Pt(22)
            run.font.bold = True
            run.font.color.rgb = RGBColor(37, 99, 235)
            p.paragraph_format.space_after = Pt(4)
        elif line_s.startswith('## '):
            p = doc.add_paragraph()
            run = p.add_run(line_s[3:].strip())
            run.font.size = Pt(13)
            run.font.bold = True
            run.font.color.rgb = RGBColor(30, 41, 59)
            p.paragraph_format.space_before = Pt(12)
            p.paragraph_format.space_after = Pt(4)
        elif line_s.startswith('### '):
            p = doc.add_paragraph()
            run = p.add_run(line_s[4:].strip())
            run.font.size = Pt(11)
            run.font.bold = True
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(2)
        elif line_s.startswith('• ') or line_s.startswith('- '):
            p = doc.add_paragraph(style='List Bullet')
            run = p.add_run(line_s[2:].strip())
            p.paragraph_format.space_after = Pt(2)
        else:
            p = doc.add_paragraph()
            p.add_run(line_s)
            p.paragraph_format.space_after = Pt(4)

    target_stream = io.BytesIO()
    doc.save(target_stream)
    target_stream.seek(0)

    clean_filename = re.sub(r'[^a-zA-Z0-9_-]', '_', title) + '.docx'
    return send_file(
        target_stream,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=clean_filename
    )
