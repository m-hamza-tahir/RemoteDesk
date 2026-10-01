import asyncio
import base64
import json
import os
import ssl
import threading
import time
import uuid
import socket
from io import BytesIO
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

import websockets
import mss
import pyautogui
import pyperclip
import bcrypt
from PIL import Image, ImageTk


APP = Path(os.environ.get("APPDATA", Path.home())) / "RemoteDesk"
APP.mkdir(parents=True, exist_ok=True)

CFG_PATH = APP / "client.json"

DEFAULT_SERVER_HOST = "182.178.213.210"
DEFAULT_SERVER_PORT = 8765


def load():
    if CFG_PATH.exists():
        try:
            return json.loads(CFG_PATH.read_text("utf-8"))
        except Exception:
            return {}
    return {}


def save(c):
    CFG_PATH.write_text(
        json.dumps(c, indent=2),
        encoding="utf-8"
    )


class ClientApp:
    def __init__(self, root):
        self.root = root
        self.root.title("RemoteDesk")
        self.root.geometry("1100x720")

        self.cfg = load()

        # Existing configuration
        if "server_host" not in self.cfg:
            self.cfg["server_host"] = DEFAULT_SERVER_HOST

        if "server_port" not in self.cfg:
            self.cfg["server_port"] = DEFAULT_SERVER_PORT

        if "tls" not in self.cfg:
            self.cfg["tls"] = True

        if "verify_server_certificate" not in self.cfg:
            self.cfg["verify_server_certificate"] = False

        save(self.cfg)

        self.loop = asyncio.new_event_loop()

        self.ws = None
        self.cws = None
        self.sessions = {}
        self.tabs = {}
        self.devices = []

        self.make_ui()

        if not self.cfg.get("device_id"):
            self.setup_device()

        self.refresh_header()

        threading.Thread(
            target=self.net_thread,
            daemon=True
        ).start()

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.close
        )

    # ---------------------------------------------------------
    # UI
    # ---------------------------------------------------------

    def make_ui(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        self.info = ttk.Label(
            top,
            text="RemoteDesk"
        )
        self.info.pack(side="left")

        self.status = ttk.Label(
            top,
            text="Offline"
        )
        self.status.pack(side="right")

        main = ttk.Panedwindow(
            self.root,
            orient="horizontal"
        )
        main.pack(
            fill="both",
            expand=True,
            padx=10,
            pady=5
        )

        left = ttk.Frame(main, padding=5)
        right = ttk.Frame(main, padding=5)

        main.add(left, weight=1)
        main.add(right, weight=3)

        ttk.Label(
            left,
            text="Devices"
        ).pack(anchor="w")

        self.list = tk.Listbox(left)
        self.list.pack(
            fill="both",
            expand=True,
            pady=5
        )

        b = ttk.Frame(left)
        b.pack(fill="x")

        ttk.Button(
            b,
            text="Refresh",
            command=self.refresh
        ).pack(side="left")

        ttk.Button(
            b,
            text="View",
            command=lambda: self.open("view")
        ).pack(
            side="left",
            padx=3
        )

        ttk.Button(
            b,
            text="Control",
            command=lambda: self.open("control")
        ).pack(side="left")

        ttk.Button(
            b,
            text="Settings",
            command=self.settings
        ).pack(
            side="left",
            padx=3
        )

        self.tabs_ui = ttk.Notebook(right)
        self.tabs_ui.pack(
            fill="both",
            expand=True
        )

        logf = ttk.LabelFrame(
            self.root,
            text="Status",
            padding=4
        )
        logf.pack(
            fill="x",
            padx=10,
            pady=(0, 10)
        )

        self.log = tk.Text(
            logf,
            height=5
        )
        self.log.pack(fill="x")

    # ---------------------------------------------------------
    # Device setup
    # ---------------------------------------------------------

    def setup_device(self):
        w = tk.Toplevel(self.root)
        w.title("RemoteDesk - Device Setup")
        w.geometry("450x360")
        w.grab_set()

        name = tk.StringVar(
            value=socket.gethostname()
        )

        server = tk.StringVar(
            value=self.cfg.get(
                "server_host",
                DEFAULT_SERVER_HOST
            )
        )

        port = tk.StringVar(
            value=str(
                self.cfg.get(
                    "server_port",
                    DEFAULT_SERVER_PORT
                )
            )
        )

        pw = tk.StringVar()
        pw2 = tk.StringVar()

        ttk.Label(
            w,
            text="Server address"
        ).pack(
            anchor="w",
            padx=20,
            pady=(20, 4)
        )

        ttk.Entry(
            w,
            textvariable=server
        ).pack(
            fill="x",
            padx=20
        )

        ttk.Label(
            w,
            text="Server port"
        ).pack(
            anchor="w",
            padx=20,
            pady=(10, 4)
        )

        ttk.Entry(
            w,
            textvariable=port
        ).pack(
            fill="x",
            padx=20
        )

        ttk.Label(
            w,
            text="Device name"
        ).pack(
            anchor="w",
            padx=20,
            pady=(10, 4)
        )

        ttk.Entry(
            w,
            textvariable=name
        ).pack(
            fill="x",
            padx=20
        )

        ttk.Label(
            w,
            text="Permanent password (8+ characters)"
        ).pack(
            anchor="w",
            padx=20,
            pady=(10, 4)
        )

        ttk.Entry(
            w,
            textvariable=pw,
            show="*"
        ).pack(
            fill="x",
            padx=20
        )

        ttk.Label(
            w,
            text="Confirm password"
        ).pack(
            anchor="w",
            padx=20,
            pady=(10, 4)
        )

        ttk.Entry(
            w,
            textvariable=pw2,
            show="*"
        ).pack(
            fill="x",
            padx=20
        )

        def go():
            host = server.get().strip()

            if not host:
                messagebox.showerror(
                    "RemoteDesk",
                    "Server address is required.",
                    parent=w
                )
                return

            try:
                server_port = int(port.get().strip())

                if not 1 <= server_port <= 65535:
                    raise ValueError
            except ValueError:
                messagebox.showerror(
                    "RemoteDesk",
                    "Server port must be between 1 and 65535.",
                    parent=w
                )
                return

            if (
                len(pw.get()) < 8
                or pw.get() != pw2.get()
            ):
                messagebox.showerror(
                    "RemoteDesk",
                    "Passwords must match and be 8+ characters.",
                    parent=w
                )
                return

            self.cfg = {
                "server_host": host,
                "server_port": server_port,
                "tls": True,
                "verify_server_certificate": False,
                "device_id":
                    "RD-" +
                    uuid.uuid4().hex[:12].upper(),
                "device_name":
                    name.get().strip()
                    or socket.gethostname(),
                "password_hash":
                    bcrypt.hashpw(
                        pw.get().encode(),
                        bcrypt.gensalt()
                    ).decode()
            }

            save(self.cfg)

            w.destroy()
            self.refresh_header()

        ttk.Button(
            w,
            text="Create Device",
            command=go
        ).pack(pady=18)

        w.wait_window()

    # ---------------------------------------------------------
    # Settings
    # ---------------------------------------------------------

    def settings(self):
        w = tk.Toplevel(self.root)
        w.title("RemoteDesk - Server Settings")
        w.geometry("430x260")
        w.grab_set()

        host = tk.StringVar(
            value=self.cfg.get(
                "server_host",
                DEFAULT_SERVER_HOST
            )
        )

        port = tk.StringVar(
            value=str(
                self.cfg.get(
                    "server_port",
                    DEFAULT_SERVER_PORT
                )
            )
        )

        ttk.Label(
            w,
            text="Server address / IP / hostname"
        ).pack(
            anchor="w",
            padx=20,
            pady=(20, 5)
        )

        ttk.Entry(
            w,
            textvariable=host
        ).pack(
            fill="x",
            padx=20
        )

        ttk.Label(
            w,
            text="Server port"
        ).pack(
            anchor="w",
            padx=20,
            pady=(12, 5)
        )

        ttk.Entry(
            w,
            textvariable=port
        ).pack(
            fill="x",
            padx=20
        )

        ttk.Label(
            w,
            text=(
                "Examples:\n"
                "182.178.213.210\n"
                "127.0.0.1\n"
                "192.168.1.3"
            )
        ).pack(
            anchor="w",
            padx=20,
            pady=10
        )

        def save_settings():
            new_host = host.get().strip()

            if not new_host:
                messagebox.showerror(
                    "RemoteDesk",
                    "Server address is required.",
                    parent=w
                )
                return

            try:
                new_port = int(port.get().strip())

                if not 1 <= new_port <= 65535:
                    raise ValueError
            except ValueError:
                messagebox.showerror(
                    "RemoteDesk",
                    "Invalid server port.",
                    parent=w
                )
                return

            self.cfg["server_host"] = new_host
            self.cfg["server_port"] = new_port

            save(self.cfg)

            messagebox.showinfo(
                "RemoteDesk",
                "Server settings saved.\n\n"
                "Restart RemoteDesk to reconnect "
                "using the new server.",
                parent=w
            )

            w.destroy()

        ttk.Button(
            w,
            text="Save",
            command=save_settings
        ).pack(pady=8)

        w.wait_window()

    # ---------------------------------------------------------
    # SSL
    # ---------------------------------------------------------

    def sslctx(self):
        c = ssl.create_default_context()

        if not self.cfg.get(
            "verify_server_certificate",
            False
        ):
            c.check_hostname = False
            c.verify_mode = ssl.CERT_NONE

        return c

    # ---------------------------------------------------------
    # Network
    # ---------------------------------------------------------

    def net_thread(self):
        asyncio.set_event_loop(self.loop)

        self.loop.create_task(
            self.connect()
        )

        self.loop.run_forever()

    async def connect(self):
        while True:
            try:
                host = self.cfg.get(
                    "server_host",
                    DEFAULT_SERVER_HOST
                )

                port = int(
                    self.cfg.get(
                        "server_port",
                        DEFAULT_SERVER_PORT
                    )
                )

                uri = f"wss://{host}:{port}"

                self.set_status(
                    f"Connecting to {host}:{port}..."
                )

                async with websockets.connect(
                    uri,
                    ssl=self.sslctx(),
                    max_size=20 * 1024 * 1024
                ) as ws:

                    self.ws = ws

                    hello = {
                        "type": "agent_login",
                        "device_id":
                            self.cfg["device_id"],
                        "device_name":
                            self.cfg["device_name"],
                        "password_hash":
                            self.cfg["password_hash"]
                    }

                    await ws.send(
                        json.dumps(hello)
                    )

                    await ws.recv()

                    asyncio.create_task(
                        self.controller_connection()
                    )

                    self.set_status(
                        "Agent online"
                    )

                    async for raw in ws:
                        msg = json.loads(raw)
                        await self.agent_message(msg)

            except Exception as e:
                self.logmsg(
                    "Connection: " + str(e)
                )

                self.set_status(
                    "Offline - retrying"
                )

                await asyncio.sleep(4)

    # ---------------------------------------------------------
    # Agent messages
    # ---------------------------------------------------------

    async def agent_message(self, m):
        if m.get("type") == "controller_open":

            sid = m["session_id"]
            mode = m.get("mode", "view")

            asyncio.create_task(
                self.stream(sid, mode)
            )

        elif m.get("type") == "controller_close":
            pass

        elif m.get("type") == "input":

            action = m.get("action")

            if action == "move":
                pyautogui.moveTo(
                    int(m["x"]),
                    int(m["y"])
                )

            elif action == "click":
                pyautogui.click(
                    int(m["x"]),
                    int(m["y"]),
                    button=m.get(
                        "button",
                        "left"
                    )
                )

            elif action == "key":
                pyautogui.press(
                    m.get("key", "")
                )

            elif action == "write":
                pyautogui.write(
                    m.get("text", "")
                )

    # ---------------------------------------------------------
    # Screen streaming
    # ---------------------------------------------------------

    async def stream(self, sid, mode):
        while self.ws:
            try:
                with mss.mss() as sct:

                    mon = sct.monitors[0]

                    shot = sct.grab(mon)

                    img = Image.frombytes(
                        "RGB",
                        shot.size,
                        shot.rgb
                    )

                    buf = BytesIO()

                    img.save(
                        buf,
                        "JPEG",
                        quality=60,
                        optimize=True
                    )

                    await self.ws.send(
                        json.dumps({
                            "type": "screen",
                            "session_id": sid,
                            "data":
                                base64.b64encode(
                                    buf.getvalue()
                                ).decode()
                        })
                    )

                await asyncio.sleep(0.12)

            except Exception:
                return

    # ---------------------------------------------------------
    # Controller connection
    # ---------------------------------------------------------

    async def controller_connection(self):

        try:
            host = self.cfg.get(
                "server_host",
                DEFAULT_SERVER_HOST
            )

            port = int(
                self.cfg.get(
                    "server_port",
                    DEFAULT_SERVER_PORT
                )
            )

            uri = f"wss://{host}:{port}"

            async with websockets.connect(
                uri,
                ssl=self.sslctx(),
                max_size=20 * 1024 * 1024
            ) as ws:

                self.cws = ws

                await ws.send(
                    json.dumps({
                        "type": "controller_login",
                        "device_id":
                            self.cfg["device_id"],
                        "password_hash":
                            self.cfg["password_hash"]
                    })
                )

                async for raw in ws:

                    m = json.loads(raw)

                    typ = m.get("type")

                    if typ == "controller_auth_ok":
                        self.set_status(
                            "Agent + Controller online"
                        )

                    elif typ == "device_list":
                        self.update_devices(
                            m.get("devices", [])
                        )

                    elif typ == "screen":
                        self.show_screen(
                            m.get("session_id"),
                            m.get("data")
                        )

        except Exception as e:
            self.logmsg(
                "Controller: " + str(e)
            )

    # ---------------------------------------------------------
    # Devices
    # ---------------------------------------------------------

    def refresh(self):
        if getattr(self, "cws", None):
            asyncio.run_coroutine_threadsafe(
                self.cws.send(
                    json.dumps({
                        "type": "list_devices"
                    })
                ),
                self.loop
            )

    def update_devices(self, ds):
        self.devices = ds

        self.root.after(
            0,
            self._update_list
        )

    def _update_list(self):
        self.list.delete(0, "end")

        for d in self.devices:

            if d["device_id"] != self.cfg["device_id"]:

                self.list.insert(
                    "end",
                    f'{d["device_name"]} | '
                    f'{d["device_id"]} | '
                    f'{"ONLINE" if d["online"] else "OFFLINE"}'
                )

    # ---------------------------------------------------------
    # Open remote session
    # ---------------------------------------------------------

    def open(self, mode):

        i = self.list.curselection()

        if not i:
            messagebox.showwarning(
                "RemoteDesk",
                "Select an online device."
            )
            return

        d = self.devices[i[0]]

        if not d["online"]:
            messagebox.showwarning(
                "RemoteDesk",
                "Device is offline."
            )
            return

        sid = uuid.uuid4().hex

        self.sessions[sid] = {
            "mode": mode,
            "target": d["device_id"]
        }

        asyncio.run_coroutine_threadsafe(
            self.cws.send(
                json.dumps({
                    "type": "open_session",
                    "session_id": sid,
                    "target_id": d["device_id"],
                    "mode": mode
                })
            ),
            self.loop
        )

        self.make_tab(
            sid,
            d["device_name"],
            mode
        )

    # ---------------------------------------------------------
    # Remote screen tab
    # ---------------------------------------------------------

    def make_tab(self, sid, name, mode):

        f = ttk.Frame(self.tabs_ui)

        canvas = tk.Canvas(
            f,
            bg="black"
        )

        canvas.pack(
            fill="both",
            expand=True
        )

        canvas.bind(
            "<Button-1>",
            lambda e:
                self.input(
                    sid,
                    "click",
                    e
                )
        )

        canvas.bind(
            "<Button-3>",
            lambda e:
                self.input(
                    sid,
                    "rclick",
                    e
                )
        )

        self.tabs[sid] = {
            "canvas": canvas,
            "photo": None,
            "mode": mode
        }

        self.tabs_ui.add(
            f,
            text=name[:20]
        )

        self.tabs_ui.select(f)

    # ---------------------------------------------------------
    # Screen display
    # ---------------------------------------------------------

    def show_screen(self, sid, data):

        t = self.tabs.get(sid)

        if not t:
            return

        try:
            img = Image.open(
                BytesIO(
                    base64.b64decode(data)
                )
            )

            cw = max(
                200,
                t["canvas"].winfo_width()
            )

            ch = max(
                150,
                t["canvas"].winfo_height()
            )

            img.thumbnail(
                (cw, ch)
            )

            ph = ImageTk.PhotoImage(img)

            t["photo"] = ph

            t["canvas"].delete("all")

            t["canvas"].create_image(
                0,
                0,
                image=ph,
                anchor="nw"
            )

        except Exception as e:
            self.logmsg(
                "Screen: " + str(e)
            )

    # ---------------------------------------------------------
    # Input
    # ---------------------------------------------------------

    def input(self, sid, action, e):

        t = self.tabs.get(sid)

        if (
            not t
            or t["mode"] != "control"
            or not getattr(self, "cws", None)
        ):
            return

        act = (
            "click"
            if action in ("click", "rclick")
            else "move"
        )

        btn = (
            "right"
            if action == "rclick"
            else "left"
        )

        asyncio.run_coroutine_threadsafe(
            self.cws.send(
                json.dumps({
                    "type": "input",
                    "session_id": sid,
                    "action": act,
                    "x": e.x,
                    "y": e.y,
                    "button": btn
                })
            ),
            self.loop
        )

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------

    def refresh_header(self):
        if self.cfg.get("device_id"):
            self.info.config(
                text=(
                    f'{self.cfg.get("device_name")} | '
                    f'{self.cfg.get("device_id")} | '
                    f'{self.cfg.get("server_host")}:'
                    f'{self.cfg.get("server_port")}'
                )
            )

    def set_status(self, s):
        self.root.after(
            0,
            lambda: self.status.config(
                text=s
            )
        )

    def logmsg(self, s):
        self.root.after(
            0,
            lambda: (
                self.log.insert(
                    "end",
                    time.strftime("%H:%M:%S")
                    + " "
                    + s
                    + "\n"
                ),
                self.log.see("end")
            )
        )

    def close(self):
        try:
            self.loop.call_soon_threadsafe(
                self.loop.stop
            )
        except Exception:
            pass

        self.root.destroy()


if __name__ == "__main__":
    r = tk.Tk()

    a = ClientApp(r)

    a.refresh_header()

    r.mainloop()
