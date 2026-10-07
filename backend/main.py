import os
import secrets
import tempfile
import re
import time
from threading import BoundedSemaphore
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, APIRouter, UploadFile, File, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from backend.gate.config import Thresholds, load_config, MAX_UPLOAD_BYTES, ALGORITHM_VERSION
from backend.gate.image_input import read_image, InvalidImage
from backend.gate.pipeline import analyze
from backend.gate.models import Analysis
from backend.gate import storage
from backend.gate.multipart import PhotoUploadRoute

app = FastAPI(title='Barcode Quality Gate', version=ALGORITHM_VERSION)
analysis_slots = BoundedSemaphore(max(1, int(os.getenv('MAX_CONCURRENT_ANALYSES', '2'))))
analyze_router=APIRouter(route_class=PhotoUploadRoute)

class BodyLimit:
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http': return await self.app(scope,receive,send)
        total = 0
        async def limited():
            nonlocal total
            message = await receive()
            total += len(message.get('body',b''))
            if total > MAX_UPLOAD_BYTES + 65536: raise HTTPException(413, 'FILE_TOO_LARGE')
            return message
        await self.app(scope,limited,send)

app.add_middleware(BodyLimit)

@app.middleware('http')
async def request_context(request, call_next):
    request.state.request_id = str(uuid4())
    try:
        length = int(request.headers.get('content-length','0') or 0)
    except ValueError:
        length = -1
    if length < 0:
        response = JSONResponse({'error':'INVALID_CONTENT_LENGTH','request_id':request.state.request_id},400)
    elif length > MAX_UPLOAD_BYTES + 65536:
        response = JSONResponse({'error':'FILE_TOO_LARGE','request_id':request.state.request_id},413)
    else:
        try: response = await call_next(request)
        except Exception:
            response = JSONResponse({'error':'SYSTEM_ERROR','request_id':request.state.request_id},500)
    response.headers['X-Request-ID'] = request.state.request_id
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    code=exc.detail if isinstance(exc.detail,str) and re.fullmatch('[A-Z][A-Z0-9_]*',exc.detail) else 'INVALID_REQUEST'
    return JSONResponse({'error':code,'request_id':request.state.request_id},exc.status_code)

@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Do not echo untrusted inputs, admin payloads or file details in errors.
    return JSONResponse({'error':'INVALID_REQUEST','request_id':request.state.request_id},422)

def admin(token):
    expected = os.getenv('ADMIN_TOKEN')
    if not expected or not token or not secrets.compare_digest(token.encode('utf-8'), expected.encode('utf-8')):
        raise HTTPException(403,'ADMIN_REQUIRED')

@app.get('/api/v1/health')
def health(): return {'status':'ok','algorithm_version':ALGORITHM_VERSION}

@app.get('/api/v1/config')
def config():
    c = load_config()
    return {'thresholds':c.model_dump(),'config_version':c.version,'calibrated':False,'schema':Thresholds.model_json_schema()}

@app.put('/api/v1/config')
def set_config(c: Thresholds, x_admin_token: str | None = Header(None)):
    admin(x_admin_token)
    path = Path(os.getenv('GATE_CONFIG','config/thresholds.json'))
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,suffix='.tmp',delete=False) as f:
        f.write(c.model_dump_json(indent=2))
        temp = Path(f.name)
    try:
        for attempt in range(6):
            try:
                temp.replace(path)
                break
            except PermissionError:
                if attempt==5:raise
                # Windows may temporarily deny replacement while a reader or
                # another process's replacement still holds the target handle.
                time.sleep(.02*(attempt+1))
    finally:
        temp.unlink(missing_ok=True)
    storage.audit(c,datetime.now(timezone.utc).isoformat())
    return {'thresholds':c.model_dump(),'config_version':c.version}

@app.get('/api/v1/history',response_model=list[Analysis])
def get_history(x_admin_token: str | None = Header(None)):
    admin(x_admin_token)
    return storage.history()

@analyze_router.post('/api/v1/analyze',response_model=Analysis)
async def analyze_image(request: Request, image: UploadFile = File(...)):
    try:
        form = await request.form()
        if set(form) != {'image'} or len(form.getlist('image')) != 1:
            raise HTTPException(422,'INVALID_REQUEST')
        data = await image.read(MAX_UPLOAD_BYTES+1)
        return await run_in_threadpool(process_image,data,image.content_type,request.state.request_id)
    except InvalidImage as exc:
        raise HTTPException(413 if str(exc)=='FILE_TOO_LARGE' else 422,str(exc)) from exc
    finally:
        await image.close()

def process_image(data, mime, request_id):
    # The worker owns the permit, including on request cancellation. Never release
    # capacity while its native decoder is still running in a background thread.
    if not analysis_slots.acquire(blocking=False):
        raise HTTPException(503,'BUSY')
    try:
        pixels = read_image(data,mime)
        result = analyze(pixels,None,None,request_id)
        storage.store_image(data,result.request_id)
        storage.save_result(result)
        return result
    finally:
        analysis_slots.release()

app.include_router(analyze_router)
