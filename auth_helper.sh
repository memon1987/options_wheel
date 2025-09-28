#!/bin/bash
# Helper script for Google Cloud authentication

echo "Starting Google Cloud authentication..."
echo "When prompted, enter 'y' to sign in"
echo "Then paste your verification code when asked"

# Use expect to handle the interactive session
expect << 'EOF'
spawn /Users/zmemon/google-cloud-sdk/bin/gcloud init --console-only
expect "Would you like to sign in (Y/n)?"
send "y\r"
expect "Once finished, enter the verification code provided in your browser:"
send "4/0AVGzR1A6mJyHHqATWjCJ9sGvGkxiWPYfYKshdYUsSBD5V0m9m15z0Dneng6S8HOk1_smfg\r"
expect eof
EOF