"""PDF report generation service using WeasyPrint."""

from io import BytesIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from weasyprint import CSS, HTML  # type: ignore[import-untyped]

from backend.models.report import AnalysisReport


class PDFGenerator:
    """Generates PDF reports from analysis data using WeasyPrint."""

    def __init__(self) -> None:
        template_dir = Path(__file__).parent.parent / "templates" / "pdf"
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=True,
        )
        self.css_path = template_dir / "styles.css"

    def generate(self, report: AnalysisReport) -> bytes:
        """
        Generate a PDF from an analysis report.

        Args:
            report: The analysis report to convert to PDF

        Returns:
            PDF file contents as bytes
        """
        template = self.env.get_template("report.html")

        # Prepare template context
        red_flags = [f for f in report.flags if f.severity.value == "RED"]
        yellow_flags = [f for f in report.flags if f.severity.value == "YELLOW"]
        green_flags = [f for f in report.flags if f.severity.value == "GREEN"]

        html_content = template.render(
            report=report,
            red_flags=red_flags,
            yellow_flags=yellow_flags,
            green_flags=green_flags,
        )

        # Load CSS
        css = CSS(filename=str(self.css_path)) if self.css_path.exists() else None

        # Generate PDF
        html = HTML(string=html_content)
        pdf_buffer = BytesIO()

        if css:
            html.write_pdf(pdf_buffer, stylesheets=[css])
        else:
            html.write_pdf(pdf_buffer)

        return pdf_buffer.getvalue()

    def generate_filename(self, report: AnalysisReport) -> str:
        """Generate a filename for the PDF report."""
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in report.character_name)
        date_str = report.created_at.strftime("%Y%m%d")
        return f"sentinel_report_{safe_name}_{date_str}.pdf"
