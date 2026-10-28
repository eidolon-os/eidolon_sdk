# Device recognition declarations

Device Foundation V1 reserves two optional `properties` names in
`DeviceCapabilityManifest`:

| Name | Meaning |
| --- | --- |
| `recognition.voiceprint` | The device implements local speaker identity matching from a voiceprint. |
| `recognition.face` | The device implements local face identity matching. Owner-only matching qualifies; multi-person identification is not implied. |

Example of an installed capability:

```json
{
  "name": "recognition.face",
  "observable": false,
  "writable": false,
  "schema": {"type": "boolean", "const": true}
}
```

Each name may occur at most once. The schema contains exactly `type: boolean`
and a boolean `const`; strings, numbers, dynamic values and additional schema
constraints are rejected. `false` and absence both mean no declared support.
Old clients may continue omitting these properties. Other property namespaces
remain extensible. Both JSON Schema and Python admission validation enforce
these vocabulary rules; historical directory reads remain permissive.

These are installed facilities, independent of runtime availability, enrollment
of biometric templates, Owner authorization and whether a recognizer is active.
Microphone/camera capture, VAD, face detection, and host-side recognition do not
imply either declaration. Local inference need not publish audio or video.

The attributes carry no biometric data, identity evidence, grants, actions or
results. They do not enable recognition, dispatch an agent tool, or establish a
person's identity. A future recognition workflow must separately define trusted
results, model/profile versions, authorization and lifecycle invalidation.
Existing owner-face and voiceprint services remain the implementation owners.

Use the existing Manifest digest, enrollment and signed assertion path. A change
in a declaration changes the digest and advances the device's accepted revision;
there is no separate recognition registry or synchronization protocol. SDK Python
exports `RECOGNITION_VOICEPRINT_PROPERTY` and `RECOGNITION_FACE_PROPERTY`.

The ESP32 producer has corresponding `DeviceCapabilities` members. Face support
comes from the existing `CONFIG_EIDOLON_OWNER_FACE_PROFILE` build facility;
voiceprint support defaults off. Mobile currently implements neither local
recognizer and omits both properties. Managing face photos or voiceprints in a
mobile UI is not local recognition support.
