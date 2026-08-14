"""
Weekly wellness report -- aggregates journal + prediction + habit data for
the last 7 days into a PDF via reportlab (see /mnt/skills/public/pdf/SKILL.md
guidance -- reportlab is the right tool for generating a new PDF from
scratch, as opposed to pypdf/pdfplumber which are for reading/editing
existing ones).
"""
import io
from datetime import datetime, timedelta, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from database.db import get_dashboard_data, get_habit_status

TEAL = colors.HexColor("#0EA5A0")
INK = colors.HexColor("#0B1120")
SLATE = colors.HexColor("#64748B")


def build_weekly_report_pdf(user_row) -> bytes:
    data = get_dashboard_data(user_row["id"], days=7)
    habits = get_habit_status(user_row["id"])

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.7 * inch, bottomMargin=0.7 * inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleTeal", parent=styles["Title"], textColor=INK)
    heading_style = ParagraphStyle("HeadingTeal", parent=styles["Heading2"], textColor=TEAL, spaceBefore=16)
    body_style = ParagraphStyle("Body", parent=styles["Normal"], textColor=INK, leading=15)
    muted_style = ParagraphStyle("Muted", parent=styles["Normal"], textColor=SLATE, fontSize=9)

    story = []
    today = datetime.now(timezone.utc).date()
    week_start = today - timedelta(days=6)
    story.append(Paragraph("Kivora — Weekly Report", title_style))
    story.append(Paragraph(f"{user_row['name']} · {week_start.isoformat()} to {today.isoformat()}", muted_style))
    story.append(Spacer(1, 16))

    # ---- Summary stats table ----
    story.append(Paragraph("This Week At a Glance", heading_style))
    summary_rows = [
        ["Journal entries", str(data["total_journal_entries"])],
        ["Assessments run", str(data["total_predictions"])],
        ["Most common mood", data["most_common_emotion"] or "—"],
        ["Average sentiment", str(data["average_sentiment"]) if data["average_sentiment"] is not None else "—"],
        ["Current journal streak", f"{data['journal_streak_days']} day(s)"],
    ]
    table = Table(summary_rows, colWidths=[2.5 * inch, 3 * inch])
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), SLATE),
        ("TEXTCOLOR", (1, 0), (1, -1), INK),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, colors.HexColor("#E2E8F0")),
    ]))
    story.append(table)

    # ---- Mood distribution ----
    story.append(Paragraph("Mood Distribution", heading_style))
    dist = data["emotion_distribution"]
    if dist:
        rows = [[emotion, str(count)] for emotion, count in sorted(dist.items(), key=lambda x: -x[1])]
        t = Table(rows, colWidths=[2.5 * inch, 1 * inch])
        t.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("TEXTCOLOR", (0, 0), (-1, -1), INK),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No journal entries this week.", body_style))

    # ---- Wellbeing trend ----
    story.append(Paragraph("Wellbeing Score Trend", heading_style))
    if data["wellbeing_trend"]:
        rows = [["Date", "Score"]] + [[p["date"], str(p["wellbeing_score"])] for p in data["wellbeing_trend"]]
        t = Table(rows, colWidths=[2.5 * inch, 1 * inch])
        t.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
            ("TEXTCOLOR", (0, 0), (-1, -1), INK),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No assessments run this week.", body_style))

    # ---- Habits ----
    story.append(Paragraph("Habit Streaks", heading_style))
    if habits:
        rows = [["Habit", "Streak", "Total check-ins"]] + [
            [h["name"], f"{h['streak']} day(s)", str(h["total_checkins"])] for h in habits
        ]
        t = Table(rows, colWidths=[2.5 * inch, 1.3 * inch, 1.5 * inch])
        t.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
            ("TEXTCOLOR", (0, 0), (-1, -1), INK),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No habits being tracked yet.", body_style))

    story.append(Spacer(1, 24))
    story.append(Paragraph(
        "This report summarizes app usage patterns and self-reported mood. It is not a "
        "clinical assessment. If you're struggling, please reach out to a mental health "
        "professional or a crisis line.",
        muted_style,
    ))

    doc.build(story)
    return buf.getvalue()
