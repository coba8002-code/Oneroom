"""Supabase Storage REST API 흉내 (시험용) — 메모리에 보관, 서비스 키 검사."""
import json
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
SIGNED: dict[str, str] = {}
STATS = {"signed_downloads": 0, "signed_uploads": 0, "bytes_up": 0, "bytes_down": 0}
OBJ: dict[str, bytes] = {}
KEY = "fake-service-key"

def auth(req: Request):
    if req.headers.get("authorization") != f"Bearer {KEY}" or req.headers.get("apikey") != KEY:
        raise HTTPException(401)

@app.post("/storage/v1/object/list/{bucket}")
async def list_(bucket: str, req: Request):
    auth(req); b = json.loads(await req.body()); folder = b["prefix"]
    names = sorted(k[len(folder)+1:] for k in OBJ if k.startswith(f"{bucket}/{folder}/".removeprefix(f"{bucket}/")) and "/" not in k[len(folder)+1:])
    names = [n for n in names if n.startswith(b["search"])]
    return [{"name": n, "id": "1"} for n in names]

@app.post("/storage/v1/object/sign/{bucket}/{path:path}")
async def sign(bucket: str, path: str, req: Request):
    auth(req); SIGNED["dl-"+path] = "tok"; return {"signedURL": f"/object/sign/{bucket}/{path}?token=tok"}

@app.get("/storage/v1/object/sign/{bucket}/{path:path}")
async def signed_get(bucket: str, path: str, token: str, download: str = ""):
    if SIGNED.get("dl-"+path) != token: raise HTTPException(400)
    STATS["signed_downloads"] += 1; STATS["bytes_down"] += len(OBJ[path])
    return Response(OBJ[path], headers={"Content-Disposition": f'attachment; filename="{download}"'})

@app.post("/storage/v1/object/upload/sign/{bucket}/{path:path}")
async def sign_up(bucket: str, path: str, req: Request):
    auth(req); SIGNED["up-"+path] = "uptok"; return {"url": f"/object/upload/sign/{bucket}/{path}?token=uptok"}

@app.put("/storage/v1/object/upload/sign/{bucket}/{path:path}")
async def signed_put(bucket: str, path: str, token: str, req: Request):
    if SIGNED.get("up-"+path) != token: raise HTTPException(400)
    body = await req.body(); OBJ[path] = body
    STATS["signed_uploads"] += 1; STATS["bytes_up"] += len(body); return {"Key": path}

@app.get("/_debug/stats")
def stats(): return STATS

@app.post("/storage/v1/object/move")
async def move(req: Request):
    auth(req); b = json.loads(await req.body()); OBJ[b["destinationKey"]] = OBJ.pop(b["sourceKey"]); return {}

@app.post("/storage/v1/object/{bucket}/{path:path}")
async def put(bucket: str, path: str, req: Request):
    auth(req); OBJ[path] = await req.body(); return {"Key": f"{bucket}/{path}"}

@app.get("/storage/v1/object/{bucket}/{path:path}")
async def get(bucket: str, path: str, req: Request):
    auth(req)
    if path not in OBJ: return Response(status_code=400, content=b'{"error":"not_found"}')
    return Response(OBJ[path])

@app.delete("/storage/v1/object/{bucket}")
async def delete(bucket: str, req: Request):
    auth(req)
    for p in json.loads(await req.body())["prefixes"]: OBJ.pop(p, None)
    return []

@app.get("/_debug/keys")
def keys(): return {k: len(v) for k, v in OBJ.items()}
