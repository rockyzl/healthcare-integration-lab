import asyncio
import os
from datetime import datetime, UTC
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import databases as db
from . import fhir
from .agent import draft_reply
from .config import ROOT

app = FastAPI(title='Healthcare Integration Lab', description='Local synthetic-data learning prototype')
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])
app.mount('/assets', StaticFiles(directory=ROOT / 'app/static'), name='assets')
operation_lock = asyncio.Lock()


@app.middleware('http')
async def local_write_guard(request: Request, call_next):
    if request.method == 'POST' and request.headers.get('X-Lab-Request') != 'demo':
        return JSONResponse({'detail': 'Use the local demo page.'}, status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.get('/', response_class=HTMLResponse)
def index():
    return (ROOT / 'app/static/index.html').read_text()


@app.get('/api/status')
def status():
    systems = db.health()
    return {'systems': systems, 'patients': db.list_patients() if systems['sqlserver']['connected'] else [],
            'model': os.getenv('MODEL', 'gemini-3.8-flash'), 'fhir_base': fhir.FHIR_BASE,
            'vendor_connections': {'Epic': False, 'ServiceNow': False, 'UKG': False}}


@app.post('/api/import/{source}')
async def import_source(source: Literal['live', 'fixture']):
    if operation_lock.locked():
        raise HTTPException(409, 'An import or draft is already running. Please wait.')
    async with operation_lock:
        try:
            data = await fhir.fetch_live() if source == 'live' else fhir.load_fixture()
            manifest = await run_in_threadpool(db.sql_import, data)
            await run_in_threadpool(db.oracle_mirror, data)
            comparison = await run_in_threadpool(db.compare, data['patient_key'])
        except Exception as exc:
            # A successful SQL write is retained if the independent Oracle write fails.
            raise HTTPException(502, f'Import did not complete across both databases ({type(exc).__name__}). Re-run after checking connections.') from exc
    return {'patient': manifest, 'comparison': comparison}


@app.get('/api/records/{key}')
def record(key: str):
    try:
        return {'record': db.evidence(key), 'comparison': db.compare(key)}
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


class Question(BaseModel):
    patient_key: str = Field(pattern=r'^[a-f0-9]{64}$')
    message: str = Field(min_length=5, max_length=700)


@app.post('/api/cases')
async def create_case(body: Question):
    if operation_lock.locked():
        raise HTTPException(409, 'An import or draft is already running. Please wait.')
    async with operation_lock:
        try:
            result = await asyncio.wait_for(draft_reply(body.patient_key, body.message), timeout=170)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, f'The real model run did not complete ({type(exc).__name__}). No reply was published.') from exc
        case = {'id': uuid4().hex, 'patient_key': body.patient_key, 'question': body.message,
                'status': 'awaiting_review', 'created_at': datetime.now(UTC).isoformat(),
                'response': None, **result}
        await run_in_threadpool(db.save_case, case)
    return case


@app.get('/api/cases')
def cases():
    return {'cases': db.list_cases()}


class Decision(BaseModel):
    decision: Literal['approve', 'reject']
    reply: str = Field(min_length=1, max_length=2200)


@app.post('/api/cases/{case_id}/review')
def review(case_id: str, body: Decision):
    try:
        return db.review_case(case_id, body.decision, body.reply)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
