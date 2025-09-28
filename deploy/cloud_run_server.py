#!/usr/bin/env python3
"""
Cloud Run compatible web server for Options Wheel Strategy.
Provides HTTP endpoints to trigger and monitor the trading strategy.
"""

import os
import threading
import time
from datetime import datetime
from flask import Flask, jsonify, request
import structlog

# Add src to path
import sys
sys.path.append('/app/src')

from src.utils.config import Config

logger = structlog.get_logger(__name__)

app = Flask(__name__)

# Global state
strategy_status = {
    'status': 'idle',
    'last_run': None,
    'last_scan': None,
    'positions': 0,
    'pnl': 0.0,
    'errors': []
}

strategy_lock = threading.Lock()

@app.route('/')
def health_check():
    """Health check endpoint for Cloud Run."""
    return jsonify({
        'status': 'healthy',
        'service': 'options-wheel-strategy',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/status')
def get_status():
    """Get current strategy status."""
    return jsonify(strategy_status)

@app.route('/scan', methods=['POST'])
def trigger_scan():
    """Trigger a market scan for opportunities."""
    with strategy_lock:
        try:
            logger.info("Triggering market scan")

            # This would normally run the scan logic
            # For now, just update status
            strategy_status['last_scan'] = datetime.now().isoformat()
            strategy_status['status'] = 'scan_completed'

            return jsonify({
                'message': 'Market scan triggered successfully',
                'timestamp': datetime.now().isoformat()
            })

        except Exception as e:
            error_msg = f"Scan failed: {str(e)}"
            logger.error(error_msg)
            strategy_status['errors'].append({
                'timestamp': datetime.now().isoformat(),
                'error': error_msg
            })
            return jsonify({'error': error_msg}), 500

@app.route('/run', methods=['POST'])
def trigger_strategy():
    """Trigger strategy execution."""
    with strategy_lock:
        try:
            logger.info("Triggering strategy execution")

            # This would normally run the strategy
            # For now, just update status
            strategy_status['last_run'] = datetime.now().isoformat()
            strategy_status['status'] = 'execution_completed'

            return jsonify({
                'message': 'Strategy execution triggered successfully',
                'timestamp': datetime.now().isoformat()
            })

        except Exception as e:
            error_msg = f"Strategy execution failed: {str(e)}"
            logger.error(error_msg)
            strategy_status['errors'].append({
                'timestamp': datetime.now().isoformat(),
                'error': error_msg
            })
            return jsonify({'error': error_msg}), 500

@app.route('/config', methods=['GET'])
def get_config():
    """Get current configuration (sanitized)."""
    try:
        config = Config()

        # Return sanitized config (no secrets)
        config_data = {
            'paper_trading': True,  # Always true for cloud deployment
            'stock_symbols': getattr(config, 'stock_symbols', []),
            'max_positions': getattr(config, 'max_total_positions', 10),
            'gap_thresholds': {
                'quality': getattr(config, 'quality_gap_threshold', 2.0),
                'execution': getattr(config, 'execution_gap_threshold', 1.5)
            }
        }

        return jsonify(config_data)

    except Exception as e:
        error_msg = f"Config retrieval failed: {str(e)}"
        logger.error(error_msg)
        return jsonify({'error': error_msg}), 500

@app.route('/health')
def detailed_health():
    """Detailed health check including dependencies."""
    health_data = {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'checks': {}
    }

    # Check configuration
    try:
        config = Config()
        health_data['checks']['config'] = 'ok'
    except Exception as e:
        health_data['checks']['config'] = f'error: {str(e)}'
        health_data['status'] = 'unhealthy'

    # Check environment variables
    required_env_vars = ['ALPACA_API_KEY', 'ALPACA_SECRET_KEY']
    missing_vars = []
    for var in required_env_vars:
        if not os.getenv(var):
            missing_vars.append(var)

    if missing_vars:
        health_data['checks']['environment'] = f'missing: {", ".join(missing_vars)}'
        health_data['status'] = 'unhealthy'
    else:
        health_data['checks']['environment'] = 'ok'

    return jsonify(health_data)

def setup_logging():
    """Configure structured logging."""
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

if __name__ == '__main__':
    setup_logging()

    # Get port from environment (Cloud Run sets this)
    port = int(os.environ.get('PORT', 8080))

    logger.info("Starting Options Wheel Strategy Cloud Run server", port=port)

    # Initialize configuration to verify everything works
    try:
        config = Config()
        logger.info("Configuration loaded successfully")
    except Exception as e:
        logger.error("Failed to load configuration", error=str(e))

    # Run the Flask app
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        threaded=True
    )