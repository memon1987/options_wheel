#!/usr/bin/env python3
"""Monitor Cloud Build progress"""

import subprocess
import time
import json

def get_latest_build():
    """Get the latest build status"""
    try:
        result = subprocess.run([
            '/Users/zmemon/google-cloud-sdk/bin/gcloud', 'builds', 'list',
            '--limit=1', '--format=json'
        ], capture_output=True, text=True, check=True)

        builds = json.loads(result.stdout)
        if builds:
            return builds[0]
        return None
    except Exception as e:
        print(f"Error getting build status: {e}")
        return None

def format_duration(duration_str):
    """Format duration string"""
    if not duration_str:
        return "N/A"
    # Remove 's' and convert to minutes if needed
    seconds = float(duration_str.rstrip('s'))
    if seconds > 60:
        return f"{seconds/60:.1f}m"
    return f"{seconds:.0f}s"

def main():
    print("🔍 Monitoring Cloud Build Progress")
    print("=" * 50)

    last_status = None

    while True:
        build = get_latest_build()
        if not build:
            print("No builds found")
            time.sleep(10)
            continue

        build_id = build.get('id', 'Unknown')[:8]
        status = build.get('status', 'Unknown')
        create_time = build.get('createTime', 'Unknown')[:19]
        duration = format_duration(build.get('timing', {}).get('BUILD', {}).get('endTime'))

        # Only print if status changed
        if status != last_status:
            print(f"\n🚀 Build {build_id}")
            print(f"   Status: {status}")
            print(f"   Started: {create_time}")
            if duration != "N/A":
                print(f"   Duration: {duration}")

            if status == 'SUCCESS':
                print("\n🎉 BUILD SUCCESSFUL!")
                print("✅ Your options wheel strategy has been deployed!")
                print("✅ Continuous deployment is now active!")
                break
            elif status == 'FAILURE':
                print("\n❌ BUILD FAILED!")
                print("Check the logs at:")
                print(f"https://console.cloud.google.com/cloud-build/builds/{build.get('id')}?project=gen-lang-client-0607444019")
                break
            elif status in ['WORKING', 'RUNNING']:
                print("   🔨 Building...")

        last_status = status
        time.sleep(15)  # Check every 15 seconds

if __name__ == "__main__":
    main()