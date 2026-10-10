"""Builds the small fictional demo tender pack in samples/demo_tender/.

Developer tool only: the owner does not need to run this. The files it makes
are already included in the project. Needs reportlab (pip install reportlab).
All wording is invented; none is copied from any standard form of contract.
"""

from pathlib import Path

import docx
import openpyxl
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

OUT = Path(__file__).resolve().parent.parent / "samples" / "demo_tender"
PROJECT = "Riverside Community Centre (fictional demonstration project)"
EMPLOYER = "Northvale Borough Council (fictional)"


def instructions_to_tenderers():
    d = docx.Document()
    d.add_heading("Instructions to Tenderers", 0)
    d.add_paragraph(f"Project: {PROJECT}")
    d.add_paragraph(f"Employer: {EMPLOYER}")
    d.add_heading("1. Tender return", 1)
    d.add_paragraph("Tenders must be returned by 12:00 noon on 31 October 2026. "
                    "Late tenders will not be considered.")
    d.add_heading("2. Clarifications", 1)
    d.add_paragraph("Clarification questions must be submitted no later than 10 working days "
                    "before the tender return date. Questions received after this date will not be answered.")
    d.add_heading("3. Form of contract", 1)
    d.add_paragraph("The contract will be the NEC4 Engineering and Construction Contract, Option A, "
                    "amended by the Schedule of Amendments included in this tender pack.")
    d.add_heading("4. Evaluation", 1)
    d.add_paragraph("Tenders will be evaluated 70% on price and 30% on quality.")
    d.add_heading("5. Qualifications", 1)
    d.add_paragraph("Qualified tenders may be rejected at the Employer's sole discretion.")
    d.add_heading("Key dates", 1)
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Event", "Date"
    for event, date in [("Access date", "5 January 2027"), ("Completion date", "30 November 2027")]:
        row = t.add_row()
        row.cells[0].text, row.cells[1].text = event, date
    d.save(OUT / "Instructions to Tenderers.docx")


def schedule_of_amendments():
    styles = getSampleStyleSheet()
    story = [Paragraph("Schedule of Amendments (Option Z clauses)", styles["Title"]),
             Paragraph(PROJECT, styles["Normal"]), Spacer(1, 12)]
    pages = [
        [("Z1 Order of precedence", "If there is any conflict between the documents, the Scope shall take "
          "precedence over the Contractor's tender and these Z clauses shall take precedence over all other documents."),
         ("Z2 Liability", "The Contractor's total liability to the Employer shall not be limited, save that "
          "liability for indirect or consequential loss is excluded."),
         ("Z3 Ground conditions", "The Contractor is deemed to have inspected the Site and satisfied itself as "
          "to the ground conditions. No compensation event arises from physical conditions within the Site.")],
        [("Z4 Payment", "The Employer pays within 45 days of the assessment date. Retention is 5% of the "
          "Price for Work Done to Date, half of which is released at Completion."),
         ("Z5 Notification", "A compensation event not notified by the Contractor within 4 weeks of becoming "
          "aware of it is time-barred."),
         ("Z6 Delay damages", "Delay damages are GBP 15,000 per week. The total of delay damages is not capped.")],
        [("Z7 Termination", "The Employer may terminate the Contractor's obligation to Provide the Works at any "
          "time for its convenience. The Contractor is not entitled to loss of profit on work not carried out."),
         ("Z8 Price", "The Prices are fixed for the duration of the contract and are not subject to adjustment "
          "for inflation."),
         ("Z9 Security", "The Contractor provides a performance bond of 10% of the total of the Prices and a "
          "parent company guarantee.")],
    ]
    for i, clauses in enumerate(pages):
        for heading, text in clauses:
            story += [Paragraph(heading, styles["Heading2"]), Paragraph(text, styles["Normal"]), Spacer(1, 8)]
        if i < len(pages) - 1:
            story.append(PageBreak())
    SimpleDocTemplate(str(OUT / "Schedule of Amendments.pdf"), pagesize=A4).build(story)


def pricing_schedule():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Pricing"
    ws.append(["Item", "Description", "Unit", "Quantity", "Rate (GBP)", "Total (GBP)"])
    for row in [
        ("1.1", "Site set-up and welfare", "item", 1, None, None),
        ("2.1", "Demolition of existing pavilion", "item", 1, None, None),
        ("3.1", "Piled foundations", "nr", 64, None, None),
        ("4.1", "Steel frame", "t", 85, None, None),
        ("5.1", "Provisional sum: diversion of existing water main", "item", 1, 40000, 40000),
        ("6.1", "Contractor's design: mechanical and electrical services (fit for purpose)", "item", 1, None, None),
    ]:
        ws.append(list(row))
    notes = wb.create_sheet("Notes")
    notes.append(["Tenderers must price all items. Unpriced items are deemed included elsewhere."])
    notes.append(["The site investigation report (2019) is provided for information only."])
    wb.save(OUT / "Pricing Schedule.xlsx")


def site_notes():
    (OUT / "Site Information.txt").write_text(
        "Site Information\n\n"
        "The site is a former industrial yard. A site investigation was carried out in 2019 with three "
        "boreholes. Made ground up to 3 m deep was found. Asbestos may be present in the existing pavilion.\n"
        "Access is from Mill Lane only, which is shared with a primary school. No deliveries between "
        "08:15-09:00 and 15:00-15:45 on school days.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    instructions_to_tenderers()
    schedule_of_amendments()
    pricing_schedule()
    site_notes()
    print(f"Demo pack written to {OUT}")
