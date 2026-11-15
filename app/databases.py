"""Real SQL Server storage and a separate Oracle reporting copy."""
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, UTC

import oracledb
import pymssql

from .config import required
from .fhir import financial_facts


@contextmanager
def sql_connection(admin=False, master=False):
    c = pymssql.connect(server=os.getenv('SQLSERVER_HOST', '127.0.0.1'),
                        port=int(os.getenv('SQLSERVER_PORT', '14339')),
                        user='sa' if admin else required('SQLSERVER_USER'),
                        password=required('MSSQL_SA_PASSWORD' if admin else 'SQLSERVER_PASSWORD'),
                        database='master' if master else os.getenv('SQLSERVER_DATABASE', 'HealthcareIntegrationLab'),
                        login_timeout=8, timeout=20, as_dict=True, autocommit=master)
    try:
        yield c
    finally:
        c.close()


@contextmanager
def oracle_connection(admin=False):
    c = oracledb.connect(user='system' if admin else required('ORACLE_USER'),
                        password=required('ORACLE_PWD' if admin else 'ORACLE_PASSWORD'),
                        tcp_connect_timeout=4, retry_count=0,
                        dsn=f"{os.getenv('ORACLE_HOST', '127.0.0.1')}:{os.getenv('ORACLE_PORT', '15219')}/{os.getenv('ORACLE_SERVICE', 'FREEPDB1')}")
    try:
        yield c
    finally:
        c.close()


def snapshot_hash(rows):
    pairs = sorted((r['resource_type'], r['resource_id'], r['payload_hash']) for r in rows)
    return hashlib.sha256(json.dumps(pairs, separators=(',', ':')).encode()).hexdigest()


def sql_import(data):
    manifest = {k: v for k, v in data.items() if k != 'resources'}
    manifest['imported_at'] = datetime.now(UTC).isoformat()
    manifest['snapshot_hash'] = snapshot_hash(data['resources'])
    key = data['patient_key']
    with sql_connection() as c:
        q = c.cursor()
        q.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
        q.execute('SELECT PatientKey FROM dbo.LabPatients WITH (UPDLOCK,HOLDLOCK) WHERE PatientKey=%s', (key,))
        if q.fetchone():
            q.execute('UPDATE dbo.LabPatients SET Manifest=%s WHERE PatientKey=%s', (json.dumps(manifest), key))
        else:
            q.execute('INSERT INTO dbo.LabPatients(PatientKey,Manifest) VALUES (%s,%s)', (key, json.dumps(manifest)))
        q.execute('DELETE FROM dbo.LabResources WHERE PatientKey=%s', (key,))
        for r in data['resources']:
            q.execute('INSERT INTO dbo.LabResources(PatientKey,ResourceType,ResourceId,PayloadHash,Payload) VALUES (%s,%s,%s,%s,%s)',
                      (key, r['resource_type'], r['resource_id'], r['payload_hash'], r['payload']))
        c.commit()
    return manifest


def oracle_mirror(data):
    """A separate transaction; failure must not be reported as a complete sync."""
    with oracle_connection() as c:
        q = c.cursor()
        q.execute('DELETE FROM LAB_MIRROR WHERE PATIENT_KEY=:1', [data['patient_key']])
        q.executemany('INSERT INTO LAB_MIRROR(PATIENT_KEY,RESOURCE_TYPE,RESOURCE_ID,PAYLOAD_HASH,PAYLOAD) VALUES (:1,:2,:3,:4,:5)',
                      [(data['patient_key'], r['resource_type'], r['resource_id'], r['payload_hash'], r['payload']) for r in data['resources']])
        c.commit()


def list_patients():
    with sql_connection() as c:
        q = c.cursor()
        q.execute('SELECT Manifest FROM dbo.LabPatients ORDER BY PatientKey')
        return [json.loads(r['Manifest']) for r in q.fetchall()]


def get_patient(key):
    with sql_connection() as c:
        q = c.cursor()
        q.execute('SELECT Manifest FROM dbo.LabPatients WHERE PatientKey=%s', (key,))
        row = q.fetchone()
        if not row:
            raise LookupError('Import this test record before querying it.')
        manifest = json.loads(row['Manifest'])
        q.execute('SELECT ResourceType,ResourceId,PayloadHash,Payload,JSON_VALUE(Payload,\'$.status\') AS FhirStatus FROM dbo.LabResources WHERE PatientKey=%s ORDER BY ResourceType,ResourceId', (key,))
        records = [{'resource_type': r['ResourceType'], 'resource_id': r['ResourceId'],
                    'payload_hash': r['PayloadHash'], 'fhir_status': r['FhirStatus'], 'resource': json.loads(r['Payload'])} for r in q.fetchall()]
    return manifest, records


