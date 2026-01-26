"""Email notification service using SMTP."""

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from backend.config import settings
from backend.logging_config import get_logger
from backend.models.report import AnalysisReport

logger = get_logger(__name__)


class EmailService:
    """Service for sending email notifications."""

    def __init__(self) -> None:
        self.enabled = settings.smtp_enabled
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.user = settings.smtp_user
        self.password = settings.smtp_password
        self.from_email = settings.smtp_from_email or settings.smtp_user
        self.from_name = settings.smtp_from_name
        self.use_tls = settings.smtp_use_tls

    def is_configured(self) -> bool:
        """Check if email is properly configured."""
        return (
            self.enabled
            and self.host
            and self.user
            and self.password
            and self.from_email
        )

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> bool:
        """
        Send an email.

        Args:
            to_email: Recipient email address
            subject: Email subject
            html_body: HTML content
            text_body: Plain text content (optional fallback)

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.is_configured():
            logger.warning("Email not configured, skipping send")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{self.from_name} <{self.from_email}>"
            msg["To"] = to_email

            # Add plain text and HTML parts
            if text_body:
                msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            # Connect and send
            context = ssl.create_default_context()

            if self.use_tls:
                with smtplib.SMTP(self.host, self.port) as server:
                    server.starttls(context=context)
                    server.login(self.user, self.password)
                    server.sendmail(self.from_email, to_email, msg.as_string())
            else:
                with smtplib.SMTP_SSL(self.host, self.port, context=context) as server:
                    server.login(self.user, self.password)
                    server.sendmail(self.from_email, to_email, msg.as_string())

            logger.info(f"Email sent to {to_email}: {subject}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    def send_risk_change_alert(
        self,
        to_email: str,
        character_name: str,
        character_id: int,
        old_risk: str,
        new_risk: str,
        report: AnalysisReport,
        base_url: str = "http://localhost:8000",
    ) -> bool:
        """Send alert when a watchlist character's risk level changes."""
        subject = f"[EVE Sentinel] Risk Change Alert: {character_name}"

        # Determine risk color for styling
        risk_colors = {
            "RED": "#dc3545",
            "YELLOW": "#ffc107",
            "GREEN": "#28a745",
        }

        old_color = risk_colors.get(old_risk, "#6c757d")
        new_color = risk_colors.get(new_risk, "#6c757d")

        # Build flag summary
        red_flags = [f for f in report.flags if f.severity.value == "RED"]
        yellow_flags = [f for f in report.flags if f.severity.value == "YELLOW"]

        flags_html = ""
        if red_flags:
            flags_html += "<h4 style='color: #dc3545;'>Red Flags</h4><ul>"
            for flag in red_flags:
                flags_html += f"<li>{flag.reason}</li>"
            flags_html += "</ul>"

        if yellow_flags:
            flags_html += "<h4 style='color: #ffc107;'>Yellow Flags</h4><ul>"
            for flag in yellow_flags:
                flags_html += f"<li>{flag.reason}</li>"
            flags_html += "</ul>"

        report_url = f"{base_url}/reports/{report.report_id}"

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; background: #1a1a2e; color: #e0e0e0; padding: 20px; }}
                .container {{ max-width: 600px; margin: 0 auto; background: #16213e; padding: 20px; border-radius: 8px; }}
                .header {{ text-align: center; border-bottom: 1px solid #0f3460; padding-bottom: 15px; margin-bottom: 20px; }}
                .risk-change {{ display: flex; justify-content: center; align-items: center; gap: 20px; margin: 20px 0; }}
                .risk-badge {{ padding: 10px 20px; border-radius: 4px; font-weight: bold; font-size: 18px; }}
                .arrow {{ font-size: 24px; color: #e94560; }}
                .btn {{ display: inline-block; background: #e94560; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; margin-top: 20px; }}
                h4 {{ margin-bottom: 10px; }}
                ul {{ margin-top: 5px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>Risk Level Changed</h2>
                    <h3>{character_name}</h3>
                    <small>Character ID: {character_id}</small>
                </div>

                <div class="risk-change">
                    <span class="risk-badge" style="background: {old_color};">{old_risk}</span>
                    <span class="arrow">→</span>
                    <span class="risk-badge" style="background: {new_color};">{new_risk}</span>
                </div>

                {flags_html}

                <div style="text-align: center;">
                    <a href="{report_url}" class="btn">View Full Report</a>
                </div>

                <p style="margin-top: 30px; font-size: 12px; color: #888; text-align: center;">
                    This is an automated alert from EVE Sentinel.
                    <br>You're receiving this because this character is on your watchlist.
                </p>
            </div>
        </body>
        </html>
        """

        text_body = f"""
Risk Level Changed: {character_name}

{old_risk} → {new_risk}

View the full report: {report_url}

This is an automated alert from EVE Sentinel.
        """

        return self.send_email(to_email, subject, html_body, text_body)

    def send_new_analysis_alert(
        self,
        to_email: str,
        report: AnalysisReport,
        base_url: str = "http://localhost:8000",
    ) -> bool:
        """Send alert for a new high-risk analysis."""
        risk = report.overall_risk.value
        subject = f"[EVE Sentinel] {risk} Risk Alert: {report.character_name}"

        risk_colors = {
            "RED": "#dc3545",
            "YELLOW": "#ffc107",
            "GREEN": "#28a745",
        }
        risk_color = risk_colors.get(risk, "#6c757d")

        report_url = f"{base_url}/reports/{report.report_id}"

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; background: #1a1a2e; color: #e0e0e0; padding: 20px; }}
                .container {{ max-width: 600px; margin: 0 auto; background: #16213e; padding: 20px; border-radius: 8px; }}
                .header {{ text-align: center; border-bottom: 1px solid #0f3460; padding-bottom: 15px; margin-bottom: 20px; }}
                .risk-badge {{ display: inline-block; padding: 10px 30px; border-radius: 4px; font-weight: bold; font-size: 24px; background: {risk_color}; }}
                .stats {{ display: flex; justify-content: space-around; margin: 20px 0; text-align: center; }}
                .stat {{ padding: 10px; }}
                .stat-value {{ font-size: 24px; font-weight: bold; }}
                .btn {{ display: inline-block; background: #e94560; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; margin-top: 20px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>New Analysis Complete</h2>
                    <h3>{report.character_name}</h3>
                    <div class="risk-badge">{risk}</div>
                </div>

                <div class="stats">
                    <div class="stat">
                        <div class="stat-value" style="color: #dc3545;">{report.red_flag_count}</div>
                        <div>Red Flags</div>
                    </div>
                    <div class="stat">
                        <div class="stat-value" style="color: #ffc107;">{report.yellow_flag_count}</div>
                        <div>Yellow Flags</div>
                    </div>
                    <div class="stat">
                        <div class="stat-value" style="color: #28a745;">{report.green_flag_count}</div>
                        <div>Green Flags</div>
                    </div>
                </div>

                <div style="text-align: center;">
                    <a href="{report_url}" class="btn">View Full Report</a>
                </div>
            </div>
        </body>
        </html>
        """

        text_body = f"""
New Analysis: {report.character_name}

Risk Level: {risk}
Red Flags: {report.red_flag_count}
Yellow Flags: {report.yellow_flag_count}
Green Flags: {report.green_flag_count}

View the full report: {report_url}
        """

        return self.send_email(to_email, subject, html_body, text_body)


# Global instance
email_service = EmailService()
