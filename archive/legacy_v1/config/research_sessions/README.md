# Frozen v1 research session configurations

Unreferenced historical v1 session YAMLs have been moved here with Git renames, byte-for-byte unchanged. The active FOMC proxy session YAML remains in `config/research_sessions/` because its regression test reads that path. They remain available for forensic reproduction by passing their archived paths explicitly to legacy compatibility tools. For new autonomous research, use `scripts/quant.py ingest` and `scripts/quant.py run` instead. Do not rewrite frozen session identities, and do not silently substitute the new candidate schema for these historical contracts.

Consult `docs/architecture/dual_mode_20261015/archive_inventory.md` for original paths and SHA-256 evidence.
