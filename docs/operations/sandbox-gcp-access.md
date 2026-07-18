# Recurring GCP access for Claude Code web sandboxes

How to let remote Claude Code sessions talk to our GCP project (Secret Manager,
Cloud Run, BigQuery, GCS) without running commands locally each time.

**Status (2026-07-07):** hook committed but not fully validated in a sandbox —
the pip step needed overlays for debian-managed packages (`packaging`,
`blinker`); if the first session start still fails, check the hook output for
another `Cannot uninstall X, RECORD file not found` and add X to the
`--ignore-installed` list in `.claude/hooks/session-start.sh`.

## How it works

`.claude/hooks/session-start.sh` (registered in `.claude/settings.json`) runs at
the start of every remote session:

1. Installs `requirements-minimal.txt` + the google-cloud/flask/finnhub extras
   actually imported by `src/`.
2. If the environment secret `GCP_SA_KEY_B64` exists, it writes the decoded
   service-account key to `/root/.gcp/sa-key.json` and exports
   `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, `GCP_PROJECT_ID`
   for the session. All `google-cloud-*` client libraries then just work
   (Application Default Credentials). `scripts/gcp_access_token.py` prints a
   bearer token for raw REST calls via curl.
3. If the environment's network policy allows `dl.google.com`, it also installs
   the `gcloud` CLI and activates the same service account. Under the default
   policy that domain is blocked (verified 2026-07-07: `*.googleapis.com` is
   allowed, `dl.google.com` / `packages.cloud.google.com` are denied), so
   sessions run in ADC/client-library mode — sufficient for Secret Manager,
   BigQuery, GCS, and Cloud Run/Scheduler via REST.

## One-time setup (run locally)

```bash
PROJECT=gen-lang-client-0607444019
SA=claude-sandbox@$PROJECT.iam.gserviceaccount.com

# 1. Dedicated service account, least privilege — extend roles as needed
gcloud iam service-accounts create claude-sandbox \
  --project=$PROJECT --display-name="Claude Code sandbox"

for ROLE in roles/secretmanager.admin roles/storage.objectAdmin \
            roles/bigquery.dataEditor roles/bigquery.jobUser \
            roles/run.viewer roles/logging.viewer; do
  gcloud projects add-iam-policy-binding $PROJECT \
    --member="serviceAccount:$SA" --role="$ROLE" --condition=None
done

# 2. Key, base64-encoded for the env var
gcloud iam service-accounts keys create /tmp/claude-sandbox-key.json --iam-account=$SA
base64 -w0 /tmp/claude-sandbox-key.json   # macOS: base64 -i /tmp/claude-sandbox-key.json
rm /tmp/claude-sandbox-key.json           # after pasting
```

3. In [claude.ai/code](https://claude.ai/code) → Settings → Environments → this
   repo's environment → **Environment variables**: add `GCP_SA_KEY_B64` with the
   base64 output as its value (mark as secret).

4. Optional, for the full `gcloud` CLI in sandboxes: add `dl.google.com` to the
   environment's network allowlist.

Every new session in that environment then has GCP access automatically once
the hook is on the default branch (or on whatever branch the session starts
from).

## Security notes

- The SA key is long-lived: scope roles tightly (no `roles/owner` /
  `roles/editor`), rotate periodically
  (`gcloud iam service-accounts keys list/create/delete`), and remember any
  session in this environment — including ones processing untrusted content —
  can use it.
- Deployment permissions (`roles/run.admin`, `roles/cloudbuild.builds.editor`,
  `roles/cloudscheduler.admin`, `roles/iam.serviceAccountUser`) are deliberately
  not in the default list above; add them when we want sandboxes to deploy the
  covered-call service (FC-037 Phase 3) rather than just prepare it.
