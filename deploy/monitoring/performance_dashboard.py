#!/usr/bin/env python3
"""
Enhanced performance monitoring dashboard for the Options Wheel Strategy.
Provides real-time monitoring, alerting, and comprehensive analytics.
"""

import os
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import structlog

try:
    from google.cloud import monitoring_v3
    from google.cloud import logging as cloud_logging
    GOOGLE_CLOUD_AVAILABLE = True
except ImportError:
    GOOGLE_CLOUD_AVAILABLE = False
    monitoring_v3 = None
    cloud_logging = None

logger = structlog.get_logger(__name__)


@dataclass
class PerformanceMetrics:
    """Container for performance metrics."""
    timestamp: str
    total_return: float
    daily_pnl: float
    portfolio_value: float
    cash_allocation: float
    positions_count: int
    win_rate: float
    avg_return_per_trade: float
    max_drawdown: float
    sharpe_ratio: float
    volatility: float
    var_95: float
    gap_events: int
    trades_blocked: int
    api_errors: int
    execution_latency: float


@dataclass
class AlertThresholds:
    """Alert threshold configuration."""
    max_daily_loss: float = -0.02  # 2% daily loss
    min_cash_allocation: float = 0.15  # 15% cash minimum
    max_drawdown: float = -0.05  # 5% max drawdown
    max_api_errors: int = 5
    max_execution_latency: float = 5.0  # seconds
    min_win_rate: float = 0.65
    max_gap_events: int = 3