def compare(key):
    manifest, records = get_patient(key)
    with oracle_connection() as c:
        q = c.cursor()
        q.execute("SELECT RESOURCE_TYPE,RESOURCE_ID,PAYLOAD_HASH,PAYLOAD,JSON_VALUE(PAYLOAD,'$.status') FROM LAB_MIRROR WHERE PATIENT_KEY=:1 ORDER BY RESOURCE_TYPE,RESOURCE_ID", [key])
        rows = []
        hashes_valid = True
        for r in q:
            # python-oracledb 4 decodes IS JSON columns to dictionaries;
            # older drivers may return a CLOB locator instead.
            resource = r[3] if isinstance(r[3], dict) else json.loads(r[3].read() if hasattr(r[3], 'read') else r[3])
            payload = json.dumps(resource, sort_keys=True, separators=(',', ':'))
            digest = hashlib.sha256(payload.encode()).hexdigest()
            hashes_valid &= digest == r[2]
            rows.append({'resource_type': r[0], 'resource_id': r[1], 'payload_hash': digest, 'fhir_status': r[4]})
        q.execute('SELECT RESOURCE_TYPE,COUNT(*) FROM LAB_MIRROR WHERE PATIENT_KEY=:1 GROUP BY RESOURCE_TYPE ORDER BY RESOURCE_TYPE', [key])
        counts = dict(q.fetchall())
    for record in records:
        payload = json.dumps(record['resource'], sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        hashes_valid &= digest == record['payload_hash']
        record['payload_hash'] = digest
    expected = snapshot_hash(records)
    actual = snapshot_hash(rows)
    return {'source_id': 'oracle-report:' + key, 'sql_count': len(records), 'oracle_count': len(rows),
            'oracle_counts_by_type': counts, 'hashes_match': expected == actual and hashes_valid and expected == manifest['snapshot_hash'],
            'stored_hashes_valid': hashes_valid,
            'oracle_statuses': [{'type': r['resource_type'], 'status': r['fhir_status']} for r in rows],
            'sql_snapshot_hash': expected, 'oracle_snapshot_hash': actual,
            'source_mode': manifest['source_mode']}


def evidence(key):
    manifest, records = get_patient(key)
    eobs = []
    for r in records:
        if r['resource_type'] == 'ExplanationOfBenefit':
            eobs.append({'id': r['resource_id'], 'status': r['fhir_status'], 'financial_facts': financial_facts(r['resource'])})
    return {'source_id': 'sqlserver-record:' + key, 'source_mode': manifest['source_mode'],
            'source_note': manifest['source_note'], 'snapshot_hash': manifest['snapshot_hash'],
            'patient_id': manifest['patient_id'], 'resource_count': len(records),
            'encounter_count': sum(r['resource_type'] == 'Encounter' for r in records),
            'eobs': eobs, 'personal_bill_balance_available': False, 'truncated': manifest['truncated']}


def record_preview(key):
    """Readable imported fields for the local lab, without inventing missing data."""
    manifest, records = get_patient(key)
    visits, insurance = [], []
    for row in records:
        r = row['resource']
        if row['resource_type'] == 'Encounter':
            visits.append({'id': r['id'], 'period': r.get('period', {}),
                           'status': r.get('status'), 'class': r.get('class', {})})
        elif row['resource_type'] == 'ExplanationOfBenefit':
            insurance.append({'id': r['id'], 'period': r.get('billablePeriod', {}),
                              'status': r.get('status'), 'outcome': r.get('outcome'),
                              'financial_facts': financial_facts(r)})
    return {'patient_id': manifest['patient_id'], 'source_label': manifest['source_label'],
            'source_mode': manifest['source_mode'], 'imported_at': manifest['imported_at'],
            'counts': {'patients': sum(r['resource_type'] == 'Patient' for r in records),
                       'visits': len(visits), 'insurance': len(insurance)},
            'visits': sorted(visits, key=lambda r: r['period'].get('start', ''), reverse=True),
            'insurance': sorted(insurance, key=lambda r: r['period'].get('start', ''), reverse=True)}


def save_case(case):
    with sql_connection() as c:
        q = c.cursor()
        q.execute('INSERT INTO dbo.LabCases(CaseId,PatientKey,Payload) VALUES (%s,%s,%s)',
                  (case['id'], case['patient_key'], json.dumps(case)))
        c.commit()


def list_cases():
    with sql_connection() as c:
        q = c.cursor()
        q.execute('SELECT TOP (20) Payload FROM dbo.LabCases ORDER BY CreatedAt DESC')
        return [json.loads(r['Payload']) for r in q.fetchall()]


def review_case(case_id, decision, reply):
    with sql_connection() as c:
        q = c.cursor()
        q.execute('SELECT Payload FROM dbo.LabCases WITH (UPDLOCK,ROWLOCK) WHERE CaseId=%s', (case_id,))
        row = q.fetchone()
        if not row:
            raise LookupError('Case not found')
        case = json.loads(row['Payload'])
        if case['status'] != 'awaiting_review':
            raise ValueError('This case has already been reviewed')
        q.execute('SELECT Manifest FROM dbo.LabPatients WITH (HOLDLOCK) WHERE PatientKey=%s', (case['patient_key'],))
        current = json.loads(q.fetchone()['Manifest'])
        if decision == 'approve' and current['snapshot_hash'] != case['snapshot_hash']:
            raise ValueError('The source snapshot changed. Generate a new draft before approving.')
        if decision == 'approve' and not all(case['checks'].values()):
            raise ValueError('Evidence checks failed. The draft cannot be approved.')
        case['status'] = 'approved' if decision == 'approve' else 'rejected'
        case['response'] = reply if decision == 'approve' else None
        case['reviewed_at'] = datetime.now(UTC).isoformat()
        q.execute('UPDATE dbo.LabCases SET Payload=%s WHERE CaseId=%s', (json.dumps(case), case_id))
        c.commit()
    return case


def health():
    result = {}
    for name, factory, query in [
        ('sqlserver', sql_connection, 'SELECT CAST(SERVERPROPERTY(\'ProductVersion\') AS varchar(80)) AS Version'),
        ('oracle', oracle_connection, "SELECT PRODUCT || ' ' || VERSION_FULL FROM PRODUCT_COMPONENT_VERSION WHERE ROWNUM=1"),
    ]:
        try:
            with factory() as c:
                q = c.cursor(); q.execute(query); row = q.fetchone()
                version = row['Version'] if isinstance(row, dict) else row[0]
            result[name] = {'connected': True, 'version': version}
        except Exception as exc:
            result[name] = {'connected': False, 'error': type(exc).__name__}
    return result
