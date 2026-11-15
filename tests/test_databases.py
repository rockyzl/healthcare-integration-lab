"""Opt-in checks against real local engines; isolated temporary patient scope."""
import copy
import json
import os
from uuid import uuid4

import pytest

from app import databases as db, fhir

pytestmark = pytest.mark.skipif(os.getenv('RUN_DB_TESTS') != '1', reason='Set RUN_DB_TESTS=1 with both local databases running')


@pytest.fixture
def imported():
    data = copy.deepcopy(fhir.load_fixture())
    data['patient_key'] = fhir.patient_key('verification-' + uuid4().hex, data['patient_id'])
    key = data['patient_key']
    db.sql_import(data)
    db.oracle_mirror(data)
    try:
        yield data
    finally:
        with db.sql_connection() as c:
            q = c.cursor()
            for table in ('LabCases', 'LabResources', 'LabPatients'):
                q.execute(f'DELETE FROM dbo.{table} WHERE PatientKey=%s', (key,))
            c.commit()
        with db.oracle_connection() as c:
            c.cursor().execute('DELETE FROM LAB_MIRROR WHERE PATIENT_KEY=:1', [key])
            c.commit()


def test_reimport_is_idempotent_and_query_is_parameterized(imported):
    key = imported['patient_key']
    db.sql_import(imported)
    db.oracle_mirror(imported)
    report = db.compare(key)
    assert report['hashes_match']
    assert report['sql_count'] == report['oracle_count'] == 7
    with pytest.raises(LookupError):
        db.get_patient("' OR 1=1 --")


def test_modified_oracle_payload_is_detected(imported):
    key = imported['patient_key']
    with db.oracle_connection() as c:
        c.cursor().execute("UPDATE LAB_MIRROR SET PAYLOAD=:1 WHERE PATIENT_KEY=:2 AND RESOURCE_TYPE='Patient'",
                           [json.dumps({'resourceType': 'Patient', 'id': 'corrupted'}), key])
        c.commit()
    assert not db.compare(key)['hashes_match']


def make_case(data, checks=None):
    manifest, _ = db.get_patient(data['patient_key'])
    case = {'id': uuid4().hex, 'patient_key': data['patient_key'], 'status': 'awaiting_review',
            'snapshot_hash': manifest['snapshot_hash'], 'checks': checks or {'evidence': True},
            'response': None, 'draft': {'response': 'Verification-only draft'}}
    db.save_case(case)
    return case


def test_review_requires_checks_and_can_only_happen_once(imported):
    case = make_case(imported, {'evidence': False})
    with pytest.raises(ValueError, match='checks failed'):
        db.review_case(case['id'], 'approve', 'Should not publish')
    rejected = db.review_case(case['id'], 'reject', 'Needs investigation')
    assert rejected['response'] is None
    case = make_case(imported)
    approved = db.review_case(case['id'], 'approve', 'Reviewed response')
    assert approved['response'] == 'Reviewed response'
    with pytest.raises(ValueError, match='already been reviewed'):
        db.review_case(case['id'], 'approve', 'Second response')


def test_stale_snapshot_cannot_be_approved(imported):
    case = make_case(imported)
    changed = copy.deepcopy(imported)
    changed['resources'] = changed['resources'][:-1]
    db.sql_import(changed)
    with pytest.raises(ValueError, match='snapshot changed'):
        db.review_case(case['id'], 'approve', 'Should not publish stale evidence')
