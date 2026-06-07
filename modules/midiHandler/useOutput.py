import mido
import threading
import time
import random

from modules.functions import mainFunctions
from modules import configuration

activeTransposedNotes = {}
activeNotes = set()
stopEvent = threading.Event()
clockThreadRef = None
timerList = []
closeThread = False
paused = False
playThread = None
playbackSpeed = 1.0
sustainActive = False
midiOut = None
current_playback_id = 0

log = mainFunctions.log

def noteAllowed(note):
    allow88 = configuration.configData["midiPlayer"]["88Keys"]
    maps = configuration.configData["midiPlayer"]["pianoMap"]
    if not allow88:
        return str(note) in maps["61keyMap"]
    return str(note) in maps["61keyMap"] or str(note) in maps["88keyMap"]["lowNotes"] or str(note) in maps["88keyMap"]["highNotes"]

def parseMidi(message):
    global sustainActive, activeNotes
    log(str(message))

    if message.type == "control_change":
        if message.control == 64:
            if not configuration.configData["midiPlayer"]["sustain"]:
                return
            if message.value > configuration.configData["midiPlayer"]["sustainCutoff"]:
                sustainActive = True
                if midiOut:
                    midiOut.send(message)
            else:
                sustainActive = False
                if midiOut:
                    midiOut.send(message)
            return

    if message.type in ("note_on", "note_off"):
        noteOffset = configuration.configData["midiPlayer"].get("pitchOffset", 0) + configuration.configData["midiPlayer"].get("transposeOffset", 0)
        note = message.note + noteOffset
        if not noteAllowed(note):
            log(f"out of range: {note}")
            return

        if message.type == "note_on":
            if message.velocity == 0:
                msgType = "note_off"
            else:
                msgType = "note_on"
        else:
            msgType = "note_off"

        if msgType == "note_on":
            if not configuration.configData["midiPlayer"]["velocity"]:
                message.velocity = 78
            if configuration.configData.get("midiPlayer", {}).get("humanize", {}).get("enabled", False):
                jitter = configuration.configData["midiPlayer"]["humanize"].get("velocityJitter", 5.0)
                message.velocity = int(max(1, min(127, message.velocity + random.uniform(-jitter, jitter))))
        elif msgType == "note_off":
            message.velocity = 0

        channel = message.channel if hasattr(message, "channel") else 0
        key = (note, channel)

        if configuration.configData["midiPlayer"]["noDoubles"]:
            if msgType == "note_on" and key in activeNotes:
                log(f"skipped double: note {note} ch {channel}")
                return

        if msgType == "note_on":
            activeNotes.add(key)
        if msgType == "note_off" and key in activeNotes:
            activeNotes.remove(key)

        if midiOut:
            midiOut.send(message)

def playMidiOnce(midiFile, playback_id, startOffset=0.0):
    global sustainActive
    import math
    mid = mido.MidiFile(midiFile, clip=True)
    startTime = time.monotonic()
    playbackStartWall = time.monotonic()
    currentTime = 0
    skipping = startOffset > 0.0

    chase_notes = {}
    chase_sustain = 0
    recent_delays = []
    # For bottom-to-top chord rolling
    chord_notes_in_window = []

    for msg in mid:
        if playback_id != current_playback_id:
            return False

        adjustedDelay = msg.time / playbackSpeed

        if configuration.configData.get("midiPlayer", {}).get("humanize", {}).get("enabled", False) and not msg.is_meta:
            humanize_cfg = configuration.configData["midiPlayer"]["humanize"]

            # --- 1. ENHANCED RUBATO: tempo breathing via sine wave + fast-segment slowdown ---
            if msg.type in ("note_on", "note_off"):
                recent_delays.append(msg.time)
                if len(recent_delays) > 8:
                    recent_delays.pop(0)
                avg_delay = sum(recent_delays) / len(recent_delays)

                # Fast-segment rubato
                rubato_strength = humanize_cfg.get("rubatoStrength", 0.5)
                if avg_delay < 0.12:
                    fast_factor = 1.0 + (0.12 - avg_delay) * rubato_strength * 2.5
                    adjustedDelay *= fast_factor

                # Sine-wave tempo breathing (natural 8-second cycle)
                breath_strength = humanize_cfg.get("breathStrength", 0.04)
                elapsed_wall = time.monotonic() - playbackStartWall
                breath_factor = 1.0 + breath_strength * math.sin(2 * math.pi * elapsed_wall / 8.0)
                adjustedDelay *= breath_factor

            # --- 2. MICRO-TIMING JITTER ---
            jitter_std = humanize_cfg.get("timingJitter", 0.005)
            if jitter_std > 0:
                adjustedDelay += random.gauss(0, jitter_std)
                adjustedDelay = max(0, adjustedDelay)

            # --- 3. IMPROVED CHORD ROLLING: bottom-to-top arpeggiation ---
            if humanize_cfg.get("chordRoll", True) and msg.type == "note_on" and msg.velocity > 0:
                chord_threshold = 0.015
                if msg.time < chord_threshold:
                    chord_notes_in_window.append(msg.note)
                    sorted_chord = sorted(chord_notes_in_window)
                    rank = sorted_chord.index(msg.note)
                    roll_step = humanize_cfg.get("chordRollStep", 0.008)
                    adjustedDelay += rank * roll_step
                else:
                    chord_notes_in_window = [msg.note]

            # --- 4. NOTE-OFF DURATION JITTER (legato/staccato variation) ---
            if msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                off_jitter_std = humanize_cfg.get("noteOffJitter", 0.004)
                if off_jitter_std > 0:
                    adjustedDelay += random.gauss(0, off_jitter_std)
                    adjustedDelay = max(0, adjustedDelay)

        elif configuration.configData["midiPlayer"]["randomFail"]["enabled"] and not msg.is_meta:
            if random.random() < configuration.configData["midiPlayer"]["randomFail"]["speed"] / 100:
                adjustedDelay *= random.uniform(0.5, 1.5)

        currentTime += adjustedDelay

        # Skip messages before seek offset
        if skipping:
            if msg.type == "note_on":
                if msg.velocity > 0:
                    chase_notes[msg.note] = msg.velocity
                else:
                    chase_notes.pop(msg.note, None)
            elif msg.type == "note_off":
                chase_notes.pop(msg.note, None)
            elif msg.type == "control_change" and msg.control == 64:
                chase_sustain = msg.value

            if currentTime < startOffset:
                continue
            else:
                skipping = False
                startTime = time.monotonic() - currentTime

                # Chase active notes and sustain state
                if chase_sustain > configuration.configData["midiPlayer"]["sustainCutoff"]:
                    sustainMsg = mido.Message("control_change", control=64, value=chase_sustain)
                    parseMidi(sustainMsg)
                for note, velocity in chase_notes.items():
                    noteMsg = mido.Message("note_on", note=note, velocity=velocity)
                    parseMidi(noteMsg)

        targetTime = startTime + currentTime

        while time.monotonic() < targetTime:
            if playback_id != current_playback_id:
                return False
            while paused and playback_id == current_playback_id:
                pauseStart = time.monotonic()
                time.sleep(0.05)
                delta = time.monotonic() - pauseStart
                startTime += delta
                targetTime += delta
            remaining = targetTime - time.monotonic()
            if remaining > 0:
                time.sleep(min(remaining, 0.005))

        if msg.is_meta:
            continue

        if hasattr(msg, "note"):
            n = msg.note

            if not noteAllowed(n):
                log(f"out of range: {n}")
                continue

            if msg.type == "note_on" and msg.velocity > 0:
                is_human_fail = False
                fail_chance = 0.0
                if configuration.configData.get("midiPlayer", {}).get("humanize", {}).get("enabled", False):
                    is_human_fail = True
                    fail_chance = configuration.configData["midiPlayer"]["randomFail"].get("transpose", 5.0) / 100
                elif configuration.configData["midiPlayer"]["randomFail"]["enabled"]:
                    fail_chance = configuration.configData["midiPlayer"]["randomFail"]["transpose"] / 100

                if fail_chance > 0 and random.random() < fail_chance:
                    if is_human_fail:
                        # --- 5. REALISTIC FAILS: mostly adjacent keys (±1/±2 semitones) ---
                        r = random.random()
                        if r < 0.55:
                            delta = random.choice([-1, 1])   # adjacent key (most common)
                        elif r < 0.80:
                            delta = random.choice([-2, 2])   # two semitones
                        elif r < 0.92:
                            delta = random.choice([-3, 3])   # three semitones
                        else:
                            delta = random.choice([-12, 12]) # octave (rare)
                    else:
                        delta = random.randint(-12, 12)
                    newNote = n + delta
                    if not noteAllowed(newNote):
                        log(f"out of range: {newNote}")
                        continue
                    if n not in activeTransposedNotes:
                        activeTransposedNotes[n] = []
                    activeTransposedNotes[n].append(newNote)
                    original = msg.note
                    msg.note = newNote
                    parseMidi(msg)
                    msg.note = original
                    continue

                # --- 5b. DYNAMIC VELOCITY SHAPING: emphasise higher pitches slightly ---
                if configuration.configData.get("midiPlayer", {}).get("humanize", {}).get("enabled", False):
                    humanize_cfg2 = configuration.configData["midiPlayer"]["humanize"]
                    vel_shape = humanize_cfg2.get("velocityShaping", 0.3)
                    if vel_shape > 0:
                        pitch_bias = (msg.note - 60) / 60.0
                        velocity_delta = int(pitch_bias * vel_shape * 12)
                        msg.velocity = max(1, min(127, msg.velocity + velocity_delta))

            if msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                if n in activeTransposedNotes and activeTransposedNotes[n]:
                    transNote = activeTransposedNotes[n].pop(0)
                    if not activeTransposedNotes[n]:
                        del activeTransposedNotes[n]
                    if noteAllowed(transNote):
                        original = msg.note
                        msg.note = transNote
                        parseMidi(msg)
                        msg.note = original
                    else:
                        log(f"out of range: {transNote}")
                    continue

        parseMidi(msg)

    return True

_startOffset = 0.0

def playMidiFile(midiFile, playback_id):
    global _startOffset
    log("nanoMIDI Direct MIDI Out v1.0")
    log(f"Playing MIDI file: {midiFile}")
    offset = _startOffset
    _startOffset = 0.0

    while playback_id == current_playback_id:
        finished = playMidiOnce(midiFile, playback_id, startOffset=offset)
        offset = 0.0

        if playback_id != current_playback_id:
            break

        if not finished:
            break

        if not configuration.configData["midiPlayer"]["loopSong"]:
            from modules.functions.midiPlayerFunctions import stopPlayback
            stopPlayback()

def formatTime(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:0}:{minutes:02}:{secs:02}"

def clockThread(totalSeconds, playback_id, updateCallback=None, startOffset=0.0):
    global playbackSpeed, paused
    currentSeconds = startOffset
    while playback_id == current_playback_id:
        if not paused:
            shown = min(currentSeconds, totalSeconds)
            formattedTime = f"{formatTime(shown)} / {formatTime(totalSeconds)}"
            if updateCallback:
                updateCallback(formattedTime, shown, totalSeconds)
            else:
                log(formattedTime)
            currentSeconds += 1
            for _ in range(10):
                if playback_id != current_playback_id:
                    break
                time.sleep(0.1 / playbackSpeed)
        else:
            time.sleep(0.1)

def startPlayback(midiFile, outputDevice, updateCallback=None, startOffset=0.0):
    global playThread, clockThreadRef, paused, midiOut, _startOffset, current_playback_id
    current_playback_id += 1
    my_playback_id = current_playback_id

    paused = False
    _startOffset = startOffset
    
    # Close old midiOut asynchronously to avoid GUI freeze
    if midiOut:
        old_midiOut = midiOut
        try:
            threading.Thread(target=old_midiOut.close, daemon=True).start()
        except:
            pass
        midiOut = None

    midiOut = mido.open_output(outputDevice)
    totalSeconds = mido.MidiFile(midiFile, clip=True).length
    playThread = threading.Thread(target=playMidiFile, args=(midiFile, my_playback_id), daemon=True)
    clockThreadRef = threading.Thread(target=clockThread, args=(totalSeconds, my_playback_id, updateCallback, startOffset), daemon=True)
    clockThreadRef.start()
    playThread.start()

def pausePlayback():
    global paused, sustainActive
    paused = not paused
    
    if paused and configuration.configData["midiPlayer"]["releaseOnPause"]:
        if midiOut:
            for note, channel in list(activeNotes):
                try:
                    midiOut.send(mido.Message("note_off", note=note, velocity=0, channel=channel))
                    activeNotes.remove((note, channel))
                except:
                    pass
            
            if sustainActive:
                sustainOff = mido.Message("control_change", control=64, value=0)
                midiOut.send(sustainOff)
                sustainActive = False
    
    log("Playback paused." if paused else "Playback resumed.")

def changeSpeed(amount):
    global playbackSpeed
    playbackSpeed = max(0.1, min(5.0, playbackSpeed + amount))
    log(f"Speed: {playbackSpeed * 100:.0f}%")

def stopPlayback():
    global current_playback_id, timerList, midiOut, activeNotes
    current_playback_id += 1
    for t in list(timerList):
        try:
            t.cancel()
        except:
            pass
    timerList.clear()
    if midiOut:
        old_midiOut = midiOut
        try:
            for note, channel in list(activeNotes):
                old_midiOut.send(mido.Message("note_off", note=note, velocity=0, channel=channel))
            activeNotes.clear()
            threading.Thread(target=old_midiOut.close, daemon=True).start()
        except:
            pass
        midiOut = None
    log("Playback fully stopped.")