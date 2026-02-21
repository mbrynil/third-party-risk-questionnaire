"""Server-side PDF (WeasyPrint) and CSV export helpers."""

import csv
import io
from datetime import datetime

from sqlalchemy.orm import Session

from app import templates
from models import (
    Vendor, Assessment, Response, Question, RemediationItem, AssessmentDecision,
    VENDOR_STATUS_ACTIVE, DECISION_STATUS_FINAL,
    REMEDIATION_STATUS_LABELS,
)
from app.services.portfolio import get_portfolio_data, RISK_LABELS, DECISION_LABELS
from app.services.remediation_service import get_portfolio_remediation_summary
from app.services.tiering import get_effective_tier


# ---------------------------------------------------------------------------
# Template → HTML → PDF (lazy WeasyPrint import)
# ---------------------------------------------------------------------------

def render_template_to_html(template_name: str, context: dict) -> str:
    """Render a Jinja2 template to an HTML string."""
    tmpl = templates.env.get_template(template_name)
    return tmpl.render(**context)


def render_html_to_pdf(html_string: str) -> bytes:
    """Convert an HTML string to PDF bytes via WeasyPrint.

    WeasyPrint is imported lazily because it depends on GTK3/Pango system
    libraries that may not be available on all platforms (notably Windows
    without MSYS2).  When the libraries are missing the import will raise
    an OSError which is re-raised as a RuntimeError with install guidance.
    """
    try:
        from weasyprint import HTML
    except OSError as exc:
        raise RuntimeError(
            "PDF generation requires GTK3 system libraries. "
            "On Windows install MSYS2 (https://www.msys2.org) then run: "
            "pacman -S mingw-w64-x86_64-pango"
        ) from exc
    return HTML(string=html_string).write_pdf()


def generate_submission_pdf(context: dict) -> bytes:
    """Render export.html (vendor submission report) → PDF."""
    html = render_template_to_html("export.html", context)
    return render_html_to_pdf(html)


def generate_assessment_report_pdf(context: dict) -> bytes:
    """Render assessment_report.html → PDF."""
    html = render_template_to_html("assessment_report.html", context)
    return render_html_to_pdf(html)


def generate_portfolio_report_pdf(context: dict) -> bytes:
    """Render portfolio_report.html → PDF."""
    html = render_template_to_html("portfolio_report.html", context)
    return render_html_to_pdf(html)


def generate_report_card_pdf(context: dict) -> bytes:
    """Render vendor_report_card.html → PDF."""
    html = render_template_to_html("vendor_report_card.html", context)
    return render_html_to_pdf(html)


