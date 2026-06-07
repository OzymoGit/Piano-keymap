"""
test_win32msg.py
─────────────────────────────────────────────────────────────────
Uses ctypes to subclass the Tkinter HWND so that it directly captures
WM_KEYDOWN and WM_KEYUP events sent via PostMessage from background
threads/applications.
"""

import tkinter as tk
from datetime import datetime
import ctypes
from ctypes import wintypes

# Win32 definitions
GWL_WNDPROC = -4
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101

# Choose function prototypes based on 32/64-bit Python
if ctypes.sizeof(ctypes.c_void_p) == 8:
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_int64, wintypes.HWND, ctypes.c_uint, ctypes.c_uint64, ctypes.c_int64)
    SetWindowLong = ctypes.windll.user32.SetWindowLongPtrW
    SetWindowLong.restype = ctypes.c_void_p
    SetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    CallWindowProc = ctypes.windll.user32.CallWindowProcW
    CallWindowProc.restype = ctypes.c_int64
    CallWindowProc.argtypes = [ctypes.c_void_p, wintypes.HWND, ctypes.c_uint, ctypes.c_uint64, ctypes.c_int64]
else:
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_int32, wintypes.HWND, ctypes.c_uint, ctypes.c_uint32, ctypes.c_int32)
    SetWindowLong = ctypes.windll.user32.SetWindowLongW
    SetWindowLong.restype = ctypes.c_int32
    SetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int32]
    CallWindowProc = ctypes.windll.user32.CallWindowProcW
    CallWindowProc.restype = ctypes.c_int32
    CallWindowProc.argtypes = [ctypes.c_int32, wintypes.HWND, ctypes.c_uint, ctypes.c_uint32, ctypes.c_int32]

WINDOW_TITLE = "nanoMIDI Key Tester"

VK_NAMES = {
    0x08: "BACK",  0x09: "TAB",   0x0D: "ENTER", 0x10: "SHIFT",
    0x11: "CTRL",  0x12: "ALT",   0x1B: "ESC",   0x20: "SPACE",
    0x25: "LEFT",  0x26: "UP",    0x27: "RIGHT",  0x28: "DOWN",
    0xA0: "LSHIFT",0xA1: "RSHIFT",0xBD: "-",      0xBB: "=",
    0xDB: "[",     0xDD: "]",     0xDC: "\\",     0xBA: ";",
    0xDE: "'",     0xBC: ",",     0xBE: ".",      0xBF: "/",
}
for i in range(0x30, 0x3A):   # 0-9
    VK_NAMES[i] = chr(i)
for i in range(0x41, 0x5B):   # A-Z
    VK_NAMES[i] = chr(i)

def vk_name(vk):
    return VK_NAMES.get(vk, f"VK 0x{vk:02X}")

class KeyTester(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(WINDOW_TITLE)
        self.geometry("540x480")
        self.configure(bg="#1a1a2e")
        self.resizable(True, True)

        # ── header ──────────────────────────────────────────────
        hdr = tk.Label(
            self, text="🎹  nanoMIDI Key Tester",
            font=("Segoe UI", 14, "bold"),
            fg="#e0e0ff", bg="#1a1a2e"
        )
        hdr.pack(pady=(14, 0))

        hint = tk.Label(
            self,
            text=f'Set Target Window to  "{WINDOW_TITLE}"  in Settings tab\n'
                 'then play MIDI — keys will appear below even when unfocused.',
            font=("Segoe UI", 9),
            fg="#8888bb", bg="#1a1a2e", justify="center"
        )
        hint.pack(pady=(4, 10))

        # ── stats bar ───────────────────────────────────────────
        self.stats_var = tk.StringVar(value="Waiting for Win32 messages…")
        stats = tk.Label(
            self, textvariable=self.stats_var,
            font=("Consolas", 10), fg="#44ff88", bg="#111122"
        )
        stats.pack(fill="x", padx=10)

        # ── log box ─────────────────────────────────────────────
        frame = tk.Frame(self, bg="#1a1a2e")
        frame.pack(fill="both", expand=True, padx=10, pady=8)

        self.log = tk.Text(
            frame, font=("Consolas", 10),
            bg="#0d0d1a", fg="#ccccff",
            insertbackground="white",
            relief="flat", bd=0
        )
        sb = tk.Scrollbar(frame, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        self.log.tag_config("down",    foreground="#44ff88")
        self.log.tag_config("up",      foreground="#ff8844")
        self.log.tag_config("divider", foreground="#333355")

        # ── clear button ────────────────────────────────────────
        btn = tk.Button(
            self, text="Clear Log", command=self.clear,
            font=("Segoe UI", 9),
            bg="#2a2a4a", fg="#aaaadd",
            relief="flat", cursor="hand2"
        )
        btn.pack(pady=(0, 10))

        self.count_down = 0
        self.count_up   = 0

        self.append("─" * 60 + "\n", "divider")
        self.append("Subclassing Window Procedure…\n", "divider")

        # Begin window procedure hook
        self.update_idletasks()
        self.hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
        if not self.hwnd:
            self.hwnd = self.winfo_id()
        
        self.append(f"HWND: {self.hwnd} | Target title: \"{WINDOW_TITLE}\"\n", "divider")
        self.append("Ready. Open nanoMIDI, select target, and play notes.\n", "divider")
        self.append("─" * 60 + "\n", "divider")

        # Subclassing
        self.new_wndproc = WNDPROC(self.wnd_proc)
        self.old_wndproc = SetWindowLong(self.hwnd, GWL_WNDPROC, self.new_wndproc)

    def wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_KEYDOWN:
            self.count_down += 1
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            name = vk_name(wparam)
            log_msg = f"[{ts}]  ▼ WM_KEYDOWN   {name:<12}  (VK {wparam})\n"
            self.append(log_msg, "down")
            self.update_stats()
        elif msg == WM_KEYUP:
            self.count_up += 1
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            name = vk_name(wparam)
            log_msg = f"[{ts}]  ▲ WM_KEYUP     {name:<12}  (VK {wparam})\n"
            self.append(log_msg, "up")
            self.update_stats()
            
        return CallWindowProc(self.old_wndproc, hwnd, msg, wparam, lparam)

    def append(self, text, tag=None):
        self.log.configure(state="normal")
        if tag:
            self.log.insert("end", text, tag)
        else:
            self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def update_stats(self):
        self.stats_var.set(
            f"  Messages — WM_KEYDOWN: {self.count_down}   WM_KEYUP: {self.count_up}"
        )

    def clear(self):
        self.count_down = 0
        self.count_up   = 0
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.stats_var.set("Waiting for Win32 messages…")

if __name__ == "__main__":
    app = KeyTester()
    app.mainloop()
