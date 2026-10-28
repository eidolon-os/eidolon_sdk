"""Recognition declarations are facts, never media grants or identity evidence."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from eidolon_sdk.device_foundation.v1 import (
    DeviceCapabilityManifest, ManifestDocument, manifest_digest,
    RECOGNITION_FACE_PROPERTY, RECOGNITION_VOICEPRINT_PROPERTY,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / 'contracts/device_foundation/v1/common/schemas.schema.json').read_text())
VALIDATOR = Draft202012Validator({**SCHEMA, '$ref': '#/$defs/DeviceCapabilityManifest'})
NAMES = (RECOGNITION_VOICEPRINT_PROPERTY, RECOGNITION_FACE_PROPERTY)


def document(properties):
    return dict(schema_version=1, title='Local recognizer', properties=properties,
                actions=[], events=[], media=[])


def declaration(name, enabled=True):
    return dict(name=name, observable=False, writable=False,
                schema={'type': 'boolean', 'const': enabled})


@pytest.mark.parametrize('properties', [[], [declaration(n) for n in NAMES],
                                       [declaration(n, False) for n in NAMES]])
def test_recognition_is_optional_and_does_not_require_media(properties):
    value = document(properties)
    VALIDATOR.validate(value)
    manifest = ManifestDocument(manifest_id='local-recognizer', revision=1,
                                digest=manifest_digest(value), document=value)
    assert manifest.document == value
    assert DeviceCapabilityManifest.model_validate(value).media == ()


@pytest.mark.parametrize('name', NAMES)
@pytest.mark.parametrize('mutation', ['writable', 'observable', 'string', 'integer',
                                     'missing_const', 'extra_schema', 'duplicate'])
def test_wire_and_runtime_reject_ambiguous_recognition(name, mutation):
    prop = declaration(name)
    properties = [prop]
    if mutation in ('writable', 'observable'):
        prop[mutation] = True
    elif mutation == 'string':
        prop['schema']['const'] = 'true'
    elif mutation == 'integer':
        prop['schema']['const'] = 1
    elif mutation == 'missing_const':
        del prop['schema']['const']
    elif mutation == 'extra_schema':
        prop['schema']['enum'] = [False]
    elif mutation == 'duplicate':
        properties.append(declaration(name, False))
    value = document(properties)
    assert list(VALIDATOR.iter_errors(value))
    with pytest.raises(ValidationError):
        ManifestDocument(manifest_id='local-recognizer', revision=2,
                         digest=manifest_digest(value), document=value)


def test_recognition_change_is_part_of_the_existing_manifest_digest():
    original = document([declaration(NAMES[0], False)])
    changed = deepcopy(original)
    changed['properties'][0]['schema']['const'] = True
    assert manifest_digest(original) != manifest_digest(changed)
