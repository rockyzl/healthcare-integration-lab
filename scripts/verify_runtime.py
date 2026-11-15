"""Exercise the running local app; optionally make two real Vertex calls.

Uses only this lab's public synthetic sources. Approvals affect local previews.
"""
import argparse
import json
from datetime import datetime, UTC
from pathlib import Path

import httpx

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--with-model', action='store_true', help='Call the configured real Vertex model twice')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
report = {'verified_at_utc': datetime.now(UTC).isoformat(), 'live_model_test': args.with_model, 'sources': {}, 'cases': []}
with httpx.Client(base_url='http://127.0.0.1:8780', timeout=190,
                  headers={'X-Lab-Request': 'demo'}) as client:
    def call(method, path, **kwargs):
        r = client.request(method, path, **kwargs)
        r.raise_for_status()
        return r.json()

    status = call('GET', '/api/status')
    assert all(s['connected'] for s in status['systems'].values()), status['systems']
    report['databases'] = status['systems']
    report['model'] = status['model']
    report['vendor_connections'] = status['vendor_connections']
    for source in ('fixture', 'live'):
        result = call('POST', '/api/import/' + source, json={})
        assert result['comparison']['hashes_match']
        key = result['patient']['patient_key']
        report['sources'][source] = result
        print(f"{source}: imported and reconciled {result['comparison']['sql_count']} records", flush=True)
        if not args.with_model:
            continue
        case = call('POST', '/api/cases', json={
            'patient_key': key,
            'message': 'The patient received an insurance explanation. What amounts are recorded, and what information is still missing before we tell them what they owe?',
        })
        assert case['status'] == 'awaiting_review' and case['response'] is None
        assert all(case['checks'].values()), case['checks']
        if source == 'fixture':
            approved = call('POST', '/api/cases/' + case['id'] + '/review', json={
                'decision': 'approve', 'reply': case['draft']['response']})
            assert approved['status'] == 'approved' and approved['response']
            decision = 'approved'
        else:
            # Keep the missing-EOB example ready for an interactive review.
            decision = 'awaiting_review'
        report['cases'].append({'source': source, 'id': case['id'], 'status': decision,
                                'model': case['model'], 'checks': case['checks'],
                                'tools_called': [t['tool'] for t in case['trace']],
                                'draft': case['draft']})
        print(f"{source}: real agent completed; checks passed; {decision}", flush=True)
report['limitations'] = [
    'Synthetic public data only; no hospital/Epic/ServiceNow/UKG connection',
    'Local simulated review, no UiPath in this repository and no real patient message',
    'FHIR projections and bounded snapshot, not an entire EHR',
    'Content agreement and dollar-amount checks do not prove every model statement correct',
]
(root / 'reports').mkdir(exist_ok=True)
(root / 'reports/verification.json').write_text(json.dumps(report, indent=2) + '\n')
print('Saved reports/verification.json (no credentials).')
