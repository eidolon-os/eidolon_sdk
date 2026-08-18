# Eidolon Device Foundation V1 canonical contract

This directory is the only physical source for the public Device Foundation V1 contract.
Authorities still own domain semantics and producer behavior; the SDK owns schemas, fixtures,
golden vectors, generation inputs, and the shared conformance runner.

P0 scope is intentionally limited. It does not switch a production writer or reader, add the
Device Control bounded context to Hub, preserve a legacy route/DTO/database shape, deploy Pi5,
or flash a device.

The frozen trust profile is `eidolon-trust-p256-hpke-v1`. It fixes RFC 8785 JCS, ES256 P-256
signatures encoded as 64-byte `R || S`, RFC 9180 Base mode with P-256/HKDF-SHA256/AES-128-GCM
for ClaimGrant handoff, and Protocomm Security 2 for the near-field session. Implementations may
not negotiate a downgrade under this profile id.

Run the P0 gates from the `eidolon_sdk` repository:

```bash
uv run python contracts/device_foundation/v1/conformance/run.py
uv run python contracts/device_foundation/v1/generation/generate.py --check
uv run python contracts/device_foundation/v1/baseline/verify.py --workspace-root ..
uv run pytest tests/contracts/test_device_foundation_v1.py
```

`baseline/cross-repo-heads.v1.json` is the immutable pre-change P0 freeze. It deliberately records
the SDK HEAD before this contract was added; a manifest stored inside a Git commit cannot contain
that same commit's own SHA. Use `baseline/verify.py --exact` only to audit the capture facts or
diagnose later drift. Repository-set verification remains the ongoing omission/addition gate.

Generated output is limited to `generated/catalog.json` in P0. Language binding targets are
declared but remain `planned`; producer and consumer cutover belongs to P1-P6.
