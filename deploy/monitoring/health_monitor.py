#!/usr/bin/env python3
"""
Health monitoring script for Options Wheel Strategy.
Can be run locally or scheduled to check strategy health.
"""

import os
import sys
import json
import requests
import subprocess
from datetime import datetime
from typing import Dict, Any

def get_access_token() -> str:
    """Get Google Cloud access token for authentication."""
    try:
        result = subprocess.run([
            '/Users/zmemon/google-cloud-sdk/bin/gcloud', 'auth', 'print-access-token'
        ], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Failed to get access token: {e}")
        return ""

def check_service_health(service_url: str, access_token: str) -> Dict[str, Any]:
    """Check the health of the Cloud Run service."""
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    try:
        # Check main health endpoint
        response = requests.get(f"{service_url}/health", headers=headers, timeout=30)
        if response.status_code == 200:
            health_data = response.json()
            return {
                'status': 'healthy',
                'response_time': response.elapsed.total_seconds(),
                'health_data': health_data
            }
        else:
            return {
                'status': 'unhealthy',
                'status_code': response.status_code,
                'response': response.text
            }
    except requests.exceptions.RequestException as e:
        return {
            'status': 'error',
            'error': str(e)
        }

def check_strategy_status(service_url: str, access_token: str) -> Dict[str, Any]:
    """Check the current strategy status."""
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    try:
        response = requests.get(f"{service_url}/status", headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            return {
                'error': f"Status check failed: {response.status_code}",
                'response': response.text
            }
    except requests.exceptions.RequestException as e:
        return {
            'error': f"Request failed: {str(e)}"
        }

def check_cloud_run_service() -> Dict[str, Any]:
    """Check Cloud Run service status using gcloud."""
    try:
        result = subprocess.run([
            '/Users/zmemon/google-cloud-sdk/bin/gcloud', 'run', 'services', 'describe',
            'options-wheel-strategy', '--region=us-central1', '--format=json'
        ], capture_output=True, text=True, check=True)

        service_info = json.loads(result.stdout)
        return {
            'service_name': service_info.get('metadata', {}).get('name'),
            'status': service_info.get('status', {}).get('conditions', [{}])[0].get('status'),
            'url': service_info.get('status', {}).get('url'),
            'ready': service_info.get('status', {}).get('conditions', [{}])[0].get('type') == 'Ready'
        }
    except subprocess.CalledProcessError as e:
        return {
            'error': f"Failed to get service info: {e}",
            'stderr': e.stderr
        }

def check_scheduler_jobs() -> Dict[str, Any]:
    """Check the status of scheduled jobs."""
    try:
        result = subprocess.run([
            '/Users/zmemon/google-cloud-sdk/bin/gcloud', 'scheduler', 'jobs', 'list',
            '--location=us-central1', '--format=json'
        ], capture_output=True, text=True, check=True)

        jobs = json.loads(result.stdout)
        job_status = {}

        for job in jobs:
            name = job.get('name', '').split('/')[-1]
            job_status[name] = {
                'state': job.get('state'),
                'schedule': job.get('schedule'),
                'last_attempt_time': job.get('status', {}).get('lastAttemptTime'),
                'description': job.get('description')
            }

        return job_status
    except subprocess.CalledProcessError as e:
        return {
            'error': f"Failed to get scheduler jobs: {e}",
            'stderr': e.stderr
        }

def main():
    """Main monitoring function."""
    print(f"🔍 Options Wheel Strategy Health Check - {datetime.now().isoformat()}")
    print("=" * 70)

    service_url = "https://options-wheel-strategy-omnlacz6ia-uc.a.run.app"
    access_token = get_access_token()

    if not access_token:
        print("❌ Failed to get access token. Please authenticate with gcloud.")
        sys.exit(1)

    # Check Cloud Run service
    print("\n📊 Cloud Run Service Status:")
    service_info = check_cloud_run_service()
    if 'error' in service_info:
        print(f"❌ Service check failed: {service_info['error']}")
    else:
        status_icon = "✅" if service_info.get('ready') else "⚠️"
        print(f"{status_icon} Service: {service_info.get('service_name')}")
        print(f"   Status: {service_info.get('status')}")
        print(f"   URL: {service_info.get('url')}")
        print(f"   Ready: {service_info.get('ready')}")

    # Check service health
    print("\n🏥 Application Health:")
    health_check = check_service_health(service_url, access_token)
    if health_check['status'] == 'healthy':
        print(f"✅ Service is healthy (response time: {health_check['response_time']:.2f}s)")

        health_data = health_check.get('health_data', {})
        checks = health_data.get('checks', {})
        for check_name, check_result in checks.items():
            icon = "✅" if check_result == 'ok' else "❌"
            print(f"   {icon} {check_name}: {check_result}")
    else:
        print(f"❌ Service health check failed: {health_check}")

    # Check strategy status
    print("\n📈 Strategy Status:")
    strategy_status = check_strategy_status(service_url, access_token)
    if 'error' not in strategy_status:
        print(f"📊 Status: {strategy_status.get('status', 'unknown')}")
        print(f"🕐 Last Run: {strategy_status.get('last_run', 'never')}")
        print(f"🔍 Last Scan: {strategy_status.get('last_scan', 'never')}")
        print(f"📋 Positions: {strategy_status.get('positions', 0)}")
        print(f"💰 P&L: ${strategy_status.get('pnl', 0.0):.2f}")

        errors = strategy_status.get('errors', [])
        if errors:
            print(f"\n⚠️ Recent Errors ({len(errors)}):")
            for error in errors[-3:]:  # Show last 3 errors
                print(f"   {error.get('timestamp')}: {error.get('error')}")
    else:
        print(f"❌ Strategy status check failed: {strategy_status['error']}")

    # Check scheduled jobs
    print("\n⏰ Scheduled Jobs:")
    scheduler_status = check_scheduler_jobs()
    if 'error' not in scheduler_status:
        for job_name, job_info in scheduler_status.items():
            state_icon = "✅" if job_info['state'] == 'ENABLED' else "❌"
            print(f"{state_icon} {job_name}")
            print(f"   Schedule: {job_info['schedule']}")
            print(f"   State: {job_info['state']}")
            if job_info.get('last_attempt_time'):
                print(f"   Last Run: {job_info['last_attempt_time']}")
    else:
        print(f"❌ Scheduler check failed: {scheduler_status['error']}")

    print("\n" + "=" * 70)
    print("✅ Health check completed")

if __name__ == "__main__":
    main()