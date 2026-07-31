# eidolon-sdk

Shared Python contracts and infrastructure for the Eidolon project family.

The package is organized by responsibility:

- `eidolon_sdk.core`: transport, storage, wire-format, and async infrastructure.
- `eidolon_sdk.biz`: shared Eidolon business contracts used by multiple projects.
- `eidolon_sdk.integrations`: third-party integration helpers.
- `eidolon_sdk.adapters`: storage adapters for SDK-owned contracts.

The memory service's wire contracts used to live here as `eidolon_sdk.memory`.
They now ship as `eidolon-memory-contracts`, alongside the service that owns
them, so that service can be built and released without the OS SDK. Clients of
memory depend on that package directly.
