"""Generate a test PDF for dry-run testing."""

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

def create_test_pdf(filename="test_report.pdf"):
    """Create a sample business report PDF."""
    c = canvas.Canvas(filename, pagesize=letter)
    width, height = letter
    
    # Title
    c.setFont("Helvetica-Bold", 16)
    c.drawString(1*inch, height - 1*inch, "Q4 2025 Sales Performance Report")
    
    # Content
    c.setFont("Helvetica", 11)
    y = height - 1.5*inch
    
    content = [
        "Executive Summary:",
        "",
        "Our Q4 sales performance shows mixed results across regions. The North American",
        "market experienced a 15% growth in revenue, reaching $2.3M compared to Q3's $2.0M.",
        "However, the European market declined by 8%, dropping to $1.8M from $1.95M.",
        "",
        "Key Findings:",
        "",
        "1. Sales Statistics: Total company revenue reached $5.2M in Q4, representing a",
        "   6% increase year-over-year. Customer acquisition cost decreased by 12% while",
        "   retention rate improved to 87%.",
        "",
        "2. Organization Structure: The recent restructuring of the sales team into",
        "   specialized verticals (Enterprise, SMB, and Startup) has shown early positive",
        "   results with a 23% improvement in deal closure rates.",
        "",
        "3. Policy Changes: The new commission structure implemented in October has",
        "   increased sales team motivation but raised operational costs by 9%. Management",
        "   is reviewing the sustainability of this approach.",
        "",
        "4. Market Analysis: Competition intensified in Q4 with three new entrants in",
        "   our primary markets. Price pressure increased, forcing us to adjust our",
        "   pricing strategy for mid-tier offerings.",
        "",
        "Assumptions:",
        "- Market conditions remain stable through Q1 2026",
        "- No major economic downturn occurs",
        "- Current team capacity can handle 20% growth",
        "",
        "Limitations:",
        "- Data from European subsidiaries is delayed by 2 weeks",
        "- Customer satisfaction metrics are based on limited survey responses (28%)",
    ]
    
    for line in content:
        if y < 1*inch:  # Start new page if needed
            c.showPage()
            c.setFont("Helvetica", 11)
            y = height - 1*inch
        
        c.drawString(1*inch, y, line)
        y -= 0.2*inch
    
    c.save()
    print(f"✅ Test PDF created: {filename}")

if __name__ == "__main__":
    # Install reportlab if needed
    try:
        import reportlab
    except ImportError:
        print("Installing reportlab...")
        import subprocess
        subprocess.check_call(["pip", "install", "reportlab"])
    
    create_test_pdf()
