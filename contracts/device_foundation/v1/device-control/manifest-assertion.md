# Manifest assertion 1.1

`POST /api/device-control/v1/manifest:assert` accepts only assertion contract
version `1.1`. There is one signing format, with no digest-only verification
fallback. The response remains the unchanged acceptance contract `1.0`.

The P-256 proof signs the RFC 8785 canonical form of:

```json
{
  "device_ref": {"...": "the exact current DeviceRef"},
  "manifest_ref": {
    "manifest_id": "the name established at admission",
    "revision": 2,
    "digest": "sha256:..."
  },
  "nonce": "the request nonce",
  "operation_type": "device-control.manifest-assert"
}
```

The SDK recomputes the digest from the submitted document. The proof binds the
name, ordering and content together; changing any one requires a new signature.
The authoritative golden is `golden/device-control-manifest-assertion-proof.json`.

For the current active Claim and exact DeviceRef:

1. The operational key must verify the complete proof.
2. `manifest_id` is fixed at admission for the Claim. It is not a rename field.
3. A lower revision is refused.
4. An equal revision succeeds only if the entire ManifestRef equals the stored
   reference. The response returns that stored reference, with `unchanged`.
5. A higher revision atomically updates the document and revision with the
   existing device-mutation CAS and audit event. The manifest name is preserved.

No nonce database, second capability store, legacy verifier or migration parser
is needed. Replaying the current assertion is idempotent; once a newer revision
is stored, older signed assertions cannot become current again. A concurrent
update still has to pass the existing CAS. The device reads configuration to
learn the accepted revision before producing another assertion.

This is a coordinated protocol cutover: update the SDK/Hub, mobile client and
firmware together, and sync client fixtures from the committed SDK version.
Stored manifests and Claims need no migration or re-enrollment. Old clients can
still read configuration; assertion `1.0` is rejected and cannot update their
manifest until the client is upgraded. Do not deploy a dual-format fallback.
