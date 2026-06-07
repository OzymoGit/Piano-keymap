import datetime
import json
import logging
import os
import platform
import threading
from tkinter import filedialog

import customtkinter
import keyboard
from mido import MidiFile
from pynput import keyboard as pynputKeyboard

from modules import configuration
from modules.functions import mainFunctions
from modules.midiHandler import useOutput
from ui import customTheme
from ui.midiPlayer import MidiPlayerTab
from ui.settings import SettingsTab

logger = logging.getLogger(__name__)
osName = platform.system()

if osName == "Windows":
    from modules.midiHandler import midiWindows as midiHandler
elif osName == "Darwin":
    from modules.midiHandler import midiDarwin as midiHandler
elif osName == "Linux":
    from modules.midiHandler import midiLinux as midiHandler

app = mainFunctions.getApp()

switchUseMIDIvar = customtkinter.StringVar(value="off")
switchSustainvar = customtkinter.StringVar(value="off")
switchNoDoublesvar = customtkinter.StringVar(value="off")
switchVelocityvar = customtkinter.StringVar(value="off")
switch88Keysvar = customtkinter.StringVar(value="off")
switch50Keysvar = customtkinter.StringVar(value="off")
switchAutoPlayvar = customtkinter.StringVar(value="off")

switchUseMIDIvar.set(
    "on"
    if configuration.configData.get("midiPlayer", {}).get("useMIDIOutput", False)
    else "off"
)
switchSustainvar.set(
    "on"
    if configuration.configData.get("midiPlayer", {}).get("sustain", False)
    else "off"
)
switchNoDoublesvar.set(
    "on"
    if configuration.configData.get("midiPlayer", {}).get("noDoubles", False)
    else "off"
)
switchVelocityvar.set(
    "on"
    if configuration.configData.get("midiPlayer", {}).get("velocity", False)
    else "off"
)
switch88Keysvar.set(
    "on"
    if configuration.configData.get("midiPlayer", {}).get("88Keys", False)
    else "off"
)
switch50Keysvar.set(
    "on"
    if configuration.configData.get("midiPlayer", {}).get("use50Keys", False)
    else "off"
)
switchAutoPlayvar.set(
    "on"
    if configuration.configData.get("midiPlayer", {}).get("autoPlayNext", False)
    else "off"
)


def switchUseMIDI():
    logger.info("switchUseMIDI called")
    try:
        configuration.configData["midiPlayer"]["useMIDIOutput"] = (
            switchUseMIDIvar.get() == "on"
        )
        configuration.configData.save()

        mainFunctions.clearConsole()
        mainFunctions.refreshOutputDevices()
        if switchUseMIDIvar.get() == "on":
            threading.Thread(
                target=mainFunctions.insertConsoleText,
                args=(
                    "-------< WARNING >-------   This will not press keys for you!",
                    True,
                ),
            ).start()
        else:
            threading.Thread(
                target=mainFunctions.insertConsoleText, args=("Macro Mode.", True)
            ).start()
    except Exception as e:
        logger.exception(f"switchUseMIDI error: {e}")


def switchSustain():
    logger.info("switchSustain called")
    try:
        configuration.configData["midiPlayer"]["sustain"] = (
            switchSustainvar.get() == "on"
        )
        configuration.configData.save()
    except Exception as e:
        logger.exception(f"switchSustain error: {e}")


def switchNoDoubles():
    logger.info("switchNoDoubles called")
    try:
        configuration.configData["midiPlayer"]["noDoubles"] = (
            switchNoDoublesvar.get() == "on"
        )
        configuration.configData.save()
    except Exception as e:
        logger.exception(f"switchNoDoubles error: {e}")


def switchVelocity():
    logger.info("switchVelocity called")
    try:
        configuration.configData["midiPlayer"]["velocity"] = (
            switchVelocityvar.get() == "on"
        )
        configuration.configData.save()
    except Exception as e:
        logger.exception(f"switchVelocity error: {e}")


def switch88Keys():
    logger.info("switch88Keys called")
    try:
        configuration.configData["midiPlayer"]["88Keys"] = switch88Keysvar.get() == "on"
        if switch88Keysvar.get() == "on":
            switch50Keysvar.set("off")
            configuration.configData["midiPlayer"]["use50Keys"] = False
        configuration.configData.save()
    except Exception as e:
        logger.exception(f"switch88Keys error: {e}")


def switch50Keys():
    logger.info("switch50Keys called")
    try:
        configuration.configData["midiPlayer"]["use50Keys"] = switch50Keysvar.get() == "on"
        if switch50Keysvar.get() == "on":
            switch88Keysvar.set("off")
            configuration.configData["midiPlayer"]["88Keys"] = False
        configuration.configData.save()
    except Exception as e:
        logger.exception(f"switch50Keys error: {e}")


def switchAutoPlay():
    logger.info("switchAutoPlay called")
    try:
        configuration.configData["midiPlayer"]["autoPlayNext"] = (
            switchAutoPlayvar.get() == "on"
        )
        configuration.configData.save()
    except Exception as e:
        logger.exception(f"switchAutoPlay error: {e}")


def drawMidiVisualizer(file_path):
    """Parse the MIDI file in a background thread and draw note rectangles on the canvas."""

    def _parse_and_draw():
        try:
            midi = MidiFile(file_path, clip=True)
            total_time = midi.length
            if total_time <= 0:
                return

            # Gather all note_on events with absolute time
            notes = []
            for track in midi.tracks:
                current_time = 0.0
                tempo = 500000  # default 120 BPM
                ticks_per_beat = midi.ticks_per_beat
                for msg in track:
                    if msg.type == "set_tempo":
                        tempo = msg.tempo
                    delta_sec = msg.time * (tempo / ticks_per_beat) / 1_000_000
                    current_time += delta_sec
                    if msg.type == "note_on" and msg.velocity > 0:
                        notes.append((current_time, msg.note))

            if not notes:
                return

            def _draw():
                try:
                    canvas = MidiPlayerTab.visualizerCanvas
                    canvas.delete("all")
                    canvas.update_idletasks()
                    w = canvas.winfo_width()
                    h = canvas.winfo_height()
                    # Use actual canvas dimensions; fall back to sensible defaults only if layout hasn't happened yet
                    if w <= 1:
                        w = max(300, int(canvas.master.winfo_width() * 0.9))
                    if h <= 1:
                        h = 40

                    # --- Heatmap density visualization ---
                    NUM_BINS = max(w // 2, 30)
                    pitch_bins = {}  # (bin_idx, pitch_range_idx) -> count

                    for t, pitch in notes:
                        bin_idx = int((t / total_time) * NUM_BINS)
                        bin_idx = min(bin_idx, NUM_BINS - 1)
                        if pitch < 36:
                            pr = 0  # sub-bass
                        elif pitch < 48:
                            pr = 1  # bass
                        elif pitch < 60:
                            pr = 2  # low-mid
                        elif pitch < 72:
                            pr = 3  # mid
                        elif pitch < 84:
                            pr = 4  # high-mid
                        elif pitch < 96:
                            pr = 5  # treble
                        else:
                            pr = 6  # super-treble
                        key = (bin_idx, pr)
                        pitch_bins[key] = pitch_bins.get(key, 0) + 1

                    if not pitch_bins:
                        return

                    max_count = max(pitch_bins.values())

                    for (bin_idx, pr), count in pitch_bins.items():
                        density = count / max_count
                        x1 = int((bin_idx / NUM_BINS) * w)
                        x2 = min(int(((bin_idx + 1) / NUM_BINS) * w), w)
                        if pr == 0:
                            bottom_y = int(h * 7 / 8)
                        elif pr == 1:
                            bottom_y = int(h * 6 / 8)
                        elif pr == 2:
                            bottom_y = int(h * 5 / 8)
                        elif pr == 3:
                            bottom_y = int(h * 4 / 8)
                        elif pr == 4:
                            bottom_y = int(h * 3 / 8)
                        elif pr == 5:
                            bottom_y = int(h * 2 / 8)
                        else:
                            bottom_y = int(h * 1 / 8)

                        if density > 0.66:
                            color = "#4caf50"
                        elif density > 0.33:
                            color = "#2e7d32"
                        else:
                            color = "#1b5e20"
                        canvas.create_rectangle(
                            x1, bottom_y, x2, h - 4, fill=color, outline=""
                        )

                    def _on_click(event):
                        if not app.isRunning:
                            return
                        try:
                            canvas = MidiPlayerTab.visualizerCanvas
                            cw = canvas.winfo_width()
                            if cw <= 1:
                                return
                            frac = event.x / float(cw)
                            frac = max(0.0, min(frac, 1.0))
                            seekPlayback(frac)
                        except Exception as e:
                            logger.debug(f"Visualizer click error: {e}")

                    canvas.bind("<Button-1>", _on_click)

                except Exception as e:
                    logger.debug(f"_draw error: {e}")

            MidiPlayerTab.visualizerCanvas.after(0, _draw)
        except Exception as e:
            logger.debug(f"drawMidiVisualizer parse error: {e}")

    threading.Thread(target=_parse_and_draw, daemon=True).start()


def openMidiFolder():
    try:
        midi_dir = os.path.join(configuration.baseDirectory, "Midis")
        os.makedirs(midi_dir, exist_ok=True)
        os.startfile(midi_dir)
    except Exception as e:
        logger.exception(f"openMidiFolder error: {e}")


def refreshFileList():
    try:
        for widget in MidiPlayerTab.fileListFrame.winfo_children():
            widget.destroy()

        midi_dir = os.path.join(configuration.baseDirectory, "Midis")
        os.makedirs(midi_dir, exist_ok=True)
        files = [
            f for f in os.listdir(midi_dir) if f.lower().endswith((".mid", ".midi"))
        ]

        configuration.configData["midiPlayer"]["midiList"] = [
            os.path.join(midi_dir, f) for f in files
        ]
        configuration.configData.save()

        if not files:
            customtkinter.CTkLabel(
                MidiPlayerTab.fileListFrame,
                text="No MIDI files found in 'Midis' folder.",
                text_color="gray",
            ).pack(pady=20)
            return

        for idx, filename in enumerate(files):
            file_path = os.path.join(midi_dir, filename)
            card = customtkinter.CTkFrame(
                MidiPlayerTab.fileListFrame,
                fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                    "OptionBackColor"
                ],
                corner_radius=6,
                border_width=1,
                border_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                    "SpeedValueBoxBorderColor"
                ],
            )
            card.pack(fill="x", pady=2, padx=2)
            card.grid_columnconfigure(0, weight=1)

            lbl = customtkinter.CTkLabel(
                card,
                text=filename,
                font=customTheme.globalFont12,
                text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                    "TextColor"
                ],
                anchor="w",
            )
            lbl.grid(row=0, column=0, padx=10, pady=5, sticky="w")

            btn = customtkinter.CTkButton(
                card,
                text="Play",
                width=60,
                height=24,
                font=customTheme.globalFont11,
                fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                    "ButtonColor"
                ],
                hover_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                    "ButtonHoverColor"
                ],
                text_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                    "TextColor"
                ],
                command=lambda p=file_path: selectAndPlayFile(p),
            )
            btn.grid(row=0, column=1, padx=5, pady=5)

            # Highlight current
            if MidiPlayerTab.filePathEntry.get() == file_path:
                card.configure(
                    border_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                        "PlayColor"
                    ]
                )
    except Exception as e:
        logger.exception(f"refreshFileList error: {e}")


def selectAndPlayFile(file_path):
    try:
        MidiPlayerTab.filePathEntry.set(file_path)
        configuration.configData["midiPlayer"]["currentFile"] = file_path
        configuration.configData.save()

        midiFileData = MidiFile(file_path, clip=True)
        totalTime = midiFileData.length
        totalStr = str(datetime.timedelta(seconds=int(totalTime)))
        timelineText = (
            f"0:00:00 / {totalStr}"
            if configuration.configData["appUI"]["timestamp"]
            else f"X:XX:XX / {totalStr}"
        )
        MidiPlayerTab.timelineIndicator.configure(text=timelineText)
        MidiPlayerTab.seekSlider.set(0)
        bindControls()

        # Draw note visualizer and track the current file for resize redraws
        MidiPlayerTab._current_midi_file = file_path
        drawMidiVisualizer(file_path)

        # Visually update list
        refreshFileList()

        # Start playback
        stopPlayback(autoPlayNextTrigger=False)
        startPlayback()
    except Exception as e:
        logger.exception(f"selectAndPlayFile error: {e}")


def selectFile():
    pass


def loadSavedFile():
    logger.info("loadSavedFile called")
    try:
        currentFile = configuration.configData["midiPlayer"].get("currentFile", "")
        if currentFile and os.path.exists(currentFile):
            MidiPlayerTab.filePathEntry.set(currentFile)
            midiFileData = MidiFile(currentFile, clip=True)
            totalTime = midiFileData.length
            totalStr = str(datetime.timedelta(seconds=int(totalTime)))
            timelineText = (
                f"0:00:00 / {totalStr}"
                if configuration.configData["appUI"]["timestamp"]
                else f"X:XX:XX / {totalStr}"
            )
            MidiPlayerTab.timelineIndicator.configure(text=timelineText)
            MidiPlayerTab.seekSlider.set(0)
            drawMidiVisualizer(currentFile)
        else:
            MidiPlayerTab.filePathEntry.set("None")
            MidiPlayerTab.timelineIndicator.configure(text="0:00:00 / 0:00:00")
            MidiPlayerTab.seekSlider.set(0)
            # Clear visualizer
            try:
                MidiPlayerTab.visualizerCanvas.delete("all")
            except Exception:
                pass

        refreshFileList()
    except Exception as e:
        logger.exception(f"loadSavedFile error: {e}")


def switchMidiEvent(event=None):
    pass


def bindControls():
    try:
        playKey = configuration.configData["hotkeys"].get("play", "F1").upper()
        pauseKey = configuration.configData["hotkeys"].get("pause", "F2").upper()
        stopKey = configuration.configData["hotkeys"].get("stop", "F3").upper()
        speedUpKey = configuration.configData["hotkeys"].get("speedup", "F4").upper()
        slowDownKey = configuration.configData["hotkeys"].get("slowdown", "F5").upper()

        if osName == "Windows":
            unbindControls()
            midiHandler.keyboardHandlers.append(
                keyboard.on_press_key(playKey.lower(), lambda e: startPlayback())
            )
            midiHandler.keyboardHandlers.append(
                keyboard.on_press_key(pauseKey.lower(), lambda e: pausePlayback())
            )
            midiHandler.keyboardHandlers.append(
                keyboard.on_press_key(stopKey.lower(), lambda e: stopPlayback())
            )
            midiHandler.keyboardHandlers.append(
                keyboard.on_press_key(speedUpKey.lower(), lambda e: decreaseSpeed())
            )
            midiHandler.keyboardHandlers.append(
                keyboard.on_press_key(slowDownKey.lower(), lambda e: increaseSpeed())
            )
        else:
            from modules.functions import mainFunctions

            mainFunctions.activeHotkeys.clear()
            mainFunctions.activeHotkeys.update(
                {
                    playKey: startPlayback,
                    pauseKey: pausePlayback,
                    stopKey: stopPlayback,
                    speedUpKey: decreaseSpeed,
                    slowDownKey: increaseSpeed,
                }
            )
            mainFunctions.startGlobalListener()
    except Exception as e:
        logger.exception(f"bindControls error: {e}")


def unbindControls():
    try:
        if osName == "Windows":
            for h in list(midiHandler.keyboardHandlers):
                try:
                    keyboard.unhook(h)
                except Exception:
                    pass
            midiHandler.keyboardHandlers.clear()
        else:
            from modules.functions import mainFunctions

            mainFunctions.activeHotkeys.clear()
    except Exception as e:
        logger.exception(f"unbindControls error: {e}")


def playButton():
    logger.info("playButton called")
    try:
        if not app.isRunning:
            startPlayback()
        else:
            pausePlayback()
    except Exception as e:
        logger.exception(f"playButton error: {e}")


def startPlayback(startOffset=0.0):
    logger.info(f"startPlayback called, offset={startOffset}")
    try:
        midiFile = MidiPlayerTab.filePathEntry.get()
        logger.debug(f"startPlayback midiFile: {midiFile}")
        if not os.path.exists(midiFile):
            logger.warning("MIDI File does not exist.")
            threading.Thread(
                target=mainFunctions.insertConsoleText,
                args=("MIDI File does not exist.", True),
            ).start()
            return

        useMIDI = configuration.configData["midiPlayer"]["useMIDIOutput"]

        if useMIDI:
            outputDevice = MidiPlayerTab.outputDeviceDropdown.get()
            logger.debug(f"outputDevice selected: {outputDevice}")
            if not outputDevice:
                threading.Thread(
                    target=mainFunctions.insertConsoleText,
                    args=("No MIDI output device selected.", True),
                ).start()
                return

            app.isRunning = True
            MidiPlayerTab.playButton.configure(
                text="Playing",
                fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                    "PlayingColor"
                ],
                hover_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                    "PlayingColorHover"
                ],
            )
            MidiPlayerTab.stopButton.configure(
                state="normal",
                fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                    "StopColor"
                ],
            )

            def updateTimeline(text, current=None, total=None):
                MidiPlayerTab.timelineIndicator.after(
                    0, lambda: MidiPlayerTab.timelineIndicator.configure(text=text)
                )
                if current is not None and total is not None and total > 0:
                    frac = current / total
                    MidiPlayerTab.seekSlider.after(
                        0, lambda c=frac: MidiPlayerTab.seekSlider.set(c)
                    )

                    # Draw playhead on visualizer
                    def _move_playhead(f=frac):
                        try:
                            canvas = MidiPlayerTab.visualizerCanvas
                            w = canvas.winfo_width()
                            if w <= 1:
                                return
                            canvas.delete("playhead")
                            x = int(f * w)
                            canvas.create_line(
                                x,
                                0,
                                x,
                                canvas.winfo_height(),
                                fill="#ef4444",
                                width=2,
                                tags="playhead",
                            )
                        except Exception:
                            pass

                    MidiPlayerTab.visualizerCanvas.after(0, _move_playhead)

            useOutput.startPlayback(
                midiFile,
                outputDevice,
                updateCallback=updateTimeline,
                startOffset=startOffset,
            )
            logger.debug("useOutput.startPlayback called")

        elif app and not app.isRunning:
            app.isRunning = True
            MidiPlayerTab.playButton.configure(
                text="Playing",
                fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                    "PlayingColor"
                ],
                hover_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                    "PlayingColorHover"
                ],
            )
            MidiPlayerTab.stopButton.configure(
                state="normal",
                fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                    "StopColor"
                ],
            )

            def updateTimeline(text, current=None, total=None):
                MidiPlayerTab.timelineIndicator.after(
                    0, lambda: MidiPlayerTab.timelineIndicator.configure(text=text)
                )
                if current is not None and total is not None and total > 0:
                    frac = current / total
                    MidiPlayerTab.seekSlider.after(
                        0, lambda c=frac: MidiPlayerTab.seekSlider.set(c)
                    )

                    # Draw playhead on visualizer
                    def _move_playhead(f=frac):
                        try:
                            canvas = MidiPlayerTab.visualizerCanvas
                            w = canvas.winfo_width()
                            if w <= 1:
                                return
                            canvas.delete("playhead")
                            x = int(f * w)
                            canvas.create_line(
                                x,
                                0,
                                x,
                                canvas.winfo_height(),
                                fill="#ef4444",
                                width=2,
                                tags="playhead",
                            )
                        except Exception:
                            pass

                    MidiPlayerTab.visualizerCanvas.after(0, _move_playhead)

            midiHandler.startPlayback(
                midiFile, updateCallback=updateTimeline, startOffset=startOffset
            )
            logger.debug("midiHandler.startPlayback called")
    except Exception as e:
        logger.exception(f"startPlayback error: {e}")


def seekPlayback(fraction):
    """Seek to a fractional position (0.0 - 1.0) in the current MIDI file."""
    logger.info(f"seekPlayback called with fraction={fraction}")
    try:
        midiFile = MidiPlayerTab.filePathEntry.get()
        if not midiFile or not os.path.exists(midiFile):
            return
        totalSeconds = MidiFile(midiFile, clip=True).length
        offsetSeconds = float(fraction) * totalSeconds

        useMIDI = configuration.configData["midiPlayer"]["useMIDIOutput"]

        was_running = app.isRunning

        # Cancel any pending seek delayed playback starts
        pending_after_id = getattr(MidiPlayerTab, "_pending_seek_after_id", None)
        if pending_after_id:
            try:
                app.after_cancel(pending_after_id)
            except Exception:
                pass
            MidiPlayerTab._pending_seek_after_id = None

        # Stop current playback cleanly
        if useMIDI:
            useOutput.stopPlayback()
        else:
            midiHandler.stopPlayback()

        app.isRunning = False

        # Only restart if the song was actually playing
        if was_running:
            import random
            min_delay = float(configuration.configData.get('midiPlayer', {}).get('minSeekDelay', 2.0))
            max_delay = float(configuration.configData.get('midiPlayer', {}).get('maxSeekDelay', 3.0))
            if min_delay > max_delay:
                min_delay, max_delay = max_delay, min_delay

            delay_sec = random.uniform(min_delay, max_delay)
            delay_ms = int(delay_sec * 1000)

            # Inform user of the delay in console
            from modules.functions.mainFunctions import insertConsoleText
            import threading
            threading.Thread(
                target=insertConsoleText,
                args=(f"Seeking... Resuming play in {delay_sec:.1f}s", True),
            ).start()

            def do_start():
                MidiPlayerTab._pending_seek_after_id = None
                startPlayback(startOffset=offsetSeconds)

            MidiPlayerTab._pending_seek_after_id = app.after(delay_ms, do_start)
        else:
            # Just update slider visually
            try:
                canvas = MidiPlayerTab.visualizerCanvas
                w = canvas.winfo_width()
                if w > 1:
                    canvas.delete("playhead")
                    x = int(fraction * w)
                    canvas.create_line(
                        x,
                        0,
                        x,
                        canvas.winfo_height(),
                        fill="#ef4444",
                        width=2,
                        tags="playhead",
                    )
            except Exception:
                pass
    except Exception as e:
        logger.exception(f"seekPlayback error: {e}")


def playNextSongInList():
    try:
        currentFile = MidiPlayerTab.filePathEntry.get()
        midiList = configuration.configData["midiPlayer"].get("midiList", [])
        if not midiList:
            return

        try:
            idx = midiList.index(currentFile)
            next_idx = (idx + 1) % len(midiList)
            next_file = midiList[next_idx]
            app.after(500, lambda: selectAndPlayFile(next_file))
        except ValueError:
            # Current file not in list, play first
            app.after(500, lambda: selectAndPlayFile(midiList[0]))
    except Exception as e:
        logger.exception(f"playNextSongInList error: {e}")


def stopPlayback(autoPlayNextTrigger=True):
    logger.info("stopPlayback called")
    try:
        if not app.isRunning:
            return

        useMIDI = configuration.configData["midiPlayer"]["useMIDIOutput"]

        if useMIDI:
            useOutput.stopPlayback()
            logger.debug("useOutput.stopPlayback called")
        else:
            midiHandler.stopPlayback()
            logger.debug("midiHandler.stopPlayback called")

        app.isRunning = False
        bindControls()
        MidiPlayerTab.stopButton.configure(
            state="disabled",
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "StopColorDisabled"
            ],
        )
        MidiPlayerTab.playButton.configure(
            text="Play",
            fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"]["PlayColor"],
            hover_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                "PlayColorHover"
            ],
        )

        midiFile = MidiPlayerTab.filePathEntry.get()
        if os.path.exists(midiFile):
            midiFileData = MidiFile(midiFile, clip=True)
            totalTime = midiFileData.length
            totalStr = str(datetime.timedelta(seconds=int(totalTime)))
            timelineText = (
                f"0:00:00 / {totalStr}"
                if configuration.configData["appUI"]["timestamp"]
                else f"X:XX:XX / {totalStr}"
            )
            MidiPlayerTab.timelineIndicator.configure(text=timelineText)

        logger.debug("stopPlayback completed")

        # Trigger Auto-Play Next
        if autoPlayNextTrigger and configuration.configData["midiPlayer"].get(
            "autoPlayNext", False
        ):
            logger.info("Song finished, triggering auto-play next.")
            playNextSongInList()

    except Exception as e:
        logger.exception(f"stopPlayback error: {e}")


def pausePlayback():
    logger.info("pausePlayback called")
    try:
        if not app.isRunning:
            return

        useMIDI = configuration.configData["midiPlayer"]["useMIDIOutput"]
        paused = False

        if useMIDI:
            useOutput.pausePlayback()
            paused = useOutput.paused
            logger.debug(f"useOutput.paused: {paused}")
        else:
            midiHandler.pausePlayback()
            paused = midiHandler.paused
            logger.debug(f"midiHandler.paused: {paused}")

        if paused:
            MidiPlayerTab.playButton.configure(
                text="Paused",
                fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                    "PausedColor"
                ],
                hover_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                    "PausedColorHover"
                ],
            )
        else:
            MidiPlayerTab.playButton.configure(
                text="Playing",
                fg_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                    "PlayingColor"
                ],
                hover_color=customTheme.activeThemeData["Theme"]["MidiPlayer"][
                    "PlayingColorHover"
                ],
            )
        logger.debug("pausePlayback state updated")
    except Exception as e:
        logger.exception(f"pausePlayback error: {e}")


def setSpeed(speed):
    logger.info(f"setSpeed called with speed: {speed}")
    try:
        useMIDI = configuration.configData["midiPlayer"]["useMIDIOutput"]

        if useMIDI:
            useOutput.playbackSpeed = max(0.01, min(5.0, speed / 100.0))
            app.playbackSpeed = round(useOutput.playbackSpeed * 100)
        else:
            midiHandler.playbackSpeed = max(0.01, min(5.0, speed / 100.0))
            app.playbackSpeed = round(midiHandler.playbackSpeed * 100)

        MidiPlayerTab.speedSlider.set(app.playbackSpeed)
        MidiPlayerTab.speedValueEntry.delete(0, "end")
        MidiPlayerTab.speedValueEntry.insert(0, str(app.playbackSpeed))
        logger.debug(f"playbackSpeed set to: {app.playbackSpeed}")
    except Exception as e:
        logger.exception(f"setSpeed error: {e}")


def decreaseSpeed():
    logger.info("decreaseSpeed called")
    try:
        useMIDI = configuration.configData["midiPlayer"]["useMIDIOutput"]
        app.focus_set()

        if useMIDI:
            useOutput.changeSpeed(
                -(configuration.configData["midiPlayer"]["decreaseSize"] / 100)
            )
            app.playbackSpeed = round(useOutput.playbackSpeed * 100)
        else:
            midiHandler.changeSpeed(
                -(configuration.configData["midiPlayer"]["decreaseSize"] / 100)
            )
            app.playbackSpeed = round(midiHandler.playbackSpeed * 100)

        MidiPlayerTab.speedSlider.set(app.playbackSpeed)
        MidiPlayerTab.speedValueEntry.delete(0, "end")
        MidiPlayerTab.speedValueEntry.insert(0, str(app.playbackSpeed))
        logger.debug(f"decreased playbackSpeed to: {app.playbackSpeed}")
    except Exception as e:
        logger.exception(f"decreaseSpeed error: {e}")


PITCH_OFFSETS = {
    "Lowest": -24,
    "Low": -12,
    "Middle": 0,
    "High": 12,
    "Highest": 24,
}

KEY_OFFSETS = {
    "C": 0,
    "C#": 1,
    "D": 2,
    "D#": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "G": 7,
    "G#": 8,
    "A": 9,
    "A#": 10,
    "B": 11,
}


def changePitch(value):
    logger.info(f"changePitch called: {value}")
    try:
        configuration.configData["midiPlayer"]["pitchOffset"] = PITCH_OFFSETS.get(
            value, 0
        )
        configuration.configData.save()
    except Exception as e:
        logger.exception(f"changePitch error: {e}")


def changeTranspose(value):
    logger.info(f"changeTranspose called: {value}")
    try:
        configuration.configData["midiPlayer"]["transposeOffset"] = KEY_OFFSETS.get(
            value, 0
        )
        configuration.configData.save()
    except Exception as e:
        logger.exception(f"changeTranspose error: {e}")


def increaseSpeed():
    logger.info("increaseSpeed called")
    try:
        useMIDI = configuration.configData["midiPlayer"]["useMIDIOutput"]
        app.focus_set()

        if useMIDI:
            useOutput.changeSpeed(
                configuration.configData["midiPlayer"]["decreaseSize"] / 100
            )
            app.playbackSpeed = round(useOutput.playbackSpeed * 100)
        else:
            midiHandler.changeSpeed(
                configuration.configData["midiPlayer"]["decreaseSize"] / 100
            )
            app.playbackSpeed = round(midiHandler.playbackSpeed * 100)

        MidiPlayerTab.speedSlider.set(app.playbackSpeed)
        MidiPlayerTab.speedValueEntry.delete(0, "end")
        MidiPlayerTab.speedValueEntry.insert(0, str(app.playbackSpeed))
        logger.debug(f"increased playbackSpeed to: {app.playbackSpeed}")
    except Exception as e:
        logger.exception(f"increaseSpeed error: {e}")
