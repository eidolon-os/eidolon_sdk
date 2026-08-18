# eidolon-sdk

Shared Python contracts and infrastructure for the Eidolon project family.

The canonical Device Foundation V1 contract is under
[`contracts/device_foundation/v1`](contracts/device_foundation/v1/README.md). No other repository
may maintain a handwritten synonymous V1 DTO or schema.

The package is organized by responsibility:

- `eidolon_sdk.core`: transport, storage, wire-format, and async infrastructure.
- `eidolon_sdk.biz`: shared Eidolon business contracts used by multiple projects.
- `eidolon_sdk.integrations`: third-party integration helpers.
- `eidolon_sdk.adapters`: storage adapters for SDK-owned contracts.

The memory service's wire contracts used to live here as `eidolon_sdk.memory`.
They now ship as `eidolon-memory-contracts`, alongside the service that owns
them, so that service can be built and released without the OS SDK. Clients of
memory depend on that package directly.

## License

Copyright © 2026 Li Jinsong.

This project is available under the
[PolyForm Noncommercial License 1.0.0](LICENSE) for permitted noncommercial
use. Commercial use requires a separate written license; contact
[lijinsong@aimanthor.com](mailto:lijinsong@aimanthor.com).

See [LICENSING.md](LICENSING.md) and [NOTICE](NOTICE) for scope, exceptions,
and required notices.
