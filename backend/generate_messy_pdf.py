"""Generate a messy, unorganized test PDF (realistic real-world document)."""

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
import io

def create_messy_pdf(filename="messy_report.pdf"):
    """Create a realistic, messy business report PDF with poor formatting."""
    
    c = canvas.Canvas(filename, pagesize=letter)
    width, height = letter
    
    y = height - 0.5*inch
    
    # Page 1 - Messy start
    c.setFont("Helvetica-Bold", 18)
    c.drawString(0.5*inch, y, "QUARTERLY PERFORMANCE ANALYSIS")
    y -= 0.3*inch
    
    c.setFont("Helvetica", 9)
    c.drawString(0.5*inch, y, "Q4 2025 | Internal Document | Confidential")
    y -= 0.5*inch
    
    # Messy intro
    c.setFont("Helvetica", 10)
    content = [
        "This report summarizes Q4 2025 performance. Data compiled from various sources",
        "including sales CRM, financial reports, and team feedback. Some figures may be",
        "preliminary and subject to revision. Last updated: Jan 14, 2026 @ 11:47 PM",
        "",
        "Executive Summary (DRAFT - NOT FINAL)",
        "=======================================",
        "Q4 saw significant market challenges, particularly in EMEA region. Revenue growth",
        "was 6.2% YoY but only 2.1% QoQ. This is concerning given market conditions. We need",
        "to review strategy asap. John mentioned this in last meeting.",
        "",
        "Key Metrics:",
        "- Total Revenue: $5.2M (was expecting $5.8M - MISSED TARGET)",
        "- Customer churn: 12% (slightly up from 10.5% in Q3)",
        "- New customer acquisition: 87 accounts (down from 112 in Q3)",
        "- Sales team size increased to 24 FTE (was 18 in Q2)",
        "- Avg deal size: $59.7K (up from $54.2K)",
        "",
        "REGIONAL BREAKDOWN",
        "==================",
        "North America: $2.3M (+15% YoY) - This is our strength",
        "  Sub-regions:",
        "  - East Coast: $1.1M",
        "  - West Coast: $0.9M", 
        "  - Central: $0.3M (struggling)",
        "",
        "Europe: $1.8M (-8% YoY) URGENT ISSUE",
        "  Germany: $0.6M (was $0.7M)",
        "  UK: $0.5M",
        "  France: $0.4M",
        "  Other: $0.3M",
        "  [NOTE: Spanish office data missing - still waiting on Maria's report]",
        "",
        "APAC: $1.1M (various issues)",
        "  - Australia performing well: $0.5M",
        "  - Japan stagnant: $0.4M",
        "  - Southeast Asia: $0.2M (new market, high potential)",
        "",
        "SALES TEAM PERFORMANCE",
        "======================",
        "Team restructured in Oct - divided into Enterprise, SMB, Startup verticals",
        "",
        "Enterprise (VP: Robert):",
        "  - 5 sales reps | 3 SDRs",
        "  - Closed deals: 12 (avg $180K)",
        "  - Pipeline: $4.2M (likely to close ~$2.1M)",
        "  - Note: One rep (Mike) underperforming - needs PIP?",
        "",
        "SMB (Manager: Sarah):",
        "  - 8 reps | 5 SDRs",  
        "  - Closed deals: 45 (avg $65K)",
        "  - Pipeline: $2.8M",
        "  - Performance uneven - some reps at $800K/year, others at $400K",
        "",
        "Startup (Manager: Chen): NEW VERTICAL",
        "  - 4 reps | 2 SDRs",
        "  - Closed deals: 30 (avg $28K)",
        "  - Pipeline: $1.5M",
        "  - High volume, low deal size - sustainable?",
        "",
        "POLICY & ORGANIZATIONAL CHANGES",
        "================================",
        "New commission structure effective Oct 1:",
        "  - Increased base from $55K to $60K",
        "  - Commission rate: 8% (was 6%)",
        "  - Accelerators for 150%+ of quota",
        "  - Clawback clause if customer churns within 12mo",
        "",
        "Impact: Payroll increased ~9%, but sales velocity up 14%",
        "Is this sustainable long-term? CFO concerned about margins.",
        "",
        "New CRM system (Salesforce) rollout in Nov - 2 weeks late due to migration issues",
        "Data quality issues persist. ~15% of opportunities lack clear close dates",
        "Training: Minimal (1 hr session) - many reps not using it correctly yet",
        "",
        "MARKET CONDITIONS & COMPETITION",
        "===============================",
        "3 new competitors entered market in Q4:",
        "  1. TechStart Solutions (aggressive pricing, $500K seed funding)",
        "  2. CloudPro Analytics (focusing on Enterprise, backed by VC)",
        "  3. DataFlow Systems (cheaper alternative, targeting SMB/Startup)",
        "",
        "Pricing pressure increasing - had to discount 8 deals (avg 20% off)",
        "Some customers renegotiating contracts. Lost 1 mid-market account to TechStart.",
        "",
        "Market size est. $500M globally (growing ~20% YoY)",
        "Our market share: ~1.04% (was 0.95% in Q3)",
        "",
        "RISKS & CONCERNS",
        "=================",
        "1. Churn rate increasing - need root cause analysis",
        "2. Deal velocity slowing in Q4 (holiday season effect?)",
        "3. New team members (6 hires) still ramping - 3mo to full productivity",
        "4. Sales enablement materials outdated",
        "5. Comp structure complex - errors in payroll last month (fix pending)",
        "6. EMEA region needs strategic review ASAP",
        "",
        "TODO / ACTION ITEMS:",
        "====================",
        "[ ] Review EMEA strategy - assign owner (Robert?)",
        "[ ] Root cause analysis on churn - Hannah (customer success)",
        "[ ] Update sales enablement deck",
        "[ ] CRM training session #2 (Jan 20)",
        "[ ] Evaluate pricing strategy vs competitors",
        "[ ] PIP discussion with Mike - HR involved",
        "[ ] Financial impact analysis of new comp structure",
        "",
        "ASSUMPTIONS",
        "===========",
        "- Market growth continues at 20% YoY",
        "- No major economic downturn in 2026",
        "- 2 competitors will be acquired/fail by end of 2026",
        "- New team members reach 70% productivity by April",
        "- Churn stabilizes to 10% by Q2",
        "- EMEA recovers with strategic focus",
        "",
        "LIMITATIONS OF THIS REPORT",
        "===========================",
        "- EMEA data 2 weeks delayed (still missing Spain/Portugal data)",
        "- CRM data incomplete due to migration issues",
        "- Comp analysis based on Q4 only (seasonal?)",
        "- Customer feedback limited to 12 surveyed (vs 300+ customers)",
        "- Pipeline figures unverified by finance",
        "- Some data pulled manually (error risk)",
        "",
        "Next review: Feb 15, 2026",
        "Prepared by: Sales Analytics Team",
        "Reviewed by: VP Sales, Finance Director (pending)",
    ]
    
    for line in content:
        if y < 0.7*inch:  # Start new page if needed
            c.showPage()
            y = height - 0.5*inch
        
        if line.startswith("="):
            c.setFont("Helvetica-Bold", 10)
        elif line.startswith("["):
            c.setFont("Helvetica-Oblique", 9)
        elif line.startswith("NOTE:") or line.startswith("[NOTE:"):
            c.setFont("Helvetica-Oblique", 9)
        elif line.startswith("-") or line.startswith("  -"):
            c.setFont("Helvetica", 9)
        else:
            c.setFont("Helvetica", 10)
        
        c.drawString(0.5*inch if not line.startswith("  ") else 0.7*inch, y, line)
        y -= 0.18*inch
    
    c.save()
    print(f"✅ Messy realistic PDF created: {filename}")

if __name__ == "__main__":
    try:
        import reportlab
    except ImportError:
        print("Installing reportlab...")
        import subprocess
        subprocess.check_call(["pip", "install", "reportlab"])
    
    create_messy_pdf()
