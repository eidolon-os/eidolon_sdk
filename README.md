# eidolon-sdk

Shared Python contracts and infrastructure for the Eidolon project family.

The package keeps domain contracts separate from storage adapters:

- `eidolon_sdk.registry`: registry domain models and store protocols.
- `eidolon_sdk.db`: SQL/SQLite infrastructure helpers.
- `eidolon_sdk.kv`: key-value infrastructure protocols.
- `eidolon_sdk.adapters.registry_sqlite`: SQLite implementation of registry stores.

