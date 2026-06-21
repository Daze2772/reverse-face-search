"""PDF export — render intelligence report using reportlab (no system deps)."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from io import BytesIO

logger = logging.getLogger("intel.pdf")


def generate_pdf(report_data: Dict[str, Any], output_path: Optional[str] = None) -> Optional[bytes]:
    """Generate a PDF from the intelligence report data using reportlab."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib.colors import HexColor
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.enums import TA_LEFT, TA_CENTER
        
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer if not output_path else output_path,
            pagesize=A4,
            rightMargin=0.75*inch,
            leftMargin=0.75*inch,
            topMargin=0.75*inch,
            bottomMargin=0.75*inch,
        )
        
        styles = getSampleStyleSheet()
        story = _build_story(report_data, styles)
        doc.build(story)
        
        if output_path:
            logger.info(f"PDF saved: {output_path}")
            return open(output_path, "rb").read()
        else:
            pdf_bytes = buffer.getvalue()
            logger.info(f"PDF generated: {len(pdf_bytes)} bytes")
            return pdf_bytes

    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        return None


def generate_html_report(report_data: Dict[str, Any]) -> str:
    """Generate an HTML version of the report for browser viewing/printing."""
    name = report_data.get("subject_name", "Unknown Person")
    now = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    
    wiki = report_data.get("wikipedia") or {}
    risk = report_data.get("risk_assessment") or {}
    search = report_data.get("search_summary", {})
    social = report_data.get("social_presence", {})
    aff = report_data.get("affiliations", {})
    pf = report_data.get("public_figure", {})
    narrative = report_data.get("narrative", "")
    
    # Wiki section
    wiki_html = ""
    if wiki.get("found"):
        facts = wiki.get("facts", {})
        wiki_html = f'''
        <div class="section-box">
            <p><strong>{wiki["title"]}</strong> <span class="badge badge-wiki">Wikipedia</span></p>
            {f'<p>Profession: {facts["profession"]}</p>' if facts.get("profession") else ""}
            {f'<p>Nationality: {facts["nationality"]}</p>' if facts.get("nationality") else ""}
            {f'<p>Born: {facts["birth_year"]}{"—" + facts["death_year"] if facts.get("death_year") else ""}</p>' if facts.get("birth_year") else ""}
            {f'<img src="{wiki["thumbnail"]}" style="max-width:150px;border-radius:4px;margin:8px 0">' if wiki.get("thumbnail") else ""}
            {f'<p style="margin-top:10px">{wiki["summary"][:800]}</p>' if wiki.get("summary") else ""}
        </div>'''
    else:
        names = report.get("candidate_names", [])
        wiki_html = f'<p>Name(s): {", ".join(names) if names else "Unknown"}</p><p>No Wikipedia entry found.</p>'
    
    # Risk section
    risk_html = ""
    if risk.get("found"):
        level = risk.get("risk_level", "LOW")
        cls = f"risk-{level.lower()}"
        risk_html = f'''
        <div class="section-box">
            <p class="{cls}">Risk Level: {level}</p>
            <p>Match: {risk.get("name", "")} ({risk.get("match_score", 0):.0%} confidence)</p>
            {f'<p>Categories: {", ".join(risk["topics"])}</p>' if risk.get("topics") else ""}
            {f'<p>Countries: {", ".join(risk["countries"])}</p>' if risk.get("countries") else ""}
        </div>'''
    
    # Assessment badge
    level = pf.get("level", "UNKNOWN").replace("_", " ")
    badge_class = "badge-public" if "PUBLIC" in pf.get("level", "") else "badge-private"
    
    # Search table
    search_rows = ""
    for eng, data in search.get("engines", {}).items():
        search_rows += f'<tr><td>{eng}</td><td>{data.get("url_count", 0)} URLs</td><td>{"⚠" if data.get("has_error") else "✓"}</td></tr>'
    
    # Social table
    social_rows = ""
    accounts = social.get("accounts", [])
    for acc in accounts:
        match = "✓" if acc.get("name_match_score", 0) >= 0.5 else ("~" if acc.get("name_match_score", 0) >= 0.3 else "?")
        social_rows += f'<tr><td>{acc["username"]}</td><td>{", ".join(acc.get("platforms", []))}</td><td>{match} ({acc.get("name_match_score", 0):.0%})</td></tr>'
    
    # Affiliations tags
    org_tags = "".join(f'<span class="tag">{o["name"]}</span>' for o in aff.get("organizations", [])[:10])
    loc_tags = "".join(f'<span class="tag">{l["name"]}</span>' for l in aff.get("locations", [])[:10])
    topic_tags = "".join(f'<span class="tag">{t["name"]}</span>' for t in aff.get("topics", [])[:10])
    
    narrative_html = narrative.replace("\n\n", "</p><p>").replace("\n", "<br>")
    
    return f'''<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
    body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; font-size: 11pt; color: #1a1a1a; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 20px; }}
    h1 {{ font-size: 20pt; margin-bottom: 4px; }}
    h2 {{ font-size: 13pt; margin-top: 22px; margin-bottom: 8px; color: #333; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
    .meta {{ color: #888; font-size: 9pt; margin-bottom: 20px; }}
    .risk-high {{ color: #c00; font-weight: bold; }}
    .risk-medium {{ color: #e67e00; font-weight: bold; }}
    .risk-low {{ color: #27ae60; }}
    table {{ width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 10pt; }}
    th {{ background: #f5f5f5; text-align: left; padding: 6px 8px; border-bottom: 2px solid #ddd; }}
    td {{ padding: 5px 8px; border-bottom: 1px solid #eee; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 9pt; font-weight: 600; }}
    .badge-public {{ background: #dbeafe; color: #1e40af; }}
    .badge-private {{ background: #f0fdf4; color: #166534; }}
    .badge-wiki {{ background: #fef3c7; color: #92400e; }}
    .section-box {{ background: #fafafa; border: 1px solid #eee; border-radius: 4px; padding: 12px 16px; margin: 12px 0; }}
    .tag {{ display: inline-block; background: #f0f0f0; padding: 2px 8px; border-radius: 3px; margin: 2px; font-size: 9pt; }}
    .footer {{ margin-top: 30px; padding-top: 10px; border-top: 1px solid #ddd; font-size: 8pt; color: #999; }}
    @media print {{ body {{ padding: 0; }} }}
</style></head><body>
<h1>Intelligence Report</h1>
<p class="meta">Subject: <strong>{name}</strong> | Generated: {now} | ID: {report.get("report_id", "N/A")[:8]}</p>
<h2>Identity</h2>
{wiki_html}
<h2>Classification</h2>
<p><span class="badge {badge_class}">{level}</span> Confidence: {pf.get("confidence", "N/A")}</p>
{risk_html}
<h2>Digital Footprint</h2>
<table><tr><th>Engine</th><th>Results</th><th>Status</th></tr>{search_rows}<tr style="font-weight:bold"><td>Total</td><td colspan="2">{search.get("total_urls", 0)} URLs</td></tr></table>
{('<h2>Social Media Presence</h2><table><tr><th>Username</th><th>Platforms</th><th>Match</th></tr>' + social_rows + '</table>') if accounts else ''}
{('<h2>Context & Affiliations</h2>' + (f'<h3>Organizations</h3><p>{org_tags}</p>' if org_tags else '') + (f'<h3>Locations</h3><p>{loc_tags}</p>' if loc_tags else '') + (f'<h3>Topics</h3><p>{topic_tags}</p>' if topic_tags else '')) if (org_tags or loc_tags or topic_tags) else ''}
<h2>Narrative Summary</h2>
<div class="section-box"><p>{narrative_html}</p></div>
<div class="footer">Reverse Face Search v2.0 | Generated {now} | Report: {report.get("report_id", "N/A")[:8]}</div>
</body></html>'''


def _build_story(report_data, styles):
    """Build reportlab story — simplified for reliability."""
    from reportlab.platypus import Paragraph, Spacer, HRFlowable
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.colors import HexColor
    
    story = []
    name = report_data.get("subject_name", "Unknown Person")
    
    story.append(Paragraph(f"Intelligence Report", styles["Title"]))
    story.append(Paragraph(f"Subject: <b>{name}</b>", styles["Normal"]))
    story.append(Spacer(1, 12))
    
    narrative = report_data.get("narrative", "No narrative available.")
    for line in narrative.split("\n"):
        if line.startswith("## "):
            story.append(Paragraph(f"<b>{line[3:]}</b>", styles["Heading2"]))
        elif line.strip():
            story.append(Paragraph(line, styles["Normal"]))
        story.append(Spacer(1, 4))
    
    return story
