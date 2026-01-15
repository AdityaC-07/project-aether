"""PDF report generation for AETHER analysis results."""

from io import BytesIO
from typing import Any, Dict, List
from datetime import datetime
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY


class AETHERPDFGenerator:
    """Generate professional PDF reports from AETHER analysis."""

    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._create_custom_styles()

    def _create_custom_styles(self):
        """Create custom paragraph styles."""
        # Only add styles if they don't already exist
        if 'CustomTitle' not in self.styles:
            self.styles.add(ParagraphStyle(
                name='CustomTitle',
                parent=self.styles['Heading1'],
                fontSize=28,
                textColor=colors.HexColor('#3b82f6'),
                spaceAfter=30,
                alignment=TA_CENTER,
                fontName='Helvetica-Bold',
            ))

        if 'CustomHeading' not in self.styles:
            self.styles.add(ParagraphStyle(
                name='CustomHeading',
                parent=self.styles['Heading2'],
                fontSize=16,
                textColor=colors.HexColor('#1f2937'),
                spaceAfter=12,
                spaceBefore=12,
                fontName='Helvetica-Bold',
            ))

        if 'FactorID' not in self.styles:
            self.styles.add(ParagraphStyle(
                name='FactorID',
                fontSize=11,
                textColor=colors.HexColor('#3b82f6'),
                fontName='Helvetica-Bold',
            ))

        if 'AetherBodyText' not in self.styles:
            self.styles.add(ParagraphStyle(
                name='AetherBodyText',
                fontSize=11,
                alignment=TA_JUSTIFY,
                spaceAfter=12,
            ))

    def generate_report(self, analysis_result: Dict[str, Any], input_text: str = "") -> bytes:
        """Generate a PDF report from analysis results."""
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.75*inch, bottomMargin=0.75*inch)
        story = []

        # Title
        story.append(Paragraph("🧠 PROJECT AETHER", self.styles['CustomTitle']))
        story.append(Paragraph("AI-Powered Debate & Synthesis System", self.styles['Heading2']))
        story.append(Spacer(1, 0.2*inch))

        # Metadata
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        story.append(Paragraph(f"<b>Generated:</b> {timestamp}", self.styles['Normal']))
        story.append(Spacer(1, 0.3*inch))

        # Input Context Section
        if input_text:
            story.append(Paragraph("Input Context", self.styles['CustomHeading']))
            story.append(Paragraph(input_text[:500] + ("..." if len(input_text) > 500 else ""), self.styles['AetherBodyText']))
            story.append(Spacer(1, 0.2*inch))

        # Factors Section
        factors = analysis_result.get('factors', [])
        if factors:
            story.append(Paragraph("Extracted Factors", self.styles['CustomHeading']))
            for idx, factor in enumerate(factors, 1):
                factor_text = f"<b>Factor {idx}:</b> {factor.get('description', 'N/A')}"
                story.append(Paragraph(factor_text, self.styles['AetherBodyText']))
                domain = factor.get('domain', 'Unknown')
                story.append(Paragraph(f"<i>Domain: {domain}</i>", self.styles['Normal']))
                story.append(Spacer(1, 0.1*inch))
            story.append(Spacer(1, 0.2*inch))

        # Debate Logs Section
        debate_logs = analysis_result.get('debate_logs', [])
        if debate_logs:
            story.append(PageBreak())
            story.append(Paragraph("Debate Analysis", self.styles['CustomHeading']))
            
            for debate in debate_logs:
                factor = debate.get('factor', {})
                story.append(Paragraph(f"<b>{factor.get('description', 'Factor')}</b>", self.styles['Heading3']))
                
                support = debate.get('support', {})
                if support:
                    story.append(Paragraph("<u>Support Arguments:</u>", self.styles['Normal']))
                    args = support.get('arguments', [])
                    for arg in args[:3]:  # Limit to 3 arguments per section
                        story.append(Paragraph(f"• {arg}", self.styles['AetherBodyText']))
                
                opposition = debate.get('opposition', {})
                if opposition:
                    story.append(Paragraph("<u>Opposition Arguments:</u>", self.styles['Normal']))
                    counters = opposition.get('counter_arguments', [])
                    for counter in counters[:3]:
                        story.append(Paragraph(f"• {counter}", self.styles['AetherBodyText']))
                
                story.append(Spacer(1, 0.15*inch))

        # Final Report Section
        final_report = analysis_result.get('final_report', {})
        if final_report:
            story.append(PageBreak())
            story.append(Paragraph("Synthesis & Recommendation", self.styles['CustomHeading']))
            
            synthesis = final_report.get('synthesis', 'No synthesis available.')
            story.append(Paragraph(synthesis, self.styles['AetherBodyText']))
            
            story.append(Spacer(1, 0.2*inch))
            
            recommendation = final_report.get('recommendation', 'No recommendation available.')
            story.append(Paragraph("<b>Recommendation:</b>", self.styles['Normal']))
            story.append(Paragraph(recommendation, self.styles['AetherBodyText']))
            
            confidence = final_report.get('confidence_score', 0)
            story.append(Spacer(1, 0.1*inch))
            story.append(Paragraph(f"<b>Confidence Score:</b> {confidence}%", self.styles['Normal']))

        # Footer
        story.append(Spacer(1, 0.3*inch))
        story.append(Paragraph(
            "This report was generated by Project AETHER, an AI-powered debate and synthesis system.",
            self.styles['Normal']
        ))

        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue()
