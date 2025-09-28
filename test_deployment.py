#!/usr/bin/env python3
"""
Test script for the deployed Options Wheel Strategy.
Tests all endpoints with proper authentication.
"""

import subprocess
import requests
import json
import time
from typing import Dict, Any

SERVICE_URL = "https://options-wheel-strategy-omnlacz6ia-uc.a.run.app"

def get_access_token() -> str:
    """Get Google Cloud access token."""
    try:
        result = subprocess.run([
            '/Users/zmemon/google-cloud-sdk/bin/gcloud', 'auth', 'print-access-token'
        ], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Failed to get access token: {e}")
        return ""

def test_endpoint(endpoint: str, method: str = 'GET', access_token: str = "") -> Dict[str, Any]:
    """Test a specific endpoint."""
    url = f"{SERVICE_URL}{endpoint}"
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    try:
        if method == 'GET':
            response = requests.get(url, headers=headers, timeout=30)
        elif method == 'POST':
            response = requests.post(url, headers=headers, timeout=30)
        else:
            return {'error': f'Unsupported method: {method}'}

        return {
            'status_code': response.status_code,
            'response_time': response.elapsed.total_seconds(),
            'response': response.text[:500] if response.text else None,
            'json': response.json() if response.headers.get('content-type', '').startswith('application/json') else None
        }
    except requests.exceptions.RequestException as e:
        return {'error': str(e)}
    except json.JSONDecodeError:
        return {
            'status_code': response.status_code,
            'response_time': response.elapsed.total_seconds(),
            'response': response.text[:500] if response.text else None
        }

def main():
    """Run comprehensive tests."""
    print("🧪 Testing Options Wheel Strategy Deployment")
    print("=" * 60)

    # Get access token
    access_token = get_access_token()
    if not access_token:
        print("❌ Failed to get access token")
        return

    print("✅ Access token obtained")

    # Test endpoints
    endpoints = [
        ('/', 'GET', 'Health check endpoint'),
        ('/health', 'GET', 'Detailed health check'),
        ('/status', 'GET', 'Strategy status'),
        ('/config', 'GET', 'Configuration'),
        ('/scan', 'POST', 'Market scan trigger'),
        ('/run', 'POST', 'Strategy execution trigger')
    ]

    results = {}

    for endpoint, method, description in endpoints:
        print(f"\n🔍 Testing {method} {endpoint} - {description}")
        result = test_endpoint(endpoint, method, access_token)
        results[endpoint] = result

        if 'error' in result:
            print(f"❌ Error: {result['error']}")
        elif result['status_code'] == 200:
            print(f"✅ Success (Status: {result['status_code']}, Time: {result['response_time']:.2f}s)")
            if result.get('json'):
                print(f"   Response: {json.dumps(result['json'], indent=2)[:200]}...")
        elif result['status_code'] == 401:
            print(f"🔒 Authentication required (Status: {result['status_code']})")
        else:
            print(f"⚠️  Status: {result['status_code']}, Time: {result['response_time']:.2f}s")
            if result.get('response'):
                print(f"   Response: {result['response'][:100]}...")

    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Summary:")

    successful_tests = sum(1 for r in results.values() if r.get('status_code') == 200)
    total_tests = len(results)

    print(f"✅ Successful tests: {successful_tests}/{total_tests}")

    if successful_tests == total_tests:
        print("🎉 All tests passed! Deployment is working correctly.")
    elif successful_tests > 0:
        print("⚠️  Some tests passed. Check authentication and endpoints.")
    else:
        print("❌ No tests passed. Check deployment and authentication.")

    print("\n🔗 Service URL:", SERVICE_URL)
    print("📝 Next steps:")
    print("   - Test scheduled jobs during market hours")
    print("   - Monitor logs for any issues")
    print("   - Configure strategy parameters as needed")

if __name__ == "__main__":
    main()