import asyncio,base64,json,os,ssl,threading,time,uuid,socket
from io import BytesIO
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
import websockets,mss,pyautogui,pyperclip,bcrypt
from PIL import Image,ImageTk

APP=Path(os.environ.get("APPDATA",Path.home()))/"RemoteDesk"
APP.mkdir(parents=True,exist_ok=True)
CFG_PATH=APP/"client.json"

def load():
    if CFG_PATH.exists():
        return json.loads(CFG_PATH.read_text("utf-8"))
    return {}

def save(c):
    CFG_PATH.write_text(json.dumps(c,indent=2),encoding="utf-8")

class ClientApp:
    def __init__(self,root):
        self.root=root; self.root.title("RemoteDesk"); self.root.geometry("1100x720")
        self.cfg=load(); self.loop=asyncio.new_event_loop()
        self.ws=None; self.sessions={}; self.tabs={}; self.devices=[]
        self.make_ui()
        if not self.cfg.get("device_id"):
            self.setup_device()
        threading.Thread(target=self.net_thread,daemon=True).start()
        self.root.protocol("WM_DELETE_WINDOW",self.close)

    def make_ui(self):
        top=ttk.Frame(self.root,padding=10); top.pack(fill="x")
        self.info=ttk.Label(top,text="RemoteDesk"); self.info.pack(side="left")
        self.status=ttk.Label(top,text="Offline"); self.status.pack(side="right")
        main=ttk.Panedwindow(self.root,orient="horizontal"); main.pack(fill="both",expand=True,padx=10,pady=5)
        left=ttk.Frame(main,padding=5); right=ttk.Frame(main,padding=5)
        main.add(left,weight=1); main.add(right,weight=3)
        ttk.Label(left,text="Devices").pack(anchor="w")
        self.list=tk.Listbox(left); self.list.pack(fill="both",expand=True,pady=5)
        b=ttk.Frame(left); b.pack(fill="x")
        ttk.Button(b,text="Refresh",command=self.refresh).pack(side="left")
        ttk.Button(b,text="View",command=lambda:self.open("view")).pack(side="left",padx=3)
        ttk.Button(b,text="Control",command=lambda:self.open("control")).pack(side="left")
        self.tabs_ui=ttk.Notebook(right); self.tabs_ui.pack(fill="both",expand=True)
        logf=ttk.LabelFrame(self.root,text="Status",padding=4); logf.pack(fill="x",padx=10,pady=(0,10))
        self.log=tk.Text(logf,height=5); self.log.pack(fill="x")

    def setup_device(self):
        w=tk.Toplevel(self.root); w.title("RemoteDesk - Device Setup"); w.geometry("420x300"); w.grab_set()
        name=tk.StringVar(value=socket.gethostname()); pw=tk.StringVar(); pw2=tk.StringVar()
        ttk.Label(w,text="Device name").pack(anchor="w",padx=20,pady=(20,4)); ttk.Entry(w,textvariable=name).pack(fill="x",padx=20)
        ttk.Label(w,text="Permanent password (8+ characters)").pack(anchor="w",padx=20,pady=(12,4)); ttk.Entry(w,textvariable=pw,show="*").pack(fill="x",padx=20)
        ttk.Label(w,text="Confirm password").pack(anchor="w",padx=20,pady=(12,4)); ttk.Entry(w,textvariable=pw2,show="*").pack(fill="x",padx=20)
        def go():
            if len(pw.get())<8 or pw.get()!=pw2.get(): messagebox.showerror("RemoteDesk","Passwords must match and be 8+ characters.",parent=w); return
            self.cfg={"server_host":"182.178.213.210","server_port":8765,"tls":True,
                      "verify_server_certificate":False,"device_id":"RD-"+uuid.uuid4().hex[:12].upper(),
                      "device_name":name.get().strip() or socket.gethostname(),
                      "password_hash":bcrypt.hashpw(pw.get().encode(),bcrypt.gensalt()).decode()}
            save(self.cfg); w.destroy(); self.refresh_header()
        ttk.Button(w,text="Create Device",command=go).pack(pady=20)
        w.wait_window()

    def refresh_header(self):
        self.info.config(text=f"{self.cfg.get('device_name')} | {self.cfg.get('device_id')}")

    def sslctx(self):
        c=ssl.create_default_context()
        if not self.cfg.get("verify_server_certificate",False):
            c.check_hostname=False; c.verify_mode=ssl.CERT_NONE
        return c

    def net_thread(self):
        asyncio.set_event_loop(self.loop)
        self.loop.create_task(self.connect())
        self.loop.run_forever()

    async def connect(self):
        while True:
            try:
                uri=f"wss://{self.cfg['server_host']}:{self.cfg['server_port']}"
                self.set_status("Connecting...")
                async with websockets.connect(uri,ssl=self.sslctx(),max_size=20*1024*1024) as ws:
                    self.ws=ws
                    hello={"type":"agent_login","device_id":self.cfg["device_id"],"device_name":self.cfg["device_name"],"password_hash":self.cfg["password_hash"]}
                    await ws.send(json.dumps(hello)); await ws.recv()  # agent auth
                    # Controller uses a separate connection so Agent remains stable.
                    asyncio.create_task(self.controller_connection())
                    self.set_status("Agent online")
                    async for raw in ws:
                        msg=json.loads(raw); await self.agent_message(msg)
            except Exception as e:
                self.logmsg("Connection: "+str(e))
                self.set_status("Offline - retrying")
                await asyncio.sleep(4)

    async def agent_message(self,m):
        if m.get("type")=="controller_open":
            sid=m["session_id"]; mode=m.get("mode","view")
            asyncio.create_task(self.stream(sid,mode))
        elif m.get("type")=="controller_close":
            pass
        elif m.get("type")=="input":
            if m.get("action")=="move": pyautogui.moveTo(int(m["x"]),int(m["y"]))
            elif m.get("action")=="click": pyautogui.click(int(m["x"]),int(m["y"]),button=m.get("button","left"))
            elif m.get("action")=="key": pyautogui.press(m.get("key",""))
            elif m.get("action")=="write": pyautogui.write(m.get("text",""))

    async def stream(self,sid,mode):
        while self.ws:
            try:
                with mss.mss() as sct:
                    mon=sct.monitors[0]; shot=sct.grab(mon)
                    img=Image.frombytes("RGB",shot.size,shot.rgb); buf=BytesIO(); img.save(buf,"JPEG",quality=60,optimize=True)
                    await self.ws.send(json.dumps({"type":"screen","session_id":sid,"data":base64.b64encode(buf.getvalue()).decode()}))
                await asyncio.sleep(.12)
            except Exception: return

    async def controller_connection(self):
        try:
            uri=f"wss://{self.cfg['server_host']}:{self.cfg['server_port']}"
            async with websockets.connect(uri,ssl=self.sslctx(),max_size=20*1024*1024) as ws:
                self.cws=ws
                await ws.send(json.dumps({"type":"controller_login","device_id":self.cfg["device_id"],"password_hash":self.cfg["password_hash"]}))
                async for raw in ws:
                    m=json.loads(raw); typ=m.get("type")
                    if typ=="controller_auth_ok": self.set_status("Agent + Controller online")
                    elif typ=="device_list": self.update_devices(m.get("devices",[]))
                    elif typ=="screen": self.show_screen(m.get("session_id"),m.get("data"))
        except Exception as e: self.logmsg("Controller: "+str(e))

    def refresh(self):
        if getattr(self,"cws",None): asyncio.run_coroutine_threadsafe(self.cws.send(json.dumps({"type":"list_devices"})),self.loop)

    def update_devices(self,ds):
        self.devices=ds
        self.root.after(0,lambda:self._update_list())
    def _update_list(self):
        self.list.delete(0,"end")
        for d in self.devices:
            if d["device_id"]!=self.cfg["device_id"]:
                self.list.insert("end",f'{d["device_name"]} | {d["device_id"]} | {"ONLINE" if d["online"] else "OFFLINE"}')

    def open(self,mode):
        i=self.list.curselection()
        if not i: messagebox.showwarning("RemoteDesk","Select an online device."); return
        d=self.devices[i[0]]
        if not d["online"]: messagebox.showwarning("RemoteDesk","Device is offline."); return
        sid=uuid.uuid4().hex; self.sessions[sid]={"mode":mode,"target":d["device_id"]}
        asyncio.run_coroutine_threadsafe(self.cws.send(json.dumps({"type":"open_session","session_id":sid,"target_id":d["device_id"],"mode":mode})),self.loop)
        self.make_tab(sid,d["device_name"],mode)

    def make_tab(self,sid,name,mode):
        f=ttk.Frame(self.tabs_ui); canvas=tk.Canvas(f,bg="black"); canvas.pack(fill="both",expand=True)
        canvas.bind("<Button-1>",lambda e:self.input(sid,"click",e)); canvas.bind("<Button-3>",lambda e:self.input(sid,"rclick",e))
        self.tabs[sid]={"canvas":canvas,"photo":None,"mode":mode}
        self.tabs_ui.add(f,text=name[:20]); self.tabs_ui.select(f)

    def show_screen(self,sid,data):
        t=self.tabs.get(sid)
        if not t: return
        try:
            img=Image.open(BytesIO(base64.b64decode(data)))
            cw=max(200,t["canvas"].winfo_width()); ch=max(150,t["canvas"].winfo_height())
            # Preserve aspect ratio and map displayed coordinates later.
            img.thumbnail((cw,ch))
            ph=ImageTk.PhotoImage(img); t["photo"]=ph
            t["canvas"].delete("all"); t["canvas"].create_image(0,0,image=ph,anchor="nw")
        except Exception as e: self.logmsg("Screen: "+str(e))

    def input(self,sid,action,e):
        t=self.tabs.get(sid)
        if not t or t["mode"]!="control" or not getattr(self,"cws",None): return
        act="click" if action in ("click","rclick") else "move"
        btn="right" if action=="rclick" else "left"
        asyncio.run_coroutine_threadsafe(self.cws.send(json.dumps({"type":"input","session_id":sid,"action":act,"x":e.x,"y":e.y,"button":btn})),self.loop)

    def set_status(self,s): self.root.after(0,lambda:self.status.config(text=s))
    def logmsg(self,s): self.root.after(0,lambda:(self.log.insert("end",time.strftime("%H:%M:%S")+" "+s+"\n"),self.log.see("end")))
    def close(self): self.root.destroy()

if __name__=="__main__":
    r=tk.Tk(); a=ClientApp(r); a.refresh_header(); r.mainloop()
