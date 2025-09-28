#!/usr/bin/env python3
"""Monitoring and alerting system for options wheel strategy."""

import os
import sys
import json
import requests
import smtplib
from datetime import datetime
from email.mime.text import MimeText
from email.mime.multipart import MimeMultipart
from typing import Dict, List, Optional

import structlog

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.utils.config import Config

logger = structlog.get_logger(__name__)


class AlertManager:
    """Manages alerts and notifications for the trading strategy."""

    def __init__(self, config: Config):
        """Initialize alert manager."""
        self.config = config
        self.slack_webhook = os.getenv('SLACK_WEBHOOK_URL')
        self.email_config = self._setup_email_config()

    def _setup_email_config(self) -> Optional[Dict]:
        """Set up email configuration from environment variables."""
        smtp_server = os.getenv('EMAIL_SMTP_SERVER')
        username = os.getenv('EMAIL_USERNAME')
        password = os.getenv('EMAIL_PASSWORD')

        if all([smtp_server, username, password]):
            return {
                'smtp_server': smtp_server,
                'username': username,
                'password': password,
                'port': int(os.getenv('EMAIL_PORT', '587'))
            }
        return None

    def send_slack_alert(self, message: str, level: str = "info") -> bool:
        """Send alert to Slack."""
        if not self.slack_webhook:
            logger.warning("Slack webhook not configured")
            return False

        try:
            color_map = {
                "info": "#36a64f",      # Green
                "warning": "#ff9900",   # Orange
                "error": "#ff0000",     # Red
                "success": "#36a64f"    # Green
            }

            payload = {
                "attachments": [{
                    "color": color_map.get(level, "#36a64f"),
                    "title": f"Options Wheel Strategy - {level.upper()}",
                    "text": message,
                    "timestamp": datetime.now().timestamp()
                }]
            }

            response = requests.post(self.slack_webhook, json=payload, timeout=10)
            response.raise_for_status()

            logger.info("Slack alert sent successfully", level=level)
            return True

        except Exception as e:
            logger.error("Failed to send Slack alert", error=str(e))
            return False

    def send_email_alert(self, subject: str, message: str, recipients: List[str]) -> bool:
        """Send email alert."""
        if not self.email_config:
            logger.warning("Email configuration not available")
            return False

        try:
            msg = MimeMultipart()
            msg['From'] = self.email_config['username']
            msg['To'] = ', '.join(recipients)
            msg['Subject'] = f"Options Wheel Strategy: {subject}"

            # Add message body
            body = f"""
Options Wheel Strategy Alert

Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Message:
{message}

---
This is an automated message from the Options Wheel Trading Strategy.
            """

            msg.attach(MimeText(body, 'plain'))

            # Send email
            server = smtplib.SMTP(self.email_config['smtp_server'], self.email_config['port'])
            server.starttls()
            server.login(self.email_config['username'], self.email_config['password'])
            server.send_message(msg)
            server.quit()

            logger.info("Email alert sent successfully", recipients=recipients)
            return True

        except Exception as e:
            logger.error("Failed to send email alert", error=str(e))
            return False

    def alert_assignment(self, symbol: str, quantity: int, strike: float, option_type: str):
        """Send alert for option assignment."""
        message = f"""
🎯 OPTION ASSIGNMENT ALERT

Symbol: {symbol}
Type: {option_type}
Quantity: {quantity} contracts
Strike: ${strike:.2f}
Status: {'Shares acquired' if option_type == 'PUT' else 'Shares called away'}

Action Required: Review position and plan next steps.
        """

        self.send_slack_alert(message, "warning")

    def alert_profit_target(self, symbol: str, pnl: float, percentage: float):
        """Send alert when profit target is reached."""
        message = f"""
💰 PROFIT TARGET REACHED

Symbol: {symbol}
P&L: ${pnl:.2f}
Return: {percentage:.1%}

Consider closing position to lock in profits.
        """

        self.send_slack_alert(message, "success")

    def alert_loss_threshold(self, symbol: str, pnl: float, percentage: float):
        """Send alert when loss threshold is breached."""
        message = f"""
⚠️ LOSS THRESHOLD ALERT

Symbol: {symbol}
P&L: ${pnl:.2f}
Loss: {percentage:.1%}

Review position for potential closure.
        """

        self.send_slack_alert(message, "error")

    def alert_gap_detection(self, symbol: str, gap_percent: float, action: str):
        """Send alert for gap-related actions."""
        message = f"""
📊 GAP RISK ALERT

Symbol: {symbol}
Gap: {gap_percent:.2f}%
Action: {action}

Gap threshold exceeded - trade execution blocked.
        """

        self.send_slack_alert(message, "warning")

    def daily_summary(self, portfolio_value: float, daily_pnl: float, active_positions: int):
        """Send daily portfolio summary."""
        message = f"""
📈 DAILY SUMMARY

Portfolio Value: ${portfolio_value:,.2f}
Daily P&L: ${daily_pnl:,.2f}
Active Positions: {active_positions}

Trading session complete.
        """

        self.send_slack_alert(message, "info")


