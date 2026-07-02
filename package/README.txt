Cloudflare R2 Log Ingestion Add-on for Splunk (TA_cloudflare_r2)

Ingests Cloudflare Logpush log files from a Cloudflare R2 bucket via the
S3-compatible API using a pure standard-library client (SigV4, path-style,
no AWS STS dependency, no boto3). Emits one Splunk event per NDJSON line.

Requirements:
- Splunk Enterprise 9.4 or higher.
- Runs on a heavy forwarder, IDM, standalone, or search head (requires KV Store;
  NOT a Universal Forwarder).

Configuration:
1. Configuration > Cloudflare R2 Account: add an account (Account ID, R2 Access
   Key ID, R2 Secret Access Key). The secret is stored encrypted in
   storage/passwords.
2. Inputs > Create New Input: select the account, set the bucket name, optional
   key prefix, interval, index, and sourcetype.

Release notes: 1.0.0 - Initial UCC-based release.