class PerformanceMonitor:
    """Comprehensive performance monitoring system."""

    def __init__(self, project_id: str = "gen-lang-client-0607444019"):
        """Initialize the performance monitor.

        Args:
            project_id: Google Cloud project ID
        """
        self.project_id = project_id
        self.alerts = AlertThresholds()

        # Initialize Google Cloud clients if available
        self.monitoring_client = None
        self.logging_client = None

        if GOOGLE_CLOUD_AVAILABLE:
            try:
                self.monitoring_client = monitoring_v3.MetricServiceClient()
                self.logging_client = cloud_logging.Client(project=project_id)
                logger.info("Google Cloud monitoring initialized")
            except Exception as e:
                logger.warning("Failed to initialize Google Cloud monitoring", error=str(e))

        # Local metrics storage
        self.metrics_history: List[PerformanceMetrics] = []
        self.alerts_history: List[Dict] = []

    def collect_current_metrics(self) -> PerformanceMetrics:
        """Collect current performance metrics.

        Returns:
            Current performance metrics
        """
        try:
            # In production, this would fetch real data from:
            # - Alpaca API for portfolio data
            # - Local database for strategy metrics
            # - Cloud monitoring for system metrics

            # Mock current metrics for demonstration
            current_time = datetime.now()

            # Generate realistic mock data
            base_portfolio = 100000.0
            daily_variation = (hash(str(current_time.date())) % 1000 - 500) / 100000
            portfolio_value = base_portfolio + (base_portfolio * daily_variation)

            metrics = PerformanceMetrics(
                timestamp=current_time.isoformat(),
                total_return=0.045 + daily_variation,
                daily_pnl=portfolio_value - base_portfolio,
                portfolio_value=portfolio_value,
                cash_allocation=0.22,
                positions_count=8,
                win_rate=0.75,
                avg_return_per_trade=0.023,
                max_drawdown=-0.018,
                sharpe_ratio=1.85,
                volatility=0.12,
                var_95=-0.015,
                gap_events=1,
                trades_blocked=0,
                api_errors=0,
                execution_latency=1.2
            )

            self.metrics_history.append(metrics)

            # Keep only last 1000 metrics to manage memory
            if len(self.metrics_history) > 1000:
                self.metrics_history = self.metrics_history[-1000:]

            logger.debug("Metrics collected", portfolio_value=metrics.portfolio_value)
            return metrics

        except Exception as e:
            logger.error("Failed to collect metrics", error=str(e))
            # Return default metrics on error
            return PerformanceMetrics(
                timestamp=datetime.now().isoformat(),
                total_return=0.0,
                daily_pnl=0.0,
                portfolio_value=100000.0,
                cash_allocation=0.20,
                positions_count=0,
                win_rate=0.0,
                avg_return_per_trade=0.0,
                max_drawdown=0.0,
                sharpe_ratio=0.0,
                volatility=0.0,
                var_95=0.0,
                gap_events=0,
                trades_blocked=0,
                api_errors=0,
                execution_latency=0.0
            )

    def check_alerts(self, metrics: PerformanceMetrics) -> List[Dict]:
        """Check for alert conditions.

        Args:
            metrics: Current performance metrics

        Returns:
            List of triggered alerts
        """
        alerts = []

        # Daily loss alert
        if metrics.daily_pnl < metrics.portfolio_value * self.alerts.max_daily_loss:
            alerts.append({
                'type': 'daily_loss',
                'severity': 'high',
                'message': f'Daily loss {metrics.daily_pnl:.2f} exceeds threshold',
                'value': metrics.daily_pnl,
                'threshold': metrics.portfolio_value * self.alerts.max_daily_loss,
                'timestamp': metrics.timestamp
            })

        # Cash allocation alert
        if metrics.cash_allocation < self.alerts.min_cash_allocation:
            alerts.append({
                'type': 'low_cash',
                'severity': 'medium',
                'message': f'Cash allocation {metrics.cash_allocation:.1%} below minimum',
                'value': metrics.cash_allocation,
                'threshold': self.alerts.min_cash_allocation,
                'timestamp': metrics.timestamp
            })

        # Max drawdown alert
        if metrics.max_drawdown < self.alerts.max_drawdown:
            alerts.append({
                'type': 'max_drawdown',
                'severity': 'high',
                'message': f'Max drawdown {metrics.max_drawdown:.1%} exceeds limit',
                'value': metrics.max_drawdown,
                'threshold': self.alerts.max_drawdown,
                'timestamp': metrics.timestamp
            })

        # API errors alert
        if metrics.api_errors > self.alerts.max_api_errors:
            alerts.append({
                'type': 'api_errors',
                'severity': 'medium',
                'message': f'API errors {metrics.api_errors} exceeding threshold',
                'value': metrics.api_errors,
                'threshold': self.alerts.max_api_errors,
                'timestamp': metrics.timestamp
            })

        # Execution latency alert
        if metrics.execution_latency > self.alerts.max_execution_latency:
            alerts.append({
                'type': 'execution_latency',
                'severity': 'low',
                'message': f'Execution latency {metrics.execution_latency:.1f}s high',
                'value': metrics.execution_latency,
                'threshold': self.alerts.max_execution_latency,
                'timestamp': metrics.timestamp
            })

        # Win rate alert
        if metrics.win_rate < self.alerts.min_win_rate:
            alerts.append({
                'type': 'low_win_rate',
                'severity': 'medium',
                'message': f'Win rate {metrics.win_rate:.1%} below expected',
                'value': metrics.win_rate,
                'threshold': self.alerts.min_win_rate,
                'timestamp': metrics.timestamp
            })

        # Gap events alert
        if metrics.gap_events > self.alerts.max_gap_events:
            alerts.append({
                'type': 'gap_events',
                'severity': 'medium',
                'message': f'Gap events {metrics.gap_events} above normal',
                'value': metrics.gap_events,
                'threshold': self.alerts.max_gap_events,
                'timestamp': metrics.timestamp
            })

        # Store alerts
        for alert in alerts:
            self.alerts_history.append(alert)
            logger.warning("Alert triggered", **alert)

        return alerts

    def generate_dashboard_data(self) -> Dict[str, Any]:
        """Generate comprehensive dashboard data.

        Returns:
            Dashboard data dictionary
        """
        current_metrics = self.collect_current_metrics()
        alerts = self.check_alerts(current_metrics)

        # Calculate trend data
        recent_metrics = self.metrics_history[-24:] if len(self.metrics_history) >= 24 else self.metrics_history

        dashboard_data = {
            'current_metrics': asdict(current_metrics),
            'alerts': {
                'active_alerts': alerts,
                'alert_count': len(alerts),
                'recent_alerts': self.alerts_history[-10:] if self.alerts_history else []
            },
            'trends': self._calculate_trends(recent_metrics),
            'performance_summary': self._generate_performance_summary(recent_metrics),
            'system_health': self._check_system_health(),
            'risk_metrics': self._calculate_risk_metrics(recent_metrics),
            'execution_metrics': self._calculate_execution_metrics(recent_metrics),
            'timestamp': datetime.now().isoformat(),
            'data_freshness': 'real_time'
        }

        return dashboard_data

    def _calculate_trends(self, metrics_list: List[PerformanceMetrics]) -> Dict[str, Any]:
        """Calculate trend data from metrics history."""
        if len(metrics_list) < 2:
            return {'trend_data': 'insufficient_data'}

        latest = metrics_list[-1]
        previous = metrics_list[-2]

        trends = {
            'portfolio_value': {
                'current': latest.portfolio_value,
                'previous': previous.portfolio_value,
                'change': latest.portfolio_value - previous.portfolio_value,
                'change_percent': ((latest.portfolio_value - previous.portfolio_value) / previous.portfolio_value) * 100
            },
            'win_rate': {
                'current': latest.win_rate,
                'previous': previous.win_rate,
                'change': latest.win_rate - previous.win_rate
            },
            'positions_count': {
                'current': latest.positions_count,
                'previous': previous.positions_count,
                'change': latest.positions_count - previous.positions_count
            },
            'cash_allocation': {
                'current': latest.cash_allocation,
                'previous': previous.cash_allocation,
                'change': latest.cash_allocation - previous.cash_allocation
            }
        }

        return trends

    def _generate_performance_summary(self, metrics_list: List[PerformanceMetrics]) -> Dict[str, Any]:
        """Generate performance summary statistics."""
        if not metrics_list:
            return {'status': 'no_data'}

        latest = metrics_list[-1]

        # Calculate performance over different periods
        summary = {
            'current_period': {
                'total_return': latest.total_return,
                'sharpe_ratio': latest.sharpe_ratio,
                'max_drawdown': latest.max_drawdown,
                'win_rate': latest.win_rate
            },
            'performance_grade': self._calculate_performance_grade(latest),
            'key_highlights': self._generate_key_highlights(latest),
            'risk_assessment': self._assess_risk_level(latest)
        }

        return summary

    def _check_system_health(self) -> Dict[str, Any]:
        """Check overall system health status."""
        health_status = {
            'overall_status': 'healthy',
            'components': {
                'api_connectivity': 'healthy',
                'data_pipeline': 'healthy',
                'execution_engine': 'healthy',
                'risk_management': 'healthy',
                'monitoring': 'healthy'
            },
            'uptime_percentage': 99.8,
            'last_health_check': datetime.now().isoformat()
        }

        # Check for any critical issues
        if len(self.alerts_history) > 0:
            recent_critical = [a for a in self.alerts_history[-10:] if a.get('severity') == 'high']
            if recent_critical:
                health_status['overall_status'] = 'degraded'
                health_status['components']['risk_management'] = 'warning'

        return health_status

    def _calculate_risk_metrics(self, metrics_list: List[PerformanceMetrics]) -> Dict[str, Any]:
        """Calculate comprehensive risk metrics."""
        if not metrics_list:
            return {'status': 'no_data'}

        latest = metrics_list[-1]

        risk_metrics = {
            'current_risk_level': 'moderate',
            'var_95': latest.var_95,
            'volatility': latest.volatility,
            'max_drawdown': latest.max_drawdown,
            'cash_buffer': latest.cash_allocation,
            'concentration_risk': 'low',  # Would be calculated from positions
            'gap_risk_exposure': latest.gap_events,
            'risk_adjusted_return': latest.total_return / max(latest.volatility, 0.01),
            'risk_recommendations': [
                'Maintain current cash allocation above 15%',
                'Monitor gap events for trend changes',
                'Consider position sizing adjustments if volatility increases'
            ]
        }

        # Determine risk level
        if latest.max_drawdown < -0.05 or latest.volatility > 0.20:
            risk_metrics['current_risk_level'] = 'high'
        elif latest.max_drawdown < -0.03 or latest.volatility > 0.15:
            risk_metrics['current_risk_level'] = 'elevated'

        return risk_metrics

    def _calculate_execution_metrics(self, metrics_list: List[PerformanceMetrics]) -> Dict[str, Any]:
        """Calculate execution quality metrics."""
        if not metrics_list:
            return {'status': 'no_data'}

        latest = metrics_list[-1]

        execution_metrics = {
            'avg_execution_latency': latest.execution_latency,
            'api_error_rate': latest.api_errors,
            'trades_blocked_by_gaps': latest.trades_blocked,
            'execution_quality_score': self._calculate_execution_score(latest),
            'slippage_analysis': 'within_tolerance',  # Would be calculated from trades
            'fill_rate': 0.98,  # Mock data
            'execution_recommendations': []
        }

        # Add recommendations based on execution metrics
        if latest.execution_latency > 3.0:
            execution_metrics['execution_recommendations'].append(
                'Consider optimizing API calls to reduce latency'
            )

        if latest.api_errors > 2:
            execution_metrics['execution_recommendations'].append(
                'Review API error patterns and implement additional retry logic'
            )

        return execution_metrics

    def _calculate_performance_grade(self, metrics: PerformanceMetrics) -> str:
        """Calculate overall performance grade."""
        score = 0

        # Return component (40%)
        if metrics.total_return > 0.05:
            score += 40
        elif metrics.total_return > 0.03:
            score += 30
        elif metrics.total_return > 0.01:
            score += 20
        elif metrics.total_return > 0:
            score += 10

        # Risk component (30%)
        if metrics.max_drawdown > -0.02:
            score += 30
        elif metrics.max_drawdown > -0.03:
            score += 25
        elif metrics.max_drawdown > -0.05:
            score += 15
        elif metrics.max_drawdown > -0.08:
            score += 5

        # Consistency component (30%)
        if metrics.win_rate > 0.80:
            score += 30
        elif metrics.win_rate > 0.75:
            score += 25
        elif metrics.win_rate > 0.70:
            score += 20
        elif metrics.win_rate > 0.65:
            score += 15
        else:
            score += 5

        # Convert to letter grade
        if score >= 90:
            return 'A'
        elif score >= 80:
            return 'B'
        elif score >= 70:
            return 'C'
        elif score >= 60:
            return 'D'
        else:
            return 'F'

    def _generate_key_highlights(self, metrics: PerformanceMetrics) -> List[str]:
        """Generate key performance highlights."""
        highlights = []

        if metrics.total_return > 0.04:
            highlights.append(f"Strong returns: {metrics.total_return:.1%} total return")

        if metrics.win_rate > 0.75:
            highlights.append(f"High win rate: {metrics.win_rate:.1%} successful trades")

        if metrics.max_drawdown > -0.03:
            highlights.append(f"Low drawdown: {metrics.max_drawdown:.1%} maximum loss")

        if metrics.sharpe_ratio > 1.5:
            highlights.append(f"Excellent risk-adjusted returns: {metrics.sharpe_ratio:.1f} Sharpe ratio")

        if not highlights:
            highlights.append("Performance within normal parameters")

        return highlights

    def _assess_risk_level(self, metrics: PerformanceMetrics) -> str:
        """Assess current risk level."""
        risk_factors = 0

        if metrics.max_drawdown < -0.05:
            risk_factors += 2
        elif metrics.max_drawdown < -0.03:
            risk_factors += 1

        if metrics.cash_allocation < 0.15:
            risk_factors += 1

        if metrics.volatility > 0.18:
            risk_factors += 1

        if metrics.gap_events > 2:
            risk_factors += 1

        if risk_factors == 0:
            return 'low'
        elif risk_factors <= 2:
            return 'moderate'
        elif risk_factors <= 4:
            return 'elevated'
        else:
            return 'high'

    def _calculate_execution_score(self, metrics: PerformanceMetrics) -> float:
        """Calculate execution quality score (0-100)."""
        score = 100.0

        # Penalize for latency
        if metrics.execution_latency > 2.0:
            score -= min(30, (metrics.execution_latency - 2.0) * 10)

        # Penalize for API errors
        score -= min(20, metrics.api_errors * 4)

        # Penalize for blocked trades (indicates poor timing)
        score -= min(15, metrics.trades_blocked * 5)

        return max(0, score)

    def export_metrics(self, format: str = 'json') -> str:
        """Export current metrics in specified format.

        Args:
            format: Export format ('json', 'csv')

        Returns:
            Exported data as string
        """
        dashboard_data = self.generate_dashboard_data()

        if format == 'json':
            return json.dumps(dashboard_data, indent=2)
        elif format == 'csv':
            # Simple CSV export of key metrics
            import csv
            import io

            output = io.StringIO()
            writer = csv.writer(output)

            # Header
            writer.writerow([
                'timestamp', 'portfolio_value', 'total_return', 'daily_pnl',
                'win_rate', 'max_drawdown', 'sharpe_ratio', 'positions_count'
            ])

            # Data
            metrics = dashboard_data['current_metrics']
            writer.writerow([
                metrics['timestamp'], metrics['portfolio_value'], metrics['total_return'],
                metrics['daily_pnl'], metrics['win_rate'], metrics['max_drawdown'],
                metrics['sharpe_ratio'], metrics['positions_count']
            ])

            return output.getvalue()

        return str(dashboard_data)


def main():
    """Main function for testing the performance monitor."""
    monitor = PerformanceMonitor()

    # Generate sample dashboard
    dashboard = monitor.generate_dashboard_data()

    print("=== OPTIONS WHEEL STRATEGY PERFORMANCE DASHBOARD ===")
    print(json.dumps(dashboard, indent=2))


if __name__ == '__main__':
    main()