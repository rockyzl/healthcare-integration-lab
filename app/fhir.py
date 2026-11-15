"""Read a bounded public FHIR sandbox or a pinned public Synthea example.

No arbitrary server URL, patient search, credentials, or remote write operation
is exposed. Names, SSNs, addresses and clinical narrative are not retained.
"""
import hashlib
import json
from copy import deepcopy
from decimal import Decimal

import httpx

from .config import FHIR_BASE, ROOT, SAMPLE_PATIENT

RESOURCE_TYPES = ('Patient', 'Encounter', 'ExplanationOfBenefit')


def patient_key(source, patient_id):
    return hashlib.sha256(f'{source}|Patient|{patient_id}'.encode()).hexdigest()


def clean_resource(resource):
    kind = resource.get('resourceType')
    common = {'resourceType', 'id', 'status', 'active'}
    allowed = {
        'Patient': common,
        'Encounter': common | {'subject', 'period', 'class'},
        'ExplanationOfBenefit': common | {'patient', 'billablePeriod', 'outcome', 'total', 'payment'},
    }
    if kind not in allowed or not resource.get('id'):
        raise ValueError('Unsupported or unidentified resource')
    result = {k: deepcopy(v) for k, v in resource.items() if k in allowed[kind]}
    # Display/text fields may contain names or narrative. Keep only references.
    for field in ('patient', 'subject'):
        if field in result:
            result[field] = {'reference': result[field].get('reference', '')}
    return result


def belongs_to(resource, patient_id, patient_full_url=None):
    if resource.get('resourceType') == 'Patient':
        return resource.get('id') == patient_id
    ref = (resource.get('patient') or resource.get('subject') or {}).get('reference', '')
    return isinstance(ref, str) and bool(ref) and ref in {f'Patient/{patient_id}', f'{FHIR_BASE}/Patient/{patient_id}', patient_full_url}


def normalize(source, resources, patient_id, full_url=None):
    selected = []
    seen = set()
    for raw in resources:
        if raw.get('resourceType') not in RESOURCE_TYPES:
            continue
        if not belongs_to(raw, patient_id, full_url):
            raise ValueError('Resource belongs to a different or unverified patient')
        item = clean_resource(raw)
        key = (item['resourceType'], item['id'])
        if key in seen:
            raise ValueError('Duplicate resource identity in the import')
        seen.add(key)
        payload = json.dumps(item, sort_keys=True, separators=(',', ':'))
        selected.append({'resource_type': key[0], 'resource_id': key[1], 'payload': payload,
                         'payload_hash': hashlib.sha256(payload.encode()).hexdigest()})
    if ('Patient', patient_id) not in seen:
        raise ValueError('Import is missing its patient resource')
    return {'patient_key': patient_key(source, patient_id), 'patient_id': patient_id,
            'source': source, 'resources': selected}


def load_fixture():
    manifest = json.loads((ROOT / 'data/provenance.json').read_text())
    raw = (ROOT / 'data/synthea-billing-example.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest['local_sha256']:
        raise ValueError('The pinned example does not match its provenance hash')
    data = json.loads(raw)
    p = next(e for e in data['entry'] if e['resource']['resourceType'] == 'Patient')
    imported = normalize(manifest['source_url'], [e['resource'] for e in data['entry']],
                         p['resource']['id'], p['fullUrl'])
    return imported | {'source_mode': 'pinned_public_fixture', 'source_label': 'Public Synthea example',
                       'source_note': 'A pinned synthetic example file, not a live hospital feed.', 'truncated': False}


async def fetch_live():
    async with httpx.AsyncClient(timeout=30, follow_redirects=False,
                                 headers={'Accept': 'application/fhir+json'}) as client:
        capability = await client.get(FHIR_BASE + '/metadata')
        capability.raise_for_status()
        version = capability.json().get('fhirVersion', '')
        if not version.startswith('4.0.'):
            raise ValueError('The selected server is not FHIR R4')
        response = await client.get(f'{FHIR_BASE}/Patient/{SAMPLE_PATIENT}')
        response.raise_for_status()
        patient = response.json()
        if not any(i.get('system') == 'https://github.com/synthetichealth/synthea'
                   for i in patient.get('identifier', [])):
            raise ValueError('The selected test patient no longer has Synthea provenance')
        resources = [patient]
        truncated = False
        totals = {}
        for kind in RESOURCE_TYPES[1:]:
            response = await client.get(f'{FHIR_BASE}/{kind}', params={'patient': SAMPLE_PATIENT, '_count': 30})
            response.raise_for_status()
            bundle = response.json()
            if bundle.get('resourceType') != 'Bundle':
                raise ValueError('FHIR search did not return a Bundle')
            entries = [e['resource'] for e in bundle.get('entry', []) if e.get('search', {}).get('mode') != 'outcome']
            if any(e.get('resourceType') != kind for e in entries):
                raise ValueError('Unexpected resource type in patient-scoped search')
            totals[kind] = bundle.get('total')
            truncated |= len(entries) > 30 or any(l.get('relation') == 'next' for l in bundle.get('link', []))
            resources.extend(entries[:30])
    return normalize(FHIR_BASE, resources, SAMPLE_PATIENT) | {
        'source_mode': 'live_fhir', 'source_label': 'Live SMART FHIR R4 sandbox',
        'source_note': 'Live public test API; Synthea-marked record. No hospital or Epic connection.',
        'fhir_version': version, 'reported_totals': totals, 'truncated': truncated}


def financial_facts(resource):
    """Keep each EOB total category; do not derive a personal balance."""
    out = []
    for total in resource.get('total', []):
        money = total.get('amount') or {}
        if 'value' not in money:
            continue
        amount = Decimal(str(money['value']))
        if not amount.is_finite():
            raise ValueError('Non-finite FHIR amount')
        coding = (total.get('category') or {}).get('coding', [])
        category = coding[0].get('code', 'unspecified') if coding else 'unspecified'
        out.append({'kind': 'EOB total', 'category': category, 'value': str(amount), 'currency': money.get('currency', 'unknown')})
    payment = (resource.get('payment') or {}).get('amount') or {}
    if 'value' in payment:
        amount = Decimal(str(payment['value']))
        if not amount.is_finite():
            raise ValueError('Non-finite FHIR payment')
        out.append({'kind': 'EOB payment', 'category': 'payment', 'value': str(amount), 'currency': payment.get('currency', 'unknown')})
    return out
