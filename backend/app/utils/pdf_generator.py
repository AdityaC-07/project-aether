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
from reportlab.graphics.shapes import Drawing, Rect, String


class AETHERPDFGenerator:
    """Generate professional PDF reports from AETHER analysis."""

    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._create_custom_styles()

    @staticmethod
    def _format_domain_name(domain: str) -> str:
        """Convert domain enum to readable name."""
        domain_map = {
            'sales': 'Sales',
            'organization': 'Organization',
            'policy': 'Policy',
            'statistics': 'Statistics',
        }
        return domain_map.get(domain.lower(), domain)

    def _importance_drawing(self, rankings: List[Dict[str, Any]]) -> Drawing:
        """Horizontal bar chart of factor importance (relative contribution)."""
        bar_width_max = 220
        row_height = 26
        chart = Drawing(width=360, height=max(40, len(rankings) * row_height + 10))
        for index, entry in enumerate(rankings):
            y = len(rankings) * row_height - index * row_height - row_height
            label = entry.get('factor_id', '?')
            importance = entry.get('importance', 0)
            contribution = entry.get('contribution', 0)
            color = (
                colors.HexColor('#3b82f6')
                if contribution >= 0
                else colors.HexColor('#ef4444')
            )
            chart.add(String(2, y + 8, label, fontName='Helvetica-Bold', fontSize=10))
            bar_width = max(3, int(importance * bar_width_max))
            chart.add(Rect(70, y + 2, bar_width, 16, fillColor=color, strokeColor=None))
            chart.add(String(
                78 + bar_width,
                y + 8,
                f"{importance:.0%}  ({contribution:+.3f})",
                fontName='Helvetica',
                fontSize=8,
            ))
        return chart

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
        story.append(Paragraph("AI-Powered Debate & Synthesis Report", self.styles['CustomTitle']))
        story.append(Spacer(1, 0.2*inch))

        # Metadata
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        story.append(Paragraph(f"<b>Generated:</b> {timestamp}", self.styles['Normal']))
        
        # Confidence Score at top
        final_report = analysis_result.get('final_report', {})
        confidence = final_report.get('confidence_score', 0)
        story.append(Paragraph(f"<b>Confidence Score:</b> {confidence}%", self.styles['Normal']))

        # Nuanced confidence breakdown
        confidence_report = final_report.get('confidence_report') or {}
        if confidence_report:
            synth_conf = confidence_report.get('synthesizer_confidence', 0)
            breakdown = confidence_report.get('uncertainty_breakdown', {})
            story.append(Paragraph(
                f"<b>Synthesizer Confidence:</b> {synth_conf}% (consensus reached across the debate)",
                self.styles['Normal']
            ))
            if breakdown:
                breakdown_text = ", ".join(
                    f"{key}: {value:.0%}" for key, value in breakdown.items()
                )
                story.append(Paragraph(f"<b>Uncertainty Breakdown:</b> {breakdown_text}", self.styles['Normal']))

            uncertain_factors = confidence_report.get('uncertain_factors', [])
            if uncertain_factors:
                story.append(Paragraph("<b>Uncertain Factors:</b>", self.styles['Normal']))
                for factor in uncertain_factors:
                    story.append(Paragraph(
                        f"&nbsp;&nbsp;{factor.get('factor_id', '')}: "
                        f"confidence {factor.get('confidence', 0)}% "
                        f"({factor.get('uncertainty_source', 'unknown')}, "
                        f"magnitude {factor.get('magnitude', 0):.0%}) - "
                        f"{factor.get('reason', '')}",
                        self.styles['Normal'],
                    ))
        story.append(Spacer(1, 0.3*inch))

        # Factor importance: permutation-based visual summary
        feature_importance = final_report.get('feature_importance') or {}
        rankings = feature_importance.get('rankings') or []
        if rankings:
            story.append(Paragraph("Factor Importance", self.styles['CustomHeading']))
            story.append(Paragraph(
                "Which factors most influenced the final recommendation. Bars show each "
                "factor's relative contribution to synthesis quality (permutation analysis: "
                "quality change when the factor is removed; blue = positive, red = negative).",
                self.styles['Normal'],
            ))
            story.append(Spacer(1, 0.1*inch))
            story.append(self._importance_drawing(rankings))
            story.append(Spacer(1, 0.1*inch))
            for entry in rankings:
                drivers = entry.get('driver_arguments') or []
                if drivers:
                    story.append(Paragraph(
                        f"<b>{entry.get('factor_id', '')}</b> top arguments: {'; '.join(drivers)}",
                        self.styles['Normal'],
                    ))
            counterfactuals = final_report.get('counterfactuals') or []
            if counterfactuals:
                story.append(Spacer(1, 0.1*inch))
                story.append(Paragraph("<b>What if a factor were removed?</b>", self.styles['Normal']))
                for cf in counterfactuals:
                    story.append(Paragraph(
                        f"&nbsp;&nbsp;Without <b>{cf.get('factor_id', '')}</b> "
                        f"(contribution {cf.get('contribution', 0):+.3f}): "
                        f"{cf.get('explanation', '')}",
                        self.styles['Normal'],
                    ))
            story.append(Spacer(1, 0.3*inch))

        # Executive Summary Section (Final Report at the top)
        if final_report:
            story.append(Paragraph("Executive Summary", self.styles['CustomHeading']))
            story.append(Spacer(1, 0.1*inch))
            
            # What Worked
            what_worked = final_report.get('what_worked', '')
            if what_worked:
                story.append(Paragraph("<b>What Worked:</b>", self.styles['Normal']))
                story.append(Paragraph(what_worked, self.styles['AetherBodyText']))
                story.append(Spacer(1, 0.15*inch))
            
            # What Failed
            what_failed = final_report.get('what_failed', '')
            if what_failed:
                story.append(Paragraph("<b>What Failed:</b>", self.styles['Normal']))
                story.append(Paragraph(what_failed, self.styles['AetherBodyText']))
                story.append(Spacer(1, 0.15*inch))
            
            # Why It Happened
            why_it_happened = final_report.get('why_it_happened', '')
            if why_it_happened:
                story.append(Paragraph("<b>Why It Happened:</b>", self.styles['Normal']))
                story.append(Paragraph(why_it_happened, self.styles['AetherBodyText']))
                story.append(Spacer(1, 0.15*inch))
            
            # How to Improve
            how_to_improve = final_report.get('how_to_improve', '')
            if how_to_improve:
                story.append(Paragraph("<b>How to Improve:</b>", self.styles['Normal']))
                story.append(Paragraph(how_to_improve, self.styles['AetherBodyText']))
                story.append(Spacer(1, 0.15*inch))
            
            # Synthesis
            synthesis = final_report.get('synthesis', '')
            if synthesis:
                story.append(Paragraph("<b>Synthesis:</b>", self.styles['Normal']))
                story.append(Paragraph(synthesis, self.styles['AetherBodyText']))
                story.append(Spacer(1, 0.15*inch))
            
            # Recommendation
            recommendation = final_report.get('recommendation', '')
            if recommendation:
                story.append(Paragraph("<b>Recommendation:</b>", self.styles['Normal']))
                story.append(Paragraph(recommendation, self.styles['AetherBodyText']))
                story.append(Spacer(1, 0.3*inch))

        # Input Context Section
        if input_text:
            story.append(PageBreak())
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
                formatted_domain = self._format_domain_name(domain)
                story.append(Paragraph(f"<i>Domain: {formatted_domain}</i>", self.styles['Normal']))
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
                story.append(Spacer(1, 0.1*inch))
                
                # Support Arguments
                support = debate.get('support', {})
                if support:
                    story.append(Paragraph("<u>Support Arguments:</u>", self.styles['Normal']))
                    story.append(Spacer(1, 0.05*inch))
                    
                    support_args = support.get('support_arguments', [])
                    for idx, arg in enumerate(support_args, 1):
                        # Format as structured argument
                        claim = arg.get('claim', 'N/A')
                        evidence = arg.get('evidence', 'N/A')
                        assumption = arg.get('assumption', 'N/A')
                        
                        story.append(Paragraph(f"<b>{idx}. Claim:</b> {claim}", self.styles['AetherBodyText']))
                        story.append(Paragraph(f"<b>Evidence:</b> {evidence}", self.styles['Normal']))
                        story.append(Paragraph(f"<b>Assumption:</b> {assumption}", self.styles['Normal']))
                        story.append(Spacer(1, 0.1*inch))
                
                # Opposition Arguments
                opposition = debate.get('opposition', {})
                if opposition:
                    story.append(Paragraph("<u>Opposition Arguments:</u>", self.styles['Normal']))
                    story.append(Spacer(1, 0.05*inch))
                    
                    counter_args = opposition.get('counter_arguments', [])
                    for idx, counter in enumerate(counter_args, 1):
                        # Format as structured counter-argument
                        target_claim = counter.get('target_claim', 'N/A')
                        challenge = counter.get('challenge', 'N/A')
                        risk = counter.get('risk', 'N/A')
                        
                        story.append(Paragraph(f"<b>{idx}. Target Claim:</b> {target_claim}", self.styles['AetherBodyText']))
                        story.append(Paragraph(f"<b>Challenge:</b> {challenge}", self.styles['Normal']))
                        story.append(Paragraph(f"<b>Risk:</b> {risk}", self.styles['Normal']))
                        story.append(Spacer(1, 0.1*inch))
                
                story.append(Spacer(1, 0.2*inch))

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
