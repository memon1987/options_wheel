#!/usr/bin/env python3
"""Print a short-lived GCP OAuth2 access token from ADC.

Useful for calling Google REST APIs with curl from environments where the
gcloud CLI cannot be installed (equivalent to `gcloud auth print-access-token`):

    curl -H "Authorization: Bearer $(python3 scripts/gcp_access_token.py)" \
         "https://secretmanager.googleapis.com/v1/projects/PROJECT/secrets"

Requires GOOGLE_APPLICATION_CREDENTIALS to point at a service-account key
(set automatically by .claude/hooks/session-start.sh when GCP_SA_KEY_B64 is
configured on the environment).
"""
import google.auth
import google.auth.transport.requests


def main() -> None:
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    print(creds.token)


if __name__ == "__main__":
    main()