class HealthChecker:
    """Health monitoring for the trading system."""

    def __init__(self, config: Config):
        """Initialize health checker."""
        self.config = config
        self.alert_manager = AlertManager(config)

    def check_api_connectivity(self) -> bool:
        """Check Alpaca API connectivity."""
        try:
            from src.api.alpaca_client import AlpacaClient
            client = AlpacaClient(self.config)

            # Test API connection
            account = client.get_account()
            return account is not None

        except Exception as e:
            logger.error("API connectivity check failed", error=str(e))
            self.alert_manager.send_slack_alert(
                f"API Connectivity Failed: {str(e)}", "error"
            )
            return False

    def check_market_data(self) -> bool:
        """Check market data availability."""
        try:
            from src.api.alpaca_client import AlpacaClient
            client = AlpacaClient(self.config)

            # Test market data
            quote = client.get_stock_quote('AAPL')
            return quote is not None

        except Exception as e:
            logger.error("Market data check failed", error=str(e))
            self.alert_manager.send_slack_alert(
                f"Market Data Failed: {str(e)}", "error"
            )
            return False

    def check_configuration(self) -> bool:
        """Check configuration validity."""
        try:
            # Verify all required config parameters
            required_attrs = [
                'alpaca_api_key', 'alpaca_secret_key',
                'stock_symbols', 'execution_gap_threshold'
            ]

            for attr in required_attrs:
                if not hasattr(self.config, attr):
                    raise ValueError(f"Missing configuration: {attr}")

            return True

        except Exception as e:
            logger.error("Configuration check failed", error=str(e))
            self.alert_manager.send_slack_alert(
                f"Configuration Error: {str(e)}", "error"
            )
            return False

    def run_health_checks(self) -> Dict[str, bool]:
        """Run all health checks."""
        logger.info("Running health checks")

        results = {
            'configuration': self.check_configuration(),
            'api_connectivity': self.check_api_connectivity(),
            'market_data': self.check_market_data()
        }

        # Send summary
        failed_checks = [check for check, passed in results.items() if not passed]

        if failed_checks:
            message = f"Health Check Failed: {', '.join(failed_checks)}"
            self.alert_manager.send_slack_alert(message, "error")
        else:
            logger.info("All health checks passed")

        return results


class MetricsCollector:
    """Collects and exports metrics for monitoring."""

    def __init__(self):
        """Initialize metrics collector."""
        self.metrics = {}

    def record_trade(self, symbol: str, action: str, quantity: int, premium: float):
        """Record trade metrics."""
        key = f"trades_{action.lower()}"
        if key not in self.metrics:
            self.metrics[key] = 0
        self.metrics[key] += 1

        # Record volume
        volume_key = f"volume_{action.lower()}"
        if volume_key not in self.metrics:
            self.metrics[volume_key] = 0
        self.metrics[volume_key] += quantity

        # Record premium
        premium_key = f"premium_{action.lower()}"
        if premium_key not in self.metrics:
            self.metrics[premium_key] = 0
        self.metrics[premium_key] += premium

    def record_gap_event(self, symbol: str, gap_percent: float, action: str):
        """Record gap-related events."""
        self.metrics['gap_events'] = self.metrics.get('gap_events', 0) + 1

        if action == 'blocked':
            self.metrics['trades_blocked_gap'] = self.metrics.get('trades_blocked_gap', 0) + 1

    def export_prometheus_metrics(self) -> str:
        """Export metrics in Prometheus format."""
        lines = [
            "# HELP options_wheel_trades_total Total number of trades executed",
            "# TYPE options_wheel_trades_total counter"
        ]

        for metric, value in self.metrics.items():
            lines.append(f"options_wheel_{metric} {value}")

        return '\n'.join(lines)

    def get_metrics_summary(self) -> Dict:
        """Get summary of collected metrics."""
        return self.metrics.copy()


def main():
    """Main monitoring script entry point."""
    config = Config()
    health_checker = HealthChecker(config)

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "health":
            results = health_checker.run_health_checks()
            print(json.dumps(results, indent=2))
            exit(0 if all(results.values()) else 1)

        elif command == "test-alert":
            alert_manager = AlertManager(config)
            alert_manager.send_slack_alert("Test alert from monitoring system", "info")

    else:
        print("Usage: python monitoring.py [health|test-alert]")


if __name__ == "__main__":
    main()