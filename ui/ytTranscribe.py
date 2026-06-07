import io
import logging
import os
import threading
import urllib.request
import webbrowser

import customtkinter as ctk
from PIL import Image

from modules.functions import mainFunctions, ytTranscribeFunctions
from ui import customTheme

logger = logging.getLogger(__name__)


class YtTranscribeTab(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)
        customTheme.initializeFonts()

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.transcribeFrame = mainFunctions.ScrollableFrame(
            self,
            corner_radius=0,
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "BackgroundColor"
            ],
        )
        self.transcribeFrame.grid(row=0, column=0, sticky="nsew")
        self.transcribeFrame.grid_columnconfigure(0, weight=1)

        # ── Header ──────────────────────────────────────────────────
        ctk.CTkLabel(
            self.transcribeFrame,
            text="YouTube Piano Transcriptor",
            font=customTheme.globalFont20,
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
        ).grid(row=0, column=0, padx=20, pady=(15, 2), sticky="w")

        # ── Cookie status bar (hidden when cookies already found) ────
        cookieBar = ctk.CTkFrame(self.transcribeFrame, fg_color="transparent")
        self.cookieCookieBar = cookieBar  # keep ref for show/hide
        cookieBar.grid(row=1, column=0, padx=20, pady=(0, 4), sticky="ew")
        cookieBar.grid_columnconfigure(0, weight=1)

        self.cookieStatusLabel = ctk.CTkLabel(
            cookieBar, text="", font=customTheme.globalFont11, anchor="w"
        )
        self.cookieStatusLabel.grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            cookieBar,
            text="Cookie Setup Guide",
            width=150,
            font=customTheme.globalFont11,
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["ButtonColor"],
            hover_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "ButtonHoverColor"
            ],
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
            command=self._show_cookie_guide,
        ).grid(row=0, column=1, sticky="e")

        self._refresh_cookie_status()

        # ── Options Panel (URL / time / device) ────────────────────────
        optFrame = ctk.CTkFrame(
            self.transcribeFrame,
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "ConsoleBackground"
            ],
            corner_radius=8,
        )
        optFrame.grid(row=2, column=0, padx=20, pady=(5, 5), sticky="ew")
        optFrame.grid_columnconfigure(1, weight=1)

        # URL row
        ctk.CTkLabel(
            optFrame,
            text="YouTube URL (or select from search above)",
            font=customTheme.globalFont11,
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
        ).grid(row=0, column=0, columnspan=4, padx=10, pady=(8, 0), sticky="w")

        self.urlEntry = ctk.CTkEntry(
            optFrame,
            placeholder_text="https://www.youtube.com/watch?v=...",
            font=customTheme.globalFont12,
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "OptionBackColor"
            ],
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
            border_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "SpeedValueBoxBorderColor"
            ],
        )
        self.urlEntry.grid(
            row=1, column=0, columnspan=4, padx=10, pady=(2, 8), sticky="ew"
        )

        # Time / device row
        ctk.CTkLabel(
            optFrame,
            text="Start Time",
            font=customTheme.globalFont11,
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
        ).grid(row=2, column=0, padx=(10, 5), pady=(0, 2), sticky="w")
        ctk.CTkLabel(
            optFrame,
            text="End Time (or 'Full')",
            font=customTheme.globalFont11,
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
        ).grid(row=2, column=1, padx=5, pady=(0, 2), sticky="w")
        ctk.CTkLabel(
            optFrame,
            text="Device",
            font=customTheme.globalFont11,
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
        ).grid(row=2, column=2, padx=(5, 10), pady=(0, 2), sticky="w")

        self.startEntry = ctk.CTkEntry(
            optFrame,
            placeholder_text="0:00",
            width=100,
            font=customTheme.globalFont12,
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "OptionBackColor"
            ],
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
            border_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "SpeedValueBoxBorderColor"
            ],
        )
        self.startEntry.insert(0, "0:00")
        self.startEntry.grid(row=3, column=0, padx=(10, 5), pady=(0, 8), sticky="w")

        self.endEntry = ctk.CTkEntry(
            optFrame,
            placeholder_text="Full",
            width=100,
            font=customTheme.globalFont12,
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "OptionBackColor"
            ],
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
            border_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "SpeedValueBoxBorderColor"
            ],
        )
        self.endEntry.insert(0, "Full")
        self.endEntry.grid(row=3, column=1, padx=5, pady=(0, 8), sticky="w")

        self.cudaMenu = ctk.CTkOptionMenu(
            optFrame,
            values=["CPU", "GPU (CUDA)"],
            font=customTheme.globalFont11,
            dropdown_font=customTheme.globalFont11,
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "OptionBackColor"
            ],
            dropdown_fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "OptionDropdownBackground"
            ],
            button_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "OptionDropdownButtonColor"
            ],
            button_hover_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "OptionDropdownButtonHoverColor"
            ],
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
        )
        self.cudaMenu.set("GPU (CUDA)")
        self.cudaMenu.grid(row=3, column=2, padx=(5, 10), pady=(0, 8), sticky="ew")

        # ── Transcribe & Play button (right below Start Time) ────────
        self.transcribeBtn = ctk.CTkButton(
            optFrame,
            text="Transcribe & Play",
            font=customTheme.globalFont14,
            command=self.trigger_transcription,
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["PlayColor"],
            hover_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "PlayColorHover"
            ],
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
        )
        self.transcribeBtn.grid(
            row=4, column=0, columnspan=3, padx=(10, 10), pady=(8, 5), sticky="ew"
        )

        # ── Progress / Status (right below Transcribe button) ────────
        self.statusLabel = ctk.CTkLabel(
            optFrame,
            text="Ready",
            font=customTheme.globalFont12,
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
        )
        self.statusLabel.grid(
            row=5, column=0, columnspan=3, sticky="w", padx=(10, 10), pady=(4, 2)
        )

        self.progressBar = ctk.CTkProgressBar(
            optFrame,
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "SpeedSliderBackColor"
            ],
            progress_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "SpeedSliderFillColor"
            ],
        )
        self.progressBar.grid(row=6, column=0, columnspan=3, padx=(10, 10), pady=(2, 8))
        self.progressBar.set(0)

        # ── Search Row ───────────────────────────────────────────────
        searchRow = ctk.CTkFrame(self.transcribeFrame, fg_color="transparent")
        searchRow.grid(row=3, column=0, padx=20, pady=(5, 5), sticky="ew")
        searchRow.grid_columnconfigure(0, weight=1)

        self.searchEntry = ctk.CTkEntry(
            searchRow,
            placeholder_text="Search YouTube for piano videos...",
            font=customTheme.globalFont14,
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "OptionBackColor"
            ],
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
            border_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "SpeedValueBoxBorderColor"
            ],
        )
        self.searchEntry.grid(row=0, column=0, padx=(0, 10), sticky="ew")
        self.searchEntry.bind("<Return>", lambda e: self.trigger_search())

        self.searchBtn = ctk.CTkButton(
            searchRow,
            text="Search",
            width=90,
            font=customTheme.globalFont14,
            command=self.trigger_search,
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["ButtonColor"],
            hover_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "ButtonHoverColor"
            ],
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
        )
        self.searchBtn.grid(row=0, column=1, sticky="e")

        # ── Results Frame (Parent provides scrolling) ───────────────────
        self.scrollFrameWrapper = ctk.CTkFrame(
            self.transcribeFrame,
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "ConsoleBackground"
            ],
            corner_radius=8,
        )
        self.scrollFrameWrapper.grid(row=4, column=0, padx=20, pady=(0, 5), sticky="ew")
        self.scrollFrameWrapper.grid_columnconfigure(0, weight=1)

        self.scrollFrameLabel = ctk.CTkLabel(
            self.scrollFrameWrapper,
            text="Search Results  (click a video to select it)",
            font=customTheme.globalFont12,
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
        )
        self.scrollFrameLabel.grid(row=0, column=0, pady=(10, 5))

        self.scrollFrame = ctk.CTkFrame(self.scrollFrameWrapper, fg_color="transparent")
        self.scrollFrame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.scrollFrame.grid_columnconfigure(0, weight=1)

        self._placeholder_lbl = ctk.CTkLabel(
            self.scrollFrame,
            text="Search for a piano video above to get started.",
            font=customTheme.globalFont12,
            text_color="gray",
        )
        self._placeholder_lbl.pack(pady=20)

        # ── Setup warning (shown only when libs missing) ─────────────
        self.setupFrame = ctk.CTkFrame(self.transcribeFrame, fg_color="transparent")
        self.setupFrame.grid(row=5, column=0, padx=20, pady=0, sticky="ew")
        self.setupFrame.grid_columnconfigure(0, weight=1)

        self.selected_video_url = ""
        self._check_dep_status()

    # ── Cookie helpers ───────────────────────────────────────────────
    def _refresh_cookie_status(self):
        cookies_file = ytTranscribeFunctions.COOKIES_FILE
        if os.path.exists(cookies_file):
            self.cookieStatusLabel.configure(
                text="✓ cookies.txt found — YouTube auth active", text_color="#22c55e"
            )
            # Hide cookie bar since everything is set up
            self.cookieCookieBar.grid_remove()
        else:
            self.cookieStatusLabel.configure(
                text="⚠ No cookies — YouTube may block downloads. Click 'Cookie Setup Guide'.",
                text_color="#f59e0b",
            )
            # Show cookie bar to guide user
            self.cookieCookieBar.grid()

    def _show_cookie_guide(self):
        import os
        import subprocess

        cookies_dir = os.path.dirname(ytTranscribeFunctions.COOKIES_FILE)
        os.makedirs(cookies_dir, exist_ok=True)
        # Open the folder
        subprocess.Popen(f'explorer "{cookies_dir}"')
        # Show instructions in status label
        self.statusLabel.configure(
            text=(
                "SETUP: Install 'Get cookies.txt LOCALLY' extension in Chrome. "
                "Go to youtube.com (logged in), click the extension → Export. "
                f"Save the file as: youtube_cookies.txt  in the folder that just opened."
            ),
            text_color="#60a5fa",
        )

    # ── Dependency check ─────────────────────────────────────────────
    def _check_dep_status(self):
        deps = ytTranscribeFunctions.check_dependencies()
        all_ok = all(deps.values())
        for w in self.setupFrame.winfo_children():
            w.destroy()
        if not all_ok:
            missing = [k for k, v in deps.items() if not v]
            self.transcribeBtn.configure(state="disabled")
            self.statusLabel.configure(
                text=f"Missing: {', '.join(missing)}. Click Setup to install.",
                text_color="orange",
            )
            ctk.CTkButton(
                self.setupFrame,
                text="Setup Dependencies  (~2 GB download)",
                font=customTheme.globalFont12,
                command=self._run_setup,
                fg_color="#D97706",
                hover_color="#B45309",
                text_color="white",
            ).grid(row=0, column=0, sticky="ew", pady=4)
        else:
            self.transcribeBtn.configure(state="normal")
            self.statusLabel.configure(
                text="Ready",
                text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                    "TextColor"
                ],
            )

    def _run_setup(self):
        self.transcribeBtn.configure(state="disabled")
        self.progressBar.set(0)

        def cb(msg, pct):
            self.after(0, lambda m=msg, p=pct: self._on_progress(m, p))

        ytTranscribeFunctions.install_dependencies(cb)

    # ── Search ───────────────────────────────────────────────────────
    def trigger_search(self):
        query = self.searchEntry.get().strip()
        if not query:
            return
        self.searchBtn.configure(state="disabled", text="Searching…")
        self._clear_results()
        ctk.CTkLabel(
            self.scrollFrame,
            text="Fetching results…",
            font=customTheme.globalFont12,
            text_color="gray",
        ).pack(pady=20)

        def worker():
            try:
                results = ytTranscribeFunctions.search_youtube(query)
                self.after(0, lambda r=results: self._show_results(r))
            except Exception as e:
                self.after(0, lambda msg=str(e): self._show_search_error(msg))

        threading.Thread(target=worker, daemon=True).start()

    def _clear_results(self):
        for w in self.scrollFrame.winfo_children():
            w.destroy()

    def _show_search_error(self, msg):
        self.searchBtn.configure(state="normal", text="Search")
        self._clear_results()
        ctk.CTkLabel(
            self.scrollFrame,
            text=f"Search error: {msg}",
            font=customTheme.globalFont12,
            text_color="red",
            wraplength=380,
        ).pack(pady=20)

    def _show_results(self, results):
        self.searchBtn.configure(state="normal", text="Search")
        self._clear_results()

        if not results:
            ctk.CTkLabel(
                self.scrollFrame,
                text="No results found. Check your query or internet connection.",
                font=customTheme.globalFont12,
                text_color="gray",
            ).pack(pady=20)
            return

        for item in results:
            self._make_result_card(item)

    def _make_result_card(self, item):
        card = ctk.CTkFrame(
            self.scrollFrame,
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "OptionBackColor"
            ],
            corner_radius=6,
            border_width=1,
            border_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "SpeedValueBoxBorderColor"
            ],
        )
        card.pack(fill="x", pady=3, padx=4)

        # Thumbnail placeholder
        thumb = ctk.CTkLabel(card, text="⬛", width=120, height=68, fg_color="#111111")
        thumb.pack(side="left", padx=5, pady=5)

        # Load thumbnail async
        def _load_thumb(url, lbl):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    data = r.read()
                img = Image.open(io.BytesIO(data)).resize(
                    (120, 68), Image.Resampling.LANCZOS
                )
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(120, 68))
                self.after(0, lambda: lbl.configure(image=ctk_img, text=""))
                lbl._img_ref = ctk_img  # keep alive
            except Exception:
                pass

        threading.Thread(
            target=_load_thumb, args=(item["thumbnail"], thumb), daemon=True
        ).start()

        # Text side
        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=(8, 6), pady=6)

        ctk.CTkLabel(
            info,
            text=item["title"],
            font=customTheme.globalFont12,
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
            anchor="w",
            justify="left",
            wraplength=260,
        ).pack(fill="x", anchor="w")

        ctk.CTkLabel(
            info,
            text=f"{item['channel']}  ·  {item['duration_str']}",
            font=customTheme.globalFont11,
            text_color="gray",
            anchor="w",
        ).pack(fill="x", anchor="w", pady=(4, 0))

        # Click anywhere on the card selects it
        url = item["url"]
        title = item["title"]

        def _select(e=None, _url=url, _title=title, _card=card):
            self.select_video(_url, _title, _card)

        card.bind("<Button-1>", _select)
        for child in card.winfo_children():
            child.bind("<Button-1>", _select)
            for grandchild in child.winfo_children():
                grandchild.bind("<Button-1>", _select)

        # Preview button (opens in default browser)
        previewBtn = ctk.CTkButton(
            card,
            text="▶ Preview",
            width=70,
            font=customTheme.globalFont11,
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["ButtonColor"],
            hover_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "ButtonHoverColor"
            ],
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
            command=lambda u=url: webbrowser.open(u),
        )
        previewBtn.pack(side="right", padx=5, pady=5)

    def select_video(self, url, title, card_widget):
        self.selected_video_url = url
        self.urlEntry.delete(0, "end")
        self.urlEntry.insert(0, url)
        # Reset all borders
        for f in self.scrollFrame.winfo_children():
            if isinstance(f, ctk.CTkFrame):
                f.configure(
                    border_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                        "SpeedValueBoxBorderColor"
                    ]
                )
        # Highlight selection
        card_widget.configure(
            border_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["PlayColor"]
        )

    # ── Transcription ────────────────────────────────────────────────
    def _parse_time(self, s):
        """Return seconds (float). Empty / 'Full' / 'All' / '0' → None (meaning full video)."""
        s = s.strip().lower()
        if not s or s in ("full", "all", "none", "0:00", "0"):
            return None
        try:
            parts = s.split(":")
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            return float(s)
        except ValueError:
            return None

    def trigger_transcription(self):
        url = self.urlEntry.get().strip()
        if not url:
            self.statusLabel.configure(
                text="Please enter or select a YouTube URL first.", text_color="red"
            )
            return
        if not url.startswith("http"):
            self.statusLabel.configure(
                text="URL must start with https://", text_color="red"
            )
            return

        start_sec = self._parse_time(self.startEntry.get()) or 0.0
        end_sec = self._parse_time(self.endEntry.get())  # None = full video

        use_cuda = self.cudaMenu.get() == "GPU (CUDA)"

        self.transcribeBtn.configure(state="disabled")
        self.progressBar.set(0)
        self.statusLabel.configure(
            text="Starting…",
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
        )

        def cb(msg, pct):
            self.after(0, lambda m=msg, p=pct: self._on_progress(m, p))

        ytTranscribeFunctions.transcribe_youtube_video(
            video_url=url,
            start_time_sec=start_sec,
            end_time_sec=end_sec,  # None means no end limit
            use_cuda=use_cuda,
            progress_callback=cb,
        )

    def _on_progress(self, msg, pct):
        if pct < 0:
            self.statusLabel.configure(text=msg, text_color="red")
            self.transcribeBtn.configure(state="normal")
        else:
            self.statusLabel.configure(
                text=msg,
                text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                    "TextColor"
                ],
            )
            self.progressBar.set(max(0.0, min(1.0, pct / 100.0)))
            if pct >= 100:
                self.transcribeBtn.configure(state="normal")
                self.after(500, self._check_dep_status)
