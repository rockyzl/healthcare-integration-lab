import copy
import json

import pytest
from fastapi.testclient import TestClient

from app import fhir
from app.agent import check_draft
from app.main import app


@pytest.mark.parametrize('reference', [None, '', 'Patient/someone-else', 'https://evil.example/Patient/p'])
def test_foreign_or_unverified_reference_is_rejected(reference):
    with pytest.raises(ValueError, match='unverified patient'):
        fhir.normalize('test', [{'resourceType': 'Patient', 'id': 'p'},
                               {'resourceType': 'Encounter', 'id': 'e', 'subject': {'reference': reference}}], 'p')


def test_duplicate_or_missing_patient_is_rejected():
    patient = {'resourceType': 'Patient', 'id': 'p'}
    with pytest.raises(ValueError, match='Duplicate'):
        fhir.normalize('test', [patient, patient], 'p')
    with pytest.raises(ValueError, match='missing'):
        fhir.normalize('test', [], 'p')


def test_identity_is_scoped_to_its_source():
    assert fhir.patient_key('hospital-a', 'p') != fhir.patient_key('hospital-b', 'p')


def test_pinned_fixture_keeps_amounts_but_not_personal_identifiers():
    record = fhir.load_fixture()
    assert len(record['resources']) == 7
    assert record['source_mode'] == 'pinned_public_fixture'
    for item in record['resources']:
        resource = json.loads(item['payload'])
        assert not {'name', 'identifier', 'address', 'text', 'telecom'} & resource.keys()
    eobs = [json.loads(r['payload']) for r in record['resources'] if r['resource_type'] == 'ExplanationOfBenefit']
    assert all(fhir.financial_facts(eob) for eob in eobs)


def test_amounts_are_not_combined_into_a_patient_balance():
    facts = fhir.financial_facts({'total': [{'category': {'coding': [{'code': 'submitted'}]},
                                          'amount': {'value': 150, 'currency': 'USD'}}],
                                 'payment': {'amount': {'value': 90, 'currency': 'USD'}}})
    assert [f['value'] for f in facts] == ['150', '90']
    assert not any(f['value'] == '60' for f in facts)
    with pytest.raises(ValueError, match='Non-finite'):
        fhir.financial_facts({'payment': {'amount': {'value': 'NaN'}}})


def test_service_content_survives_projection_without_address_or_narrative():
    raw = {'resourceType': 'ExplanationOfBenefit', 'id': 'e',
           'text': {'div': 'PRIVATE NARRATIVE'}, 'identifier': [{'value': 'PRIVATE ID'}],
           'item': [{'sequence': 1, 'productOrService': {'coding': [{'code': '162673000', 'display': 'General examination of patient (procedure)'}]},
                     'net': {'value': 42.5, 'currency': 'USD'},
                     'locationAddress': {'line': ['PRIVATE ADDRESS']}}]}
    cleaned = fhir.clean_resource(raw)
    assert cleaned['item'][0]['productOrService'] == raw['item'][0]['productOrService']
    assert cleaned['item'][0]['net'] == {'value': 42.5, 'currency': 'USD'}
    assert 'PRIVATE' not in json.dumps(cleaned)


def test_public_fixture_includes_actual_lines_and_preserves_missing_line_amounts():
    resources = [json.loads(r['payload']) for r in fhir.load_fixture()['resources']]
    encounters = [r for r in resources if r['resourceType'] == 'Encounter']
    assert all(r['type'][0]['coding'][0]['code'] for r in encounters)
    lines = [i for r in resources if r['resourceType'] == 'ExplanationOfBenefit' for i in r['item']]
    assert len(lines) == 5
    assert any(fhir.concept_text(i['productOrService']) == 'Prediabetes' for i in lines)
    assert all('net' not in line and 'unitPrice' not in line for line in lines)


def test_fabricated_amount_missing_tool_and_bad_reference_fail_checks():
    key = 'a' * 64
    trace = [
        {'output': {'source_id': 'sqlserver-record:' + key, 'eobs': [{'financial_facts': [{'value': '90', 'currency': 'USD'}]}]}},
        {'output': {'source_id': 'oracle-report:' + key, 'hashes_match': True}},
    ]
    draft = {'response': 'Recorded payment: $90.', 'evidence_ids': ['sqlserver-record:' + key, 'oracle-report:' + key]}
    assert all(check_draft(draft, trace, key).values())
    wrong = copy.deepcopy(draft)
    wrong['response'] = 'You owe $60.'
    assert not check_draft(wrong, trace, key)['quoted_amounts_in_evidence']
    assert not check_draft(draft, trace[:1], key)['both_tools_called']
    wrong['evidence_ids'] = ['unrelated-source']
    assert not check_draft(wrong, trace, key)['references_match']


def test_local_api_rejects_cross_site_writes_and_invalid_inputs():
    client = TestClient(app)
    assert client.post('/api/import/fixture').status_code == 403
    assert client.get('/', headers={'Host': 'untrusted.example'}).status_code == 400
    headers = {'X-Lab-Request': 'demo'}
    assert client.post('/api/cases', headers=headers, json={'patient_key': "' OR 1=1", 'message': 'Explain this'}).status_code == 422
    assert client.post('/api/import/other', headers=headers).status_code == 422
