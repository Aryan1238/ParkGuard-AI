import os
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def generate_pdf_challan(violation_data, output_pdf_path):
    """
    Generates a professional Digital Traffic Challan PDF report.
    """
    doc = SimpleDocTemplate(
        output_pdf_path,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    # Custom Styles
    title_style = ParagraphStyle(
        'HeaderTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#1E293B'),
        alignment=1 # Centered
    )
    
    subtitle_style = ParagraphStyle(
        'HeaderSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#64748B'),
        alignment=1
    )
    
    section_heading = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#0F172A'),
        spaceAfter=6
    )
    
    body_bold = ParagraphStyle(
        'BodyBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#334155')
    )
    
    body_normal = ParagraphStyle(
        'BodyNormal',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#475569')
    )
    
    fine_style = ParagraphStyle(
        'FineStyle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=22,
        leading=26,
        textColor=colors.HexColor('#DC2626'),
        alignment=1
    )

    # 1. Header Section
    story.append(Paragraph("SMART CITY TRAFFIC ENFORCEMENT AUTHORITY", title_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Automated No-Parking Zone Monitoring System | Digital Violation Challan", subtitle_style))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#2563EB'), spaceAfter=15))

    # 2. Key Summary Table
    code = violation_data.get('violation_code', 'CHAL-UNKNOWN')
    timestamp = violation_data.get('timestamp', 'N/A')
    status = violation_data.get('status', 'Unpaid').upper()
    status_color = colors.HexColor('#DC2626') if status == 'UNPAID' else colors.HexColor('#16A34A')
    
    summary_data = [
        [
            Paragraph("<b>CHALLAN NO:</b> " + code, body_bold),
            Paragraph("<b>DATE & TIME:</b> " + str(timestamp), body_bold),
            Paragraph(f"<b>STATUS:</b> <font color='{status_color.hexval()}'>{status}</font>", body_bold)
        ]
    ]
    
    summary_table = Table(summary_data, colWidths=[2.2*inch, 3.2*inch, 2.1*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#E2E8F0')),
        ('PADDING', (0,0), (-1,-1), 8),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 15))

    # 3. Offence & Vehicle Details
    story.append(Paragraph("OFFENCE & VEHICLE DETAILS", section_heading))
    
    plate_no = violation_data.get('plate_number', 'UNKNOWN')
    veh_type = violation_data.get('vehicle_type', 'Vehicle').capitalize()
    dwell_sec = violation_data.get('dwell_time_seconds', 0)
    location = violation_data.get('location', 'Zone A - Main Gate Corridor')
    fine_amt = violation_data.get('fine_amount', 1000.0)

    details_data = [
        [Paragraph("Offence Type:", body_bold), Paragraph("Unauthorized Parking in No-Parking Zone", body_normal)],
        [Paragraph("Vehicle Type:", body_bold), Paragraph(veh_type, body_normal)],
        [Paragraph("Registration No:", body_bold), Paragraph(f"<font size='12' color='#1E293B'><b>{plate_no}</b></font>", body_normal)],
        [Paragraph("Violation Location:", body_bold), Paragraph(location, body_normal)],
        [Paragraph("Recorded Dwell Time:", body_bold), Paragraph(f"{dwell_sec} seconds (Exceeded maximum allowed threshold)", body_normal)],
        [Paragraph("Enforcement Rule:", body_bold), Paragraph("Motor Vehicles Act Section 122/177 - Illegal Obstruction", body_normal)]
    ]
    
    details_table = Table(details_data, colWidths=[2.0*inch, 5.5*inch])
    details_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#F1F5F9')),
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#F8FAFC')),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(details_table)
    story.append(Spacer(1, 15))

    # 4. Evidence Snapshots
    story.append(Paragraph("CAMERA EVIDENCE SNAPSHOTS", section_heading))
    
    snapshot_path = violation_data.get('snapshot_path')
    plate_crop_path = violation_data.get('plate_crop_path')
    
    img_cells = []
    
    if snapshot_path and os.path.exists(snapshot_path):
        img_cells.append(Image(snapshot_path, width=3.6*inch, height=2.2*inch))
    else:
        img_cells.append(Paragraph("[Camera Snapshot Unavailable]", body_normal))
        
    if plate_crop_path and os.path.exists(plate_crop_path):
        img_cells.append(Image(plate_crop_path, width=3.6*inch, height=2.2*inch))
    else:
        img_cells.append(Paragraph("[Plate Crop Image Unavailable]", body_normal))

    evidence_table = Table([img_cells], colWidths=[3.7*inch, 3.7*inch])
    evidence_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#CBD5E1')),
        ('PADDING', (0,0), (-1,-1), 6),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC'))
    ]))
    story.append(evidence_table)
    story.append(Spacer(1, 15))

    # 5. Penalty & Payment Instructions
    story.append(Paragraph("PENALTY AMOUNT & DIGITAL PAYMENT", section_heading))
    
    payment_box_data = [
        [
            Paragraph(f"PENALTY AMOUNT: <b>₹{fine_amt:,.2f}</b>", fine_style),
        ],
        [
            Paragraph("Please pay the fine within 15 days of issue to avoid court escalation.<br/>"
                      "Scan the QR code or pay online at <b>https://traffic.smartcity.gov.in/pay</b>", subtitle_style)
        ]
    ]
    
    payment_table = Table(payment_box_data, colWidths=[7.4*inch])
    payment_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#FEF2F2')),
        ('BOX', (0,0), (-1,-1), 1.5, colors.HexColor('#FCA5A5')),
        ('PADDING', (0,0), (-1,-1), 10),
        ('ALIGN', (0,0), (-1,-1), 'CENTER')
    ]))
    story.append(payment_table)
    story.append(Spacer(1, 15))
    
    # 6. Footer Disclaimer
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#CBD5E1'), spaceAfter=8))
    story.append(Paragraph("This is an computer-generated legal digital challan issued by the Autonomous AI Surveillance System. No physical signature required.", subtitle_style))

    doc.build(story)
    return output_pdf_path

if __name__ == '__main__':
    # Simple test run
    test_data = {
        'violation_code': 'CHAL-20260814-998',
        'timestamp': '2026-08-14 15:30:00',
        'plate_number': 'MH 12 AB 1234',
        'vehicle_type': 'car',
        'dwell_time_seconds': 45,
        'fine_amount': 1000.0,
        'status': 'Unpaid'
    }
    output_path = os.path.join(os.path.dirname(__file__), 'test_challan.pdf')
    generate_pdf_challan(test_data, output_path)
    print(f"Generated test PDF: {output_path}")
