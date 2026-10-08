# Model-first context and relative fan speed

`InterpretationRequest.context` is optional caller-owned JSON, bounded to 16 KiB. It carries recent completed turns and active clarification facts; it is evidence, never execution authorization. Its inclusion participates in normal request serialization/idempotency. Existing no-context callers remain valid. Upgrade consumers before sending the new field: older strict SDK schemas may reject it.

`TRAIT_COMMANDS.fan_speed` now exposes `step: {delta: integer[-100,100]}` in addition to absolute `set`. Relative semantics are implemented at Provider execution time; clients must not convert a spoken delta to an invented absolute value. Fan state remains `speed` (integer percentage) and `on`. Provider implementation and effect verification must be upgraded with this vocabulary addition.

See sibling Agent `docs/smart-home-model-first.md` and Hub `docs/adr/20261008-relative-fan-speed.md` for ownership and tests. Existing model weights and deployment pins are unchanged.
