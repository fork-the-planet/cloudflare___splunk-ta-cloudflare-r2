# Contributing

Thanks for your interest in contributing to the Cloudflare R2 Log Ingestion
Add-on for Splunk.

## Getting started

1. Fork the repository
2. Follow the local development setup in [DEVELOPMENT.md](DEVELOPMENT.md)
3. Make your changes on a feature branch
4. Run AppInspect to verify no regressions: `splunk-appinspect inspect TA_cloudflare_r2-*.tar.gz --mode precert`
5. Open a pull request with a clear description of the change and why

## What we're looking for

The highest-value contributions right now (see [DEVELOPMENT.md](DEVELOPMENT.md)
for technical details):

- **Splunk Cloud compatibility** testing and fixes
- **Test coverage** - the R2 client's SigV4 signer has an offline known-answer
  test (`tests/test_sigv4.py`); checkpointing logic in
  `cloudflare_r2_helper.py` (dedupe, lookback pruning) still has no automated
  unit tests

## Code style

- Python 3.9+ (minimum supported Splunk is 9.4) - f-strings and other 3.9
  features are fine
- No new external dependencies without a strong reason - keep the vendored
  library footprint small
- Follow the existing pattern: transport only, no field extraction or
  dataset-specific logic in the modular input itself

## Reporting bugs

Open a GitHub issue with:
- Splunk version
- Python version (check `$SPLUNK_HOME/bin/python3 --version`)
- The relevant lines from `$SPLUNK_HOME/var/log/splunk/ta_cloudflare_r2_<input_name>.log`
  (this add-on logs per-input via solnlib, not to `splunkd.log`)
- Steps to reproduce
