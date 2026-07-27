import re
import json
from pypdf import PdfReader


def extract_text_from_pdf(file_stream):
    reader = PdfReader(file_stream)
    return "".join(page.extract_text() or "" for page in reader.pages)


def clean_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    match = re.search(r"\{[\s\S]*\}", text)
    return match.group(0) if match else text


def normalize_analysis_dict(data):
    if not isinstance(data, dict):
        data = {}

    clean_data = {}
    for k, v in data.items():
        clean_k = str(k).strip().strip('"').strip("'").strip()
        clean_data[clean_k] = v

    score = clean_data.get("overall_score", 75)
    try:
        score = int(score)
    except (ValueError, TypeError):
        score = 75
    clean_data["overall_score"] = score

    ds = clean_data.get("dimension_scores")
    if not isinstance(ds, dict):
        ds = {}
    for dim in ("clarity", "experience", "skills", "ats_readiness", "impact", "completeness"):
        val = ds.get(dim, score)
        try:
            ds[dim] = int(val)
        except (ValueError, TypeError):
            ds[dim] = score
    clean_data["dimension_scores"] = ds

    rv = clean_data.get("recruiter_verdict")
    if not isinstance(rv, dict):
        rv = {}
    rv.setdefault("decision", "Maybe")
    rv.setdefault("top_standout", "Clear title and structured experience")
    rv.setdefault("biggest_weakness", "Needs stronger quantifiable metrics in bullet points")
    rv.setdefault("priority_fix", "Add numbers and specific business outcomes to experience bullets")
    clean_data["recruiter_verdict"] = rv

    fi = clean_data.get("recruiter_first_impression")
    if not isinstance(fi, dict):
        fi = {}
    fi.setdefault("score", score)
    fi.setdefault("readability", "High")
    fi.setdefault("visual_organization", "High")
    fi.setdefault("likelihood_to_read_on", "High")
    clean_data["recruiter_first_impression"] = fi

    ats = clean_data.get("ats_breakdown")
    if not isinstance(ats, dict):
        ats = {}
    ats.setdefault("formatting_score", 85)
    ats.setdefault("keywords_match_pct", 78)
    ats.setdefault("structure_score", 88)
    ats.setdefault("machine_readability", "High")
    clean_data["ats_breakdown"] = ats

    ka = clean_data.get("keyword_analysis")
    if not isinstance(ka, dict):
        ka = {}
    ka.setdefault("matched_keywords", clean_data.get("suggested_keywords", [])[:5] or ["Python", "Cloud", "Git", "API", "CI/CD"])
    ka.setdefault("missing_keywords", ["Kubernetes", "Architecture", "System Performance"])
    ka.setdefault("overused_words", ["responsible for", "managed"])
    ka.setdefault("percentage_match", 82)
    clean_data["keyword_analysis"] = ka

    comp = clean_data.get("competitiveness")
    if not isinstance(comp, dict):
        comp = {}
    comp.setdefault("junior_readiness", 90)
    comp.setdefault("mid_readiness", 85)
    comp.setdefault("senior_readiness", 72)
    comp.setdefault("faang_readiness", 68)
    comp.setdefault("startup_readiness", 88)
    clean_data["competitiveness"] = comp

    for arr_key in ("strengths", "weaknesses", "missing_sections", "ats_issues", "suggestions", "suggested_keywords"):
        if not isinstance(clean_data.get(arr_key), list):
            clean_data[arr_key] = []

    pal = clean_data.get("priority_action_list")
    if not isinstance(pal, list) or not pal:
        pal = [
            { "priority": 1, "recommendation": "Quantify bullet points with metrics (% growth, $ saved, latency reduction)", "estimated_gain": "+12 pts", "difficulty": "Easy", "time_required": "15m" },
            { "priority": 2, "recommendation": "Replace passive verbs ('responsible for') with power verbs ('Architected', 'Spearheaded')", "estimated_gain": "+8 pts", "difficulty": "Easy", "time_required": "10m" }
        ]
    clean_data["priority_action_list"] = pal

    bae = clean_data.get("before_after_examples")
    if not isinstance(bae, list) or not bae:
        bae = [
            {
                "original": "Worked on server migration and updated codebase.",
                "improved": "Spearheaded zero-downtime migration of 30+ servers to AWS EKS, reducing deployment latency by 45%.",
                "explanation": "Added strong action verb ('Spearheaded') and quantified impact ('45% reduction')."
            }
        ]
    clean_data["before_after_examples"] = bae

    rm = clean_data.get("roadmap")
    if not isinstance(rm, dict):
        rm = {}
    rm.setdefault("quick_wins_5m", ["Replace 'responsible for' with action verbs", "Add LinkedIn profile link"])
    rm.setdefault("medium_tasks_30m", ["Add metric data to 4 main experience bullets", "Format core skills tags"])
    rm.setdefault("major_rewrites_2h", ["Rewrite summary section into an executive value statement"])
    clean_data["roadmap"] = rm

    clean_data.setdefault("summary", "Candidate exhibits strong core qualifications with clear potential.")
    clean_data.setdefault("filename", "Evaluation Report")

    return clean_data
