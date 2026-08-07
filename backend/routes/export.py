import re
import io
import json
from flask import Blueprint, request, jsonify, send_file
from backend.decorators import login_required

export_bp = Blueprint("export", __name__)


def parse_markdown_to_data(text):
    """
    Utility to parse raw markdown text into a structured dictionary if structured data is missing.
    """
    lines = text.split('\n')
    data = {
        "fullName": "",
        "email": "",
        "phone": "",
        "location": "",
        "summary": "",
        "skills": "",
        "experience": [],
        "education": [],
        "projects": []
    }
    
    current_sec = ""
    buf = []
    
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith('# '):
            data["fullName"] = s[2:].strip()
        elif s.startswith('## '):
            sec_title = s[3:].strip().lower()
            if 'summary' in sec_title or 'profile' in sec_title:
                current_sec = 'summary'
            elif 'skill' in sec_title:
                current_sec = 'skills'
            elif 'experience' in sec_title or 'work' in sec_title or 'employment' in sec_title:
                current_sec = 'experience'
            elif 'education' in sec_title:
                current_sec = 'education'
            elif 'project' in sec_title:
                current_sec = 'projects'
            else:
                current_sec = sec_title
        elif current_sec == 'summary':
            data["summary"] = (data["summary"] + " " + s).strip()
        elif current_sec == 'skills':
            clean_s = s.lstrip('-•* ').strip()
            data["skills"] = (data["skills"] + ", " + clean_s if data["skills"] else clean_s).strip(', ')
        elif current_sec in ('experience', 'projects', 'education'):
            buf.append(s)

    # Basic entry parsing for buffer lines
    if buf:
        cur_entry = None
        for b in buf:
            if b.startswith('### '):
                if cur_entry:
                    data["experience"].append(cur_entry)
                header = b[4:].strip()
                dates = ""
                if '(' in header and ')' in header:
                    parts = header.rsplit('(', 1)
                    header = parts[0].strip()
                    dates = parts[1].rstrip(')').strip()
                title_parts = header.split(' - ') if ' - ' in header else header.split(' | ')
                role = title_parts[0].strip()
                company = title_parts[1].strip() if len(title_parts) > 1 else ""
                cur_entry = {"role": role, "company": company, "dates": dates, "bullets": []}
            elif b.startswith(('- ', '• ', '* ')):
                bullet = b.lstrip('-•* ').strip()
                if cur_entry:
                    cur_entry["bullets"].append(bullet)
                else:
                    cur_entry = {"role": "Experience", "company": "", "dates": "", "bullets": [bullet]}
            elif cur_entry and not cur_entry["bullets"]:
                cur_entry["company"] = (cur_entry["company"] + " " + b).strip()
        if cur_entry:
            data["experience"].append(cur_entry)
            
    return data


@export_bp.route("/api/export/pdf", methods=["POST"])
@login_required
def export_pdf():
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors

    req_json = request.get_json() or {}
    raw_data = req_json.get("data")
    raw_text = req_json.get("text", "").strip()
    title = req_json.get("title", "Resume").strip()
    template_style = (req_json.get("template") or "modern").lower()

    if isinstance(raw_data, str):
        try:
            raw_data = json.loads(raw_data)
        except Exception:
            raw_data = None

    if not raw_data and raw_text:
        raw_data = parse_markdown_to_data(raw_text)

    if not raw_data and not raw_text:
        return jsonify({"error": "No resume data or text provided for PDF export"}), 400

    data = raw_data or {}
    full_name = data.get("fullName") or data.get("name") or "Professional Resume"
    email = data.get("email", "")
    phone = data.get("phone", "")
    location = data.get("location", "")
    summary = data.get("summary", "")
    skills = data.get("skills", "")
    experience = data.get("experience", [])
    education = data.get("education", [])
    projects = data.get("projects", [])
    certifications = data.get("certifications", [])

    # Theme colors
    color_palette = {
        "modern": {"primary": colors.HexColor("#1E3A5F"), "accent": colors.HexColor("#2563EB"), "text": colors.HexColor("#0F172A")},
        "executive": {"primary": colors.HexColor("#0F172A"), "accent": colors.HexColor("#475569"), "text": colors.HexColor("#1E293B")},
        "creative": {"primary": colors.HexColor("#6D28D9"), "accent": colors.HexColor("#7C3AED"), "text": colors.HexColor("#1E1B4B")},
        "minimalist": {"primary": colors.HexColor("#334155"), "accent": colors.HexColor("#64748B"), "text": colors.HexColor("#1E293B")}
    }
    theme = color_palette.get(template_style, color_palette["modern"])

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()

    name_style = ParagraphStyle(
        'HeaderName',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=22,
        leading=26,
        textColor=theme["primary"],
        spaceAfter=4
    )

    contact_style = ParagraphStyle(
        'HeaderContact',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=12,
        textColor=colors.HexColor('#64748B'),
        spaceAfter=8
    )

    sec_heading_style = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=15,
        textColor=theme["primary"],
        spaceBefore=10,
        spaceAfter=4
    )

    body_style = ParagraphStyle(
        'BodyTextCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=13.5,
        textColor=theme["text"],
        spaceAfter=6
    )

    bullet_style = ParagraphStyle(
        'BulletCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=13,
        textColor=theme["text"],
        leftIndent=12,
        firstLineIndent=-8,
        spaceAfter=2.5
    )

    item_title_style = ParagraphStyle(
        'ItemTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=13,
        textColor=colors.HexColor('#1E293B')
    )

    item_sub_style = ParagraphStyle(
        'ItemSub',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#64748B'),
        alignment=2  # Right aligned
    )

    story = []

    # 1. Header
    story.append(Paragraph(full_name, name_style))
    contact_parts = [p for p in [email, phone, location] if p]
    if contact_parts:
        story.append(Paragraph(" | ".join(contact_parts), contact_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=theme["accent"], spaceAfter=10))

    # 2. Professional Summary
    if summary:
        story.append(Paragraph("PROFESSIONAL SUMMARY", sec_heading_style))
        story.append(Paragraph(summary, body_style))

    # 3. Skills Matrix
    if skills:
        story.append(Paragraph("SKILLS & COMPETENCIES", sec_heading_style))
        skills_text = skills if isinstance(skills, str) else ", ".join(skills)
        story.append(Paragraph(skills_text, body_style))

    # 4. Work Experience
    if experience:
        story.append(Paragraph("WORK EXPERIENCE", sec_heading_style))
        for exp in experience:
            if isinstance(exp, dict):
                role = exp.get("role") or exp.get("title") or "Position"
                company = exp.get("company", "")
                dates = exp.get("dates", "")
                bullets = exp.get("bullets", [])

                title_line = f"<b>{role}</b>" + (f" — {company}" if company else "")
                t_table = Table(
                    [[Paragraph(title_line, item_title_style), Paragraph(dates, item_sub_style)]],
                    colWidths=[380, 160]
                )
                t_table.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                    ('TOPPADDING', (0, 0), (-1, -1), 2),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ]))
                story.append(t_table)

                for b in bullets:
                    story.append(Paragraph(f"• {b}", bullet_style))
                story.append(Spacer(1, 4))

    # 5. Education
    if education:
        story.append(Paragraph("EDUCATION", sec_heading_style))
        for edu in education:
            if isinstance(edu, dict):
                degree = edu.get("degree", "")
                school = edu.get("school", "")
                dates = edu.get("dates", "")
                title_line = f"<b>{degree}</b>" + (f" — {school}" if school else "")
                t_table = Table(
                    [[Paragraph(title_line, item_title_style), Paragraph(dates, item_sub_style)]],
                    colWidths=[380, 160]
                )
                t_table.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                    ('TOPPADDING', (0, 0), (-1, -1), 2),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ]))
                story.append(t_table)
                story.append(Spacer(1, 4))

    # 6. Projects
    if projects:
        story.append(Paragraph("PROJECTS", sec_heading_style))
        for proj in projects:
            if isinstance(proj, dict):
                p_name = proj.get("name") or proj.get("title") or "Project"
                p_desc = proj.get("desc") or proj.get("description") or ""
                p_tech = proj.get("tech") or proj.get("technologies") or ""
                story.append(Paragraph(f"<b>{p_name}</b>" + (f" ({p_tech})" if p_tech else ""), item_title_style))
                if p_desc:
                    story.append(Paragraph(p_desc, body_style))
                story.append(Spacer(1, 4))

    # If raw markdown was passed and parsing produced minimal structured output, render raw markdown blocks
    if raw_text and not experience and not summary:
        for line in raw_text.split('\n'):
            s = line.strip()
            if not s:
                continue
            if s.startswith('# '):
                story.append(Paragraph(s[2:], name_style))
            elif s.startswith('## '):
                story.append(Paragraph(s[3:], sec_heading_style))
            elif s.startswith('### '):
                story.append(Paragraph(s[4:], item_title_style))
            elif s.startswith(('- ', '• ', '* ')):
                story.append(Paragraph(f"• {s.lstrip('-•* ')}", bullet_style))
            else:
                story.append(Paragraph(s, body_style))

    doc.build(story)
    buffer.seek(0)
    clean_filename = re.sub(r'[^a-zA-Z0-9_-]', '_', title) + '.pdf'
    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=clean_filename
    )


@export_bp.route("/api/export/docx", methods=["POST"])
@login_required
def export_docx():
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor

    req_json = request.get_json() or {}
    raw_data = req_json.get("data")
    raw_text = req_json.get("text", "").strip()
    title = req_json.get("title", "Optimized_Resume").strip()

    if isinstance(raw_data, str):
        try:
            raw_data = json.loads(raw_data)
        except Exception:
            raw_data = None

    if not raw_data and raw_text:
        raw_data = parse_markdown_to_data(raw_text)

    doc = Document()

    # Set 0.6 inch margins
    for section in doc.sections:
        section.top_margin = Inches(0.6)
        section.bottom_margin = Inches(0.6)
        section.left_margin = Inches(0.6)
        section.right_margin = Inches(0.6)

    style = doc.styles['Normal']
    font = style.font
    font.name = 'Calibri'
    font.size = Pt(10.5)
    font.color.rgb = RGBColor(15, 23, 42)

    if raw_data and (raw_data.get("fullName") or raw_data.get("experience")):
        data = raw_data
        full_name = data.get("fullName") or data.get("name") or "Professional Resume"
        email = data.get("email", "")
        phone = data.get("phone", "")
        location = data.get("location", "")
        summary = data.get("summary", "")
        skills = data.get("skills", "")
        experience = data.get("experience", [])
        education = data.get("education", [])
        projects = data.get("projects", [])

        # Header
        p = doc.add_paragraph()
        run = p.add_run(full_name)
        run.font.size = Pt(22)
        run.font.bold = True
        run.font.color.rgb = RGBColor(37, 99, 235)
        p.paragraph_format.space_after = Pt(2)

        contact_parts = [cp for cp in [email, phone, location] if cp]
        if contact_parts:
            p_c = doc.add_paragraph()
            r_c = p_c.add_run(" | ".join(contact_parts))
            r_c.font.size = Pt(9.5)
            r_c.font.color.rgb = RGBColor(100, 116, 139)
            p_c.paragraph_format.space_after = Pt(10)

        # Summary
        if summary:
            p_h = doc.add_paragraph()
            r_h = p_h.add_run("PROFESSIONAL SUMMARY")
            r_h.font.size = Pt(12)
            r_h.font.bold = True
            r_h.font.color.rgb = RGBColor(30, 41, 59)
            p_h.paragraph_format.space_before = Pt(8)
            p_h.paragraph_format.space_after = Pt(3)

            p_s = doc.add_paragraph()
            p_s.add_run(summary)
            p_s.paragraph_format.space_after = Pt(8)

        # Skills
        if skills:
            p_h = doc.add_paragraph()
            r_h = p_h.add_run("SKILLS & COMPETENCIES")
            r_h.font.size = Pt(12)
            r_h.font.bold = True
            r_h.font.color.rgb = RGBColor(30, 41, 59)
            p_h.paragraph_format.space_before = Pt(8)
            p_h.paragraph_format.space_after = Pt(3)

            p_sk = doc.add_paragraph()
            p_sk.add_run(skills if isinstance(skills, str) else ", ".join(skills))
            p_sk.paragraph_format.space_after = Pt(8)

        # Experience
        if experience:
            p_h = doc.add_paragraph()
            r_h = p_h.add_run("WORK EXPERIENCE")
            r_h.font.size = Pt(12)
            r_h.font.bold = True
            r_h.font.color.rgb = RGBColor(30, 41, 59)
            p_h.paragraph_format.space_before = Pt(8)
            p_h.paragraph_format.space_after = Pt(3)

            for exp in experience:
                if isinstance(exp, dict):
                    role = exp.get("role") or exp.get("title") or "Position"
                    company = exp.get("company", "")
                    dates = exp.get("dates", "")
                    bullets = exp.get("bullets", [])

                    p_e = doc.add_paragraph()
                    r_r = p_e.add_run(role)
                    r_r.bold = True
                    if company:
                        p_e.add_run(f" — {company}")
                    if dates:
                        p_e.add_run(f"\t{dates}")
                    p_e.paragraph_format.space_after = Pt(2)

                    for b in bullets:
                        p_b = doc.add_paragraph(style='List Bullet')
                        p_b.add_run(b)
                        p_b.paragraph_format.space_after = Pt(2)

        # Education
        if education:
            p_h = doc.add_paragraph()
            r_h = p_h.add_run("EDUCATION")
            r_h.font.size = Pt(12)
            r_h.font.bold = True
            r_h.font.color.rgb = RGBColor(30, 41, 59)
            p_h.paragraph_format.space_before = Pt(8)
            p_h.paragraph_format.space_after = Pt(3)

            for edu in education:
                if isinstance(edu, dict):
                    degree = edu.get("degree", "")
                    school = edu.get("school", "")
                    dates = edu.get("dates", "")
                    p_ed = doc.add_paragraph()
                    r_d = p_ed.add_run(degree)
                    r_d.bold = True
                    if school:
                        p_ed.add_run(f" — {school}")
                    if dates:
                        p_ed.add_run(f"\t{dates}")
                    p_ed.paragraph_format.space_after = Pt(2)

        # Projects
        if projects:
            p_h = doc.add_paragraph()
            r_h = p_h.add_run("PROJECTS")
            r_h.font.size = Pt(12)
            r_h.font.bold = True
            r_h.font.color.rgb = RGBColor(30, 41, 59)
            p_h.paragraph_format.space_before = Pt(8)
            p_h.paragraph_format.space_after = Pt(3)

            for proj in projects:
                if isinstance(proj, dict):
                    p_name = proj.get("name") or proj.get("title") or "Project"
                    p_desc = proj.get("desc") or proj.get("description") or ""
                    p_tech = proj.get("tech") or proj.get("technologies") or ""
                    p_pj = doc.add_paragraph()
                    r_pn = p_pj.add_run(p_name)
                    r_pn.bold = True
                    if p_tech:
                        p_pj.add_run(f" ({p_tech})")
                    p_pj.paragraph_format.space_after = Pt(2)
                    if p_desc:
                        p_pd = doc.add_paragraph()
                        p_pd.add_run(p_desc)
                        p_pd.paragraph_format.space_after = Pt(4)

    else:
        # Fallback to lines parsing
        lines = raw_text.split('\n')
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
            elif line_s.startswith(('• ', '- ', '* ')):
                p = doc.add_paragraph(style='List Bullet')
                run = p.add_run(line_s.lstrip('-•* ').strip())
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
