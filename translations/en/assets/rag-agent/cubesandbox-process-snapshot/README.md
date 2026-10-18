# Process-memory snapshot acceptance assets

Tested on 2026-10-18 with CubeSandbox v0.7.3 and Python SDK 0.7.3.

- `process_snapshot_probe.py`: exact runner used for the formal test.
- `lab-results.json`, `production-results.json`: redacted actual output, three rounds each.
- `report.html`: Light report derived from those outputs, not a product UI.
- `01-results-light.png`, `02-memory-trace-light.png`: browser captures of the report at 1200x675.

The worker never reloads application progress. Snapshots are taken at a cooperative in-memory hold barrier; HTTP service stays live. Each round kills the guest worker before rollback, then deletes the source VM before creating a new VM from the snapshot. This is not a host-failure, cross-node, GPU, mounted-volume, or native Agent-tool acceptance test.

All test-created sandboxes and snapshots were removed; pre-existing resources were preserved. No credentials, private endpoints, infrastructure object IDs or internal cluster names are included. Identity tags are one-way hashes of randomly generated test-worker identities, not access tokens.
