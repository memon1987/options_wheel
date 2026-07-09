#!/bin/bash
# SessionStart hook for Claude Code on the web.
#
# 1. Installs the Python dependencies needed to run src/, tests, and linters.
# 2. If the environment secret GCP_SA_KEY_B64 is set (base64-encoded GCP
#    service-account JSON key), configures Application Default Credentials so
#    google-cloud-* client libraries and REST calls work for the session.
# 3. If the network policy allows dl.google.com, also installs the gcloud CLI
#    and activates the same service account.
#
# GCP setup is a silent no-op when GCP_SA_KEY_B64 is absent, so this hook is
# safe on environments without the secret. See docs/operations/sandbox-gcp-access.md.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

echo "[session-start] installing python dependencies..."
# The base image ships a debian-managed `packaging` that pip cannot cleanly
# upgrade (no RECORD file); overlay it first so the main install succeeds.
pip install --quiet --disable-pip-version-check --ignore-installed packaging blinker
pip install --quiet --disable-pip-version-check \
  -r "$CLAUDE_PROJECT_DIR/requirements-minimal.txt" \
  google-cloud-bigquery google-cloud-storage google-cloud-secret-manager \
  google-auth flask finnhub-python tenacity pytz

if [ -z "${GCP_SA_KEY_B64:-}" ]; then
  echo "[session-start] GCP_SA_KEY_B64 not set — skipping GCP auth setup"
  exit 0
fi

echo "[session-start] configuring GCP credentials..."
KEY_DIR=/root/.gcp
KEY_FILE="$KEY_DIR/sa-key.json"
mkdir -p "$KEY_DIR"
umask 077
printf '%s' "$GCP_SA_KEY_B64" | base64 -d > "$KEY_FILE"

PROJECT_ID=$(python3 - "$KEY_FILE" <<'PY'
import json, sys
key = json.load(open(sys.argv[1]))
assert key.get("type") == "service_account", "not a service-account key"
print(key["project_id"])
PY
)

{
  echo "export GOOGLE_APPLICATION_CREDENTIALS=$KEY_FILE"
  echo "export GOOGLE_CLOUD_PROJECT=$PROJECT_ID"
  echo "export GCP_PROJECT_ID=$PROJECT_ID"
} >> "$CLAUDE_ENV_FILE"

# Smoke-test the credentials (warn-only: an expired/revoked key should not
# block the session from starting).
if GOOGLE_APPLICATION_CREDENTIALS="$KEY_FILE" python3 - <<'PY'
import google.auth
import google.auth.transport.requests
creds, project = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
creds.refresh(google.auth.transport.requests.Request())
print(f"[session-start] GCP auth OK: {creds.service_account_email} @ {project}")
PY
then :; else
  echo "[session-start] WARNING: GCP token refresh failed — key may be revoked/expired or network-blocked" >&2
fi

# Optional gcloud CLI — only possible if the environment's network policy
# allows dl.google.com (blocked by default; ADC + client libraries above are
# sufficient for most work).
GCLOUD_DIR=/opt/google-cloud-sdk
if [ ! -x "$GCLOUD_DIR/bin/gcloud" ] && curl -fsS -o /dev/null --max-time 8 https://dl.google.com/dl/cloudsdk/channels/rapid/install_google_cloud_sdk.bash 2>/dev/null; then
  echo "[session-start] dl.google.com reachable — installing gcloud CLI..."
  curl -fsS https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-linux-x86_64.tar.gz \
    | tar -xz -C /opt
fi
if [ -x "$GCLOUD_DIR/bin/gcloud" ]; then
  echo "export PATH=\$PATH:$GCLOUD_DIR/bin" >> "$CLAUDE_ENV_FILE"
  "$GCLOUD_DIR/bin/gcloud" auth activate-service-account --key-file="$KEY_FILE" --quiet
  "$GCLOUD_DIR/bin/gcloud" config set project "$PROJECT_ID" --quiet
  echo "[session-start] gcloud CLI ready"
else
  echo "[session-start] gcloud CLI unavailable (network policy blocks dl.google.com); using ADC + python clients"
fi

echo "[session-start] done"