def generate_control_test_pdf(context: dict) -> bytes:
    """Render control_test_report.html → PDF."""
    html = render_template_to_html("control_test_report.html", context)
    return render_html_to_pdf(html)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def _csv_string(rows: list[list], headers: list[str]) -> str:
    """Write rows to an in-memory CSV string."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    return buf.getvalue()


def generate_vendor_list_csv(db: Session) -> str:
    """All vendors with enrichment, tier, latest score and decision."""
    data = get_portfolio_data(db)
    headers = [
        "Vendor", "Status", "Industry", "Service Type",
        "Data Classification", "Business Criticality", "Access Level",
        "Inherent Risk Tier", "Risk Rating", "Decision Outcome",
        "Overall Score", "Last Assessed", "Next Review",
    ]
    rows = []
    vendors = db.query(Vendor).order_by(Vendor.name).all()
    vendor_map = {v["id"]: v for v in data["vendors"]}
    for v in vendors:
        vr = vendor_map.get(v.id, {})
        rows.append([
            v.name,
            v.status,
            v.industry or "",
            v.service_type or "",
            v.data_classification or "",
            v.business_criticality or "",
            v.access_level or "",
            get_effective_tier(v) or "",
            vr.get("risk_rating_display", "") or "",
            vr.get("decision_outcome_display", "") or "",
            vr.get("overall_score", "") if vr.get("overall_score") is not None else "",
            vr.get("last_assessed_date", "") or "",
            vr.get("next_review_date", "") or "",
        ])
    return _csv_string(rows, headers)


def generate_assessment_tracker_csv(db: Session) -> str:
    """All assessments with status, scores, reminder counts."""
    from sqlalchemy import func
    from models import ReminderLog, REMINDER_TYPE_REMINDER

    now = datetime.utcnow()
    assessments = db.query(Assessment).order_by(Assessment.created_at.desc()).all()
    assessment_ids = [a.id for a in assessments]

    reminder_counts = {}
    if assessment_ids:
        counts = db.query(
            ReminderLog.assessment_id, func.count(ReminderLog.id)
        ).filter(
            ReminderLog.assessment_id.in_(assessment_ids),
            ReminderLog.reminder_type == REMINDER_TYPE_REMINDER,
        ).group_by(ReminderLog.assessment_id).all()
        reminder_counts = {aid: cnt for aid, cnt in counts}

    decisions_list = db.query(AssessmentDecision).filter(
        AssessmentDecision.assessment_id.in_(assessment_ids)
    ).all() if assessment_ids else []
    decisions = {d.assessment_id: d for d in decisions_list}

    headers = [
        "Assessment", "Vendor", "Status", "Created", "Sent",
        "Submitted", "Days Waiting", "Reminders Sent",
        "Risk Rating", "Decision", "Score",
    ]
    rows = []
    for a in assessments:
        days_waiting = ""
        if a.sent_at and a.status in ("SENT", "IN_PROGRESS"):
            days_waiting = (now - a.sent_at).days

        decision = decisions.get(a.id)
        rows.append([
            a.title,
            a.vendor.name if a.vendor else a.company_name,
            a.status,
            a.created_at.strftime("%Y-%m-%d") if a.created_at else "",
            a.sent_at.strftime("%Y-%m-%d") if a.sent_at else "",
            a.submitted_at.strftime("%Y-%m-%d") if a.submitted_at else "",
            days_waiting,
            reminder_counts.get(a.id, 0),
            RISK_LABELS.get(decision.overall_risk_rating, "") if decision and decision.overall_risk_rating else "",
            DECISION_LABELS.get(decision.decision_outcome, "") if decision and decision.decision_outcome else "",
            decision.overall_score if decision and decision.overall_score is not None else "",
        ])
    return _csv_string(rows, headers)


def generate_remediation_csv(db: Session) -> str:
    """All remediation items."""
    items = db.query(RemediationItem).order_by(RemediationItem.created_at.desc()).all()
    headers = [
        "ID", "Vendor", "Title", "Category", "Severity", "Status",
        "Assigned To", "Due Date", "Completed Date", "Source", "Created",
    ]
    rows = []
    for i in items:
        rows.append([
            i.id,
            i.vendor.name if i.vendor else "",
            i.title,
            i.category or "",
            i.severity,
            REMEDIATION_STATUS_LABELS.get(i.status, i.status),
            i.assigned_to or "",
            i.due_date.strftime("%Y-%m-%d") if i.due_date else "",
            i.completed_date.strftime("%Y-%m-%d") if i.completed_date else "",
            i.source,
            i.created_at.strftime("%Y-%m-%d") if i.created_at else "",
        ])
    return _csv_string(rows, headers)


def generate_assessment_responses_csv(db: Session, submission_id: int) -> str:
    """Questions + answers for one submission."""
    response = db.query(Response).filter(Response.id == submission_id).first()
    if not response:
        return ""
    assessment = db.query(Assessment).filter(Assessment.id == response.assessment_id).first()
    questions = db.query(Question).filter(
        Question.assessment_id == assessment.id
    ).order_by(Question.order).all()

    answers_dict = {a.question_id: a for a in response.answers}

    headers = [
        "Question #", "Category", "Question", "Weight",
        "Answer", "Notes",
    ]
    rows = []
    for idx, q in enumerate(questions, 1):
        answer = answers_dict.get(q.id)
        rows.append([
            idx,
            q.category or "",
            q.question_text,
            q.weight or "MEDIUM",
            answer.answer_choice if answer and answer.answer_choice else "",
            answer.notes if answer and answer.notes else "",
        ])
    return _csv_string(rows, headers)
