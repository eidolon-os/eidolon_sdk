# eidolon-sdk

Shared Python contracts and infrastructure for the Eidolon project family.

The package is organized by responsibility:

- `eidolon_sdk.core`: transport, storage, wire-format, and async infrastructure.
- `eidolon_sdk.biz`: shared Eidolon business contracts used by multiple projects.
- `eidolon_sdk.integrations`: third-party integration helpers.
- `eidolon_sdk.adapters`: storage adapters for SDK-owned contracts.
- `eidolon_sdk.memory`: memory wire contracts; intentionally kept on the legacy
  public path until the memory contract cleanup is handled separately.

Legacy public paths such as `eidolon_sdk.http`, `eidolon_sdk.registry`, and
`eidolon_sdk.runtime` remain compatibility exports so downstream projects can
migrate imports in small steps.
