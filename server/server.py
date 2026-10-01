import argparse, asyncio, json, logging, os, ssl, uuid
from pathlib import Path
import bcrypt
import websockets

BASE = Path(__file__).resolve().parents[1]
CONFIG = BASE / "config"
CONFIG.mkdir(exist_ok=True)
DB = CONFIG / "devices.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
DEVICES = {}
AGENTS = {}
CONTROLLERS = {}
SESSIONS = {}

def load_db():
    global DEVICES
    if DB.exists():
        try: DEVICES = json.loads(DB.read_text("utf-8"))
        except Exception: DEVICES = {}

def save_db():
    tmp = DB.with_suffix(".tmp")
    tmp.write_text(json.dumps(DEVICES, indent=2), encoding="utf-8")
    os.replace(tmp, DB)

async def send(ws, obj):
    if ws and not ws.closed:
        await ws.send(json.dumps(obj, separators=(",", ":")))

async def device_list():
    out=[]
    for did, rec in DEVICES.items():
        out.append({
            "device_id": did,
            "device_name": rec.get("device_name", did),
            "online": did in AGENTS
        })
    return out

async def broadcast_device_list():
    msg={"type":"device_list","devices":await device_list()}
    for item in list(CONTROLLERS.values()):
        try: await send(item["ws"], msg)
        except Exception: pass

async def close_session(sid, notify=True):
    s=SESSIONS.pop(sid, None)
    if not s: return
    try: await send(s["agent"], {"type":"controller_close","session_id":sid})
    except Exception: pass
    if notify:
        try: await send(s["controller"], {"type":"session_closed","session_id":sid})
        except Exception: pass

async def handler(ws):
    role=None; did=None; cid=None; owned=set()
    try:
        raw=await asyncio.wait_for(ws.recv(),15)
        hello=json.loads(raw)
        typ=hello.get("type")

        if typ=="agent_login":
            did=str(hello.get("device_id","")).strip()
            name=str(hello.get("device_name",did)).strip()[:100]
            ph=str(hello.get("password_hash","")).strip()
            if not did or not ph:
                await send(ws,{"type":"auth_failed","message":"Missing device credentials"})
                return
            old=DEVICES.get(did)
            if old and old.get("password_hash") != ph:
                await send(ws,{"type":"auth_failed","message":"Device credentials do not match server record"})
                return
            DEVICES[did]={"device_name":name,"password_hash":ph}
            save_db()
            AGENTS[did]=ws; role="agent"
            await send(ws,{"type":"agent_auth_ok","device_id":did})
            await broadcast_device_list()
            logging.info("Agent online: %s",did)

            async for raw in ws:
                try: msg=json.loads(raw)
                except Exception: continue
                if msg.get("type")=="screen":
                    sid=msg.get("session_id")
                    s=SESSIONS.get(sid)
                    if s and s["agent"] is ws and s["target_id"]==did:
                        await send(s["controller"],msg)
                elif msg.get("type")=="agent_status":
                    pass

        elif typ=="controller_login":
            did=str(hello.get("device_id","")).strip()
            ph=str(hello.get("password_hash","")).strip()
            rec=DEVICES.get(did)
            if not rec or rec.get("password_hash")!=ph:
                await send(ws,{"type":"auth_failed","message":"Invalid device ID or password"})
                return
            cid="C-"+uuid.uuid4().hex
            CONTROLLERS[cid]={"ws":ws,"device_id":did}
            role="controller"
            await send(ws,{"type":"controller_auth_ok","device_id":did})
            await send(ws,{"type":"device_list","devices":await device_list()})
            logging.info("Controller online: %s",did)

            async for raw in ws:
                try: msg=json.loads(raw)
                except Exception: continue
                mt=msg.get("type")
                if mt=="list_devices":
                    await send(ws,{"type":"device_list","devices":await device_list()})
                elif mt=="open_session":
                    sid=str(msg.get("session_id","")).strip()
                    target=str(msg.get("target_id","")).strip()
                    mode=msg.get("mode","view")
                    if not sid or not target or target not in AGENTS:
                        await send(ws,{"type":"session_error","session_id":sid,"message":"Target is offline or unknown"})
                        continue
                    if sid in SESSIONS:
                        await send(ws,{"type":"session_error","session_id":sid,"message":"Session ID already exists"})
                        continue
                    SESSIONS[sid]={
                        "controller":ws,"controller_id":cid,
                        "controller_device":did,"agent":AGENTS[target],
                        "target_id":target,"mode":mode
                    }
                    owned.add(sid)
                    await send(AGENTS[target],{
                        "type":"controller_open","session_id":sid,
                        "controller_id":did,"mode":mode
                    })
                    await send(ws,{"type":"session_opened","session_id":sid,"target_id":target,"mode":mode})
                elif mt=="close_session":
                    sid=msg.get("session_id")
                    if sid in owned:
                        await close_session(sid)
                        owned.discard(sid)
                elif mt=="input":
                    sid=msg.get("session_id")
                    s=SESSIONS.get(sid)
                    if s and s["controller"] is ws:
                        await send(s["agent"],msg)
                elif mt=="clipboard_set":
                    sid=msg.get("session_id")
                    s=SESSIONS.get(sid)
                    if s and s["controller"] is ws:
                        await send(s["agent"],msg)
        else:
            await send(ws,{"type":"error","message":"Unknown handshake"})
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception:
        logging.exception("Connection error")
    finally:
        for sid,s in list(SESSIONS.items()):
            if (role=="agent" and s["agent"] is ws) or (role=="controller" and s["controller"] is ws):
                await close_session(sid, notify=False)
        if role=="agent" and did and AGENTS.get(did) is ws:
            AGENTS.pop(did,None)
            await broadcast_device_list()
            logging.info("Agent offline: %s",did)
        if role=="controller" and cid:
            CONTROLLERS.pop(cid,None)
            logging.info("Controller offline: %s",did)

def tls_context(cert,key):
    c=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    c.load_cert_chain(cert,key)
    return c

async def main(host,port,cert,key):
    load_db()
    CONFIG.mkdir(exist_ok=True)
    if not Path(cert).exists() or not Path(key).exists():
        raise SystemExit("TLS certificate missing. Run tools\\make_cert.bat first.")
    ctx=tls_context(cert,key)
    logging.info("RemoteDesk FINAL server listening on %s:%s TLS=ON",host,port)
    async with websockets.serve(handler,host,port,ssl=ctx,max_size=20*1024*1024,ping_interval=20,ping_timeout=20):
        await asyncio.Future()

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--host",default="0.0.0.0")
    ap.add_argument("--port",type=int,default=8765)
    ap.add_argument("--cert",default=str(CONFIG/"server.crt"))
    ap.add_argument("--key",default=str(CONFIG/"server.key"))
    a=ap.parse_args()
    asyncio.run(main(a.host,a.port,a.cert,a.key))
