import customtkinter as ctk
import threading
import webbrowser
import os
import logging

from ui import customTheme
from modules.functions import ytTranscribeFunctions

logger = logging.getLogger(__name__)


class HistoryTab(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master)
        customTheme.initializeFonts()

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.historyFrame = ctk.CTkFrame(
            self,
            corner_radius=0,
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["BackgroundColor"]
        )
        self.historyFrame.grid(row=0, column=0, sticky="nsew")
        self.historyFrame.grid_columnconfigure(0, weight=1)
        self.historyFrame.grid_rowconfigure(1, weight=1)

        # ── Header Row ──────────────────────────────────────────────
        headerRow = ctk.CTkFrame(self.historyFrame, fg_color="transparent")
        headerRow.grid(row=0, column=0, padx=20, pady=(15, 5), sticky="ew")
        headerRow.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            headerRow, text="Transcription History",
            font=customTheme.globalFont20,
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"]
        ).grid(row=0, column=0, sticky="w")

        self.refreshBtn = ctk.CTkButton(
            headerRow, text="↻ Refresh", width=90,
            font=customTheme.globalFont12,
            command=self.refresh_history,
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["ButtonColor"],
            hover_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["ButtonHoverColor"],
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"]
        )
        self.refreshBtn.grid(row=0, column=1, sticky="e")

        # ── Scrollable list ─────────────────────────────────────────
        self.scrollFrame = ctk.CTkScrollableFrame(
            self.historyFrame,
            label_text="Past Transcriptions",
            label_font=customTheme.globalFont12,
            label_text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["ConsoleBackground"],
            scrollbar_button_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["ButtonColor"],
            scrollbar_button_hover_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["ButtonHoverColor"]
        )
        self.scrollFrame.grid(row=1, column=0, padx=20, pady=(0, 15), sticky="nsew")
        self.scrollFrame.grid_columnconfigure(0, weight=1)

        self.refresh_history()

    def refresh_history(self):
        """Reload history from disk and rebuild the list."""
        for w in self.scrollFrame.winfo_children():
            w.destroy()

        history = ytTranscribeFunctions.load_history()

        if not history:
            ctk.CTkLabel(
                self.scrollFrame,
                text="No transcriptions yet. Use YT Transcribe to get started!",
                font=customTheme.globalFont12,
                text_color="gray"
            ).pack(pady=30)
            return

        for entry in history:
            self._make_history_card(entry)

    def _make_history_card(self, entry):
        card = ctk.CTkFrame(
            self.scrollFrame,
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["OptionBackColor"],
            corner_radius=6, border_width=1,
            border_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["SpeedValueBoxBorderColor"]
        )
        card.pack(fill="x", pady=3, padx=4)
        card.grid_columnconfigure(1, weight=1)

        # Title
        ctk.CTkLabel(
            card, text=entry.get('title', 'Unknown'),
            font=customTheme.globalFont14,
            text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
            anchor="w", wraplength=320
        ).grid(row=0, column=0, columnspan=3, padx=10, pady=(8, 0), sticky="w")

        # Timestamp
        ctk.CTkLabel(
            card,
            text=f"🕐 {entry.get('timestamp', '')}",
            font=customTheme.globalFont11,
            text_color="gray", anchor="w"
        ).grid(row=1, column=0, columnspan=3, padx=10, pady=(0, 4), sticky="w")

        # MIDI path (small text)
        midi_path = entry.get('midi_path', '')
        midi_exists = os.path.exists(midi_path) if midi_path else False
        path_display = os.path.basename(midi_path) if midi_path else "N/A"

        ctk.CTkLabel(
            card,
            text=f"📁 {path_display}" + ("" if midi_exists else "  (file missing)"),
            font=customTheme.globalFont11,
            text_color="#22c55e" if midi_exists else "#ef4444",
            anchor="w"
        ).grid(row=2, column=0, padx=10, pady=(0, 8), sticky="w")

        # Buttons
        btnFrame = ctk.CTkFrame(card, fg_color="transparent")
        btnFrame.grid(row=2, column=2, padx=10, pady=(0, 8), sticky="e")

        url = entry.get('url', '')
        if url:
            ctk.CTkButton(
                btnFrame, text="▶ Preview", width=80,
                font=customTheme.globalFont11,
                fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["ButtonColor"],
                hover_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["ButtonHoverColor"],
                text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
                command=lambda u=url: webbrowser.open(u)
            ).pack(side="left", padx=(0, 4))

        if midi_exists:
            ctk.CTkButton(
                btnFrame, text="🎹 Play", width=70,
                font=customTheme.globalFont11,
                fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["PlayColor"],
                hover_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["PlayColorHover"],
                text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["TextColor"],
                command=lambda p=midi_path: self._play_midi(p)
            ).pack(side="left")

    def _play_midi(self, midi_path):
        """Load this MIDI file into the player and switch to the player tab."""
        try:
            from modules.functions import mainFunctions
            app = mainFunctions.getApp()
            if app:
                ytTranscribeFunctions.autoplay_midi(midi_path, app)
        except Exception as e:
            logger.error(f"Failed to play MIDI from history: {e}")
