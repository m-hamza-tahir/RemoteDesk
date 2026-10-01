import asyncio, base64, json, os, socket, ssl, threading, time, uuid
from io import BytesIO
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
import bcrypt, mss, pyautogui, websockets
from PIL import Image, ImageTk

APP = Path(os.environ.get("APPDATA", Path.home())) / "RemoteDesk"
APP.mkdir(parents=True, exist_ok=True)
CFG_PATH = APP / "client.json"
DEFAULT_SERVER_HOST, DEFAULT_SERVER_PORT = "182.178.213.210", 8765

def load():
    if CFG_PATH.exists():
        try: return json.loads(CFG_PATH.read_text("utf-8"))
        except Exception: return {}
    return {}

def save(c): CFG_PATH.write_text(json.dumps(c, indent=2), encoding="utf-8")

class ClientApp:
    def __init__(self, root):
        self.root=root; self.root.title("RemoteDesk"); self.root.geometry("1100x720"); self.cfg=load(); self.loop=asyncio.new_event_loop(); self.ws=None; self.cws=None; self.devices=[]; self.sessions={}; self.tabs={}
        self.make_ui()
        if not self.cfg.get("device_id"): self.setup_device()
        self.refresh_header(); threading.Thread(target=self.net_thread, daemon=True).start(); self.root.protocol("WM_DELETE_WINDOW", self.close)

    def make_ui(self):
        top=ttk.Frame(self.root,padding=10); top.pack(fill="x"); self.info=ttk.Label(top,text="RemoteDesk"); self.info.pack(side="left"); self.status=ttk.Label(top,text="Offline"); self.status.pack(side="right")
        main=ttk.Panedwindow(self.root,orient="horizontal"); main.pack(fill="both",expand=True,padx=10,pady=5); left=ttk.Frame(main,padding=5); right=ttk.Frame(main,padding=5); main.add(left,weight=1); main.add(right,weight=3)
        ttk.Label(left,text="Devices").pack(anchor="w"); self.list=tk.Listbox(left); self.list.pack(fill="both",expand=True,pady=5)
        b=ttk.Frame(left); b.pack(fill="x"); ttk.Button(b,text="Refresh",command=self.refresh).pack(side="left"); ttk.Button(b,text="View",command=lambda:self.open("view")).pack(side="left",padx=3); ttk.Button(b,text="Control",command=lambda:self.open("control")).pack(side="left"); ttk.Button(b,text="Settings",command=self.settings).pack(side="left",padx=3)
        self.tabs_ui=ttk.Notebook(right); self.tabs_ui.pack(fill="both",expand=True); lf=ttk.LabelFrame(self.root,text="Status",padding=4); lf.pack(fill="x",padx=10,pady=(0,10)); self.log=tk.Text(lf,height=6); self.log.pack(fill="x")

    def setup_device(self):
        w=tk.Toplevel(self.root); w.title("RemoteDesk - Device Setup"); w.geometry("460x430"); w.grab_set(); host=tk.StringVar(value=DEFAULT_SERVER_HOST); port=tk.StringVar(value=str(DEFAULT_SERVER_PORT)); name=tk.StringVar(value=socket.gethostname()); pw=tk.StringVar(); pw2=tk.StringVar()
        for label,var,show in [("Server address / IP",host,None),("Server port",port,None),("Device name",name,None),("Permanent password (8+ characters)",pw,"*"),("Confirm password",pw2,"*")]:
            ttk.Label(w,text=label).pack(anchor="w",padx=20,pady=(12,4)); ttk.Entry(w,textvariable=var,show=show).pack(fill="x",padx=20)
        def go():
            try:p=int(port.get())
            except: messagebox.showerror("RemoteDesk","Invalid server port.",parent=w); return
            if not host.get().strip() or not 1<=p<=65535 or len(pw.get())<8 or pw.get()!=pw2.get(): messagebox.showerror("RemoteDesk","Enter valid server settings and matching 8+ character password.",parent=w); return
            self.cfg={"server_host":host.get().strip(),"server_port":p,"verify_server_certificate":False,"device_id":"RD-"+uuid.uuid4().hex[:12].upper(),"device_name":name.get().strip() or socket.gethostname(),"password_hash":bcrypt.hashpw(pw.get().encode(),bcrypt.gensalt()).decode()}; save(self.cfg); w.destroy()
        ttk.Button(w,text="Create Device",command=go).pack(pady=22); w.wait_window()

    def settings(self):
        w=tk.Toplevel(self.root); w.title("RemoteDesk - Settings"); w.geometry("460x330"); w.grab_set(); host=tk.StringVar(value=self.cfg.get("server_host",DEFAULT_SERVER_HOST)); port=tk.StringVar(value=str(self.cfg.get("server_port",DEFAULT_SERVER_PORT))); name=tk.StringVar(value=self.cfg.get("device_name",socket.gethostname()))
        ttk.Label(w,text="Server address / IP").pack(anchor="w",padx=20,pady=(20,4)); ttk.Entry(w,textvariable=host).pack(fill="x",padx=20); ttk.Label(w,text="Server port").pack(anchor="w",padx=20,pady=(12,4)); ttk.Entry(w,textvariable=port).pack(fill="x",padx=20); ttk.Label(w,text="Device name").pack(anchor="w",padx=20,pady=(12,4)); ttk.Entry(w,textvariable=name).pack(fill="x",padx=20); ttk.Label(w,text="Local test: 127.0.0.1:8765").pack(anchor="w",padx=20,pady=15)
        def save_settings():
            try:p=int(port.get())
            except: messagebox.showerror("RemoteDesk","Invalid server port.",parent=w); return
            if not host.get().strip() or not 1<=p<=65535: messagebox.showerror("RemoteDesk","Enter a valid server address and port.",parent=w); return
            self.cfg["server_host"]=host.get().strip(); self.cfg["server_port"]=p; self.cfg["device_name"]=name.get().strip() or socket.gethostname(); save(self.cfg); self.refresh_header(); messagebox.showinfo("RemoteDesk","Saved. Restart RemoteDesk to apply.",parent=w); w.destroy()
        ttk.Button(w,text="Save",command=save_settings).pack()

    def refresh_header(self): self.info.config(text=f'{self.cfg.get("device_name","")} | {self.cfg.get("device_id","")} | {self.cfg.get("server_host","")}:{self.cfg.get("server_port","")}')
    def sslctx(self):
        c=ssl.create_default_context()
        if not self.cfg.get("verify_server_certificate",False): c.check_hostname=False; c.verify_mode=ssl.CERT_NONE
        return c
    def net_thread(self): asyncio.set_event_loop(self.loop); self.loop.create_task(self.connect()); self.loop.run_forever()

    async def connect(self):
        while True:
            try:
                uri=f'wss://{self.cfg["server_host"]}:{self.cfg["server_port"]}'; self.set_status("Connecting...")
                async with websockets.connect(uri,ssl=self.sslctx(),max_size=20*1024*1024) as ws:
                    self.ws=ws; await ws.send(json.dumps({"type":"agent_login","device_id":self.cfg["device_id"],"device_name":self.cfg["device_name"],"password_hash":self.cfg["password_hash"]})); auth=json.loads(await ws.recv())
                    if auth.get("type")!="agent_auth_ok": self.logmsg("Agent authentication failed"); await asyncio.sleep(4); continue
                    self.set_status("Agent online"); controller_task=asyncio.create_task(self.controller_connection())
                    try:
                        async for raw in ws:
                            try: await self.agent_message(json.loads(raw))
                            except Exception: continue
                    finally: controller_task.cancel()
            except Exception as e: self.logmsg("Connection: "+str(e)); self.set_status("Offline - retrying"); await asyncio.sleep(4)
            finally:self.ws=None; self.cws=None

    async def agent_message(self,m):
        if m.get("type")=="controller_open": asyncio.create_task(self.stream(m.get("session_id"),m.get("mode","view")))
        elif m.get("type")=="input":
            try:
                a=m.get("action")
                if a=="move":pyautogui.moveTo(int(m["x"]),int(m["y"]))
                elif a=="click":pyautogui.click(int(m["x"]),int(m["y"]),button=m.get("button","left"))
                elif a=="key":pyautogui.press(m.get("key",""))
                elif a=="write":pyautogui.write(m.get("text",""))
            except Exception as e:self.logmsg("Input error: "+str(e))

    async def stream(self,sid,mode):
        while self.ws:
            try:
                with mss.mss() as sct:
                    mon=sct.monitors[0]; shot=sct.grab(mon); img=Image.frombytes("RGB",shot.size,shot.rgb); buf=BytesIO(); img.save(buf,"JPEG",quality=60,optimize=True); await self.ws.send(json.dumps({"type":"screen","session_id":sid,"data":base64.b64encode(buf.getvalue()).decode()}))
                await asyncio.sleep(.12)
            except Exception:return

    async def controller_connection(self):
        try:
            uri=f'wss://{self.cfg["server_host"]}:{self.cfg["server_port"]}'
            async with websockets.connect(uri,ssl=self.sslctx(),max_size=20*1024*1024) as ws:
                self.cws=ws; await ws.send(json.dumps({"type":"controller_login","device_id":self.cfg["device_id"],"password_hash":self.cfg["password_hash"]}))
                async for raw in ws:
                    try:m=json.loads(raw)
                    except:continue
                    typ=m.get("type")
                    if typ=="controller_auth_ok":self.set_status("Agent + Controller online")
                    elif typ=="device_list":self.update_devices(m.get("devices",[]))
                    elif typ=="screen":self.show_screen(m.get("session_id"),m.get("data"))
                    elif typ=="session_opened":self.logmsg("Session opened: "+str(m.get("target_id","")))
                    elif typ=="session_error":self.logmsg("Session error: "+str(m.get("message","")))
        except asyncio.CancelledError:raise
        except Exception as e:self.logmsg("Controller: "+str(e))
        finally:self.cws=None

    def refresh(self):
        if not self.cws:self.logmsg("Controller connection is not ready."); return
        try:asyncio.run_coroutine_threadsafe(self.cws.send(json.dumps({"type":"list_devices"})),self.loop)
        except Exception as e:self.logmsg("Refresh error: "+str(e))

    def update_devices(self,ds):self.devices=list(ds); self.root.after(0,self._update_list)
    def _update_list(self):
        self.list.delete(0,"end")
        for d in self.devices:self.list.insert("end",f'{d.get("device_name",d.get("device_id","Unknown"))} | {d.get("device_id","")} | {"ONLINE" if d.get("online",False) else "OFFLINE"}')
        self.logmsg(f"Devices received: {len(self.devices)}")

    def open(self,mode):
        sel=self.list.curselection()
        if not sel:messagebox.showwarning("RemoteDesk","Select an online device.");return
        i=sel[0]
        if i>=len(self.devices):return
        d=self.devices[i]
        if not d.get("online",False):messagebox.showwarning("RemoteDesk","Device is offline.");return
        if not self.cws:messagebox.showwarning("RemoteDesk","Controller is not connected.");return
        sid=uuid.uuid4().hex; self.sessions[sid]={"mode":mode,"target":d["device_id"]}; asyncio.run_coroutine_threadsafe(self.cws.send(json.dumps({"type":"open_session","session_id":sid,"target_id":d["device_id"],"mode":mode})),self.loop); self.make_tab(sid,d.get("device_name",d["device_id"]),mode)

    def make_tab(self,sid,name,mode):
        f=ttk.Frame(self.tabs_ui); c=tk.Canvas(f,bg="black"); c.pack(fill="both",expand=True); self.tabs[sid]={"canvas":c,"photo":None,"mode":mode}; self.tabs_ui.add(f,text=name[:20]); self.tabs_ui.select(f)
    def show_screen(self,sid,data):
        t=self.tabs.get(sid)
        if not t or not data:return
        try:
            img=Image.open(BytesIO(base64.b64decode(data))); t["ow"],t["oh"]=img.width,img.height; cw=max(200,t["canvas"].winfo_width()); ch=max(150,t["canvas"].winfo_height()); img.thumbnail((cw,ch)); t["dw"],t["dh"]=img.width,img.height; p=ImageTk.PhotoImage(img); t["photo"]=p; t["canvas"].delete("all"); t["canvas"].create_image(0,0,image=p,anchor="nw")
        except Exception as e:self.logmsg("Screen: "+str(e))
    def set_status(self,s):self.root.after(0,lambda:self.status.config(text=s))
    def logmsg(self,s):self.root.after(0,lambda:self._log(s))
    def _log(self,s):self.log.insert("end",time.strftime("%H:%M:%S")+" "+str(s)+"\n");self.log.see("end")
    def close(self):
        try:
            if self.cws:asyncio.run_coroutine_threadsafe(self.cws.close(),self.loop)
            if self.ws:asyncio.run_coroutine_threadsafe(self.ws.close(),self.loop)
            self.loop.call_soon_threadsafe(self.loop.stop)
        except:pass
        self.root.destroy()

if __name__=="__main__":
    root=tk.Tk(); app=ClientApp(root); root.mainloop()
