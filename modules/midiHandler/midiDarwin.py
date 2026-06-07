import re
import keyboard
import mido
import os
import threading
import time
import random

from pynput import keyboard as pynputKeyboard
from modules.functions import mainFunctions
from modules import configuration

pressedKeys = set()
heldKeys = set()
heldKeysOrdered = []
activeTransposedNotes = {}

log = mainFunctions.log

def logKeys(action, key):
    if isinstance(key, pynputKeyboard.Key):
        keyName = key.name if key.name else str(key)
    else:
        keyName = str(key)
    if action == "press":
        pressedKeys.add(keyName)
    elif action == "release" and keyName in pressedKeys:
        pressedKeys.remove(keyName)
    if pressedKeys:
        log(f"{action}: {'+'.join(sorted(pressedKeys))}")
    else:
        log(f"{action}: {keyName}")

specialKeyMap = {
    "shift": pynputKeyboard.Key.shift,
    "ctrl": pynputKeyboard.Key.ctrl,
    "alt": pynputKeyboard.Key.alt,
    "space": pynputKeyboard.Key.space
}

pynputController = pynputKeyboard.Controller()
blockedKeys = {f"f{i}" for i in range(1, 13)} | {"tab", "backspace", "esc"}

def translateKey(key):
    keyLower = key.lower() if isinstance(key, str) else key
    if isinstance(keyLower, str) and keyLower in specialKeyMap:
        return specialKeyMap[keyLower]
    elif isinstance(keyLower, str) and len(keyLower) == 1:
        return keyLower
    elif isinstance(key, pynputKeyboard.Key):
        return key
    else:
        raise ValueError(f"Unsupported key: {key}")

def isBlockedKey(keyObj):
    if isinstance(keyObj, str):
        return keyObj.lower() in blockedKeys
    if isinstance(keyObj, pynputKeyboard.Key):
        name = getattr(keyObj, "name", None)
        if isinstance(name, str) and name.lower() in blockedKeys:
            return True
        s = str(keyObj).lower()
        if s.startswith("key.f") and any(s.startswith(f"key.f{i}") for i in range(1, 13)):
            return True
        return False
    return False

def press(key):
    keyObj = translateKey(key)
    if isinstance(keyObj, str) and (keyObj.isdigit() or keyObj in ["ctrl", "shift"]):
        keyboard.press(keyObj)
        logKeys("press", keyObj)
        if keyObj not in heldKeysOrdered:
            heldKeysOrdered.append(keyObj)
    else:
        if isBlockedKey(keyObj):
            return
        pynputController.press(keyObj)
        logKeys("press", keyObj)
        heldKeys.add(keyObj)
        if keyObj not in heldKeysOrdered:
            heldKeysOrdered.append(keyObj)

def release(key):
    keyObj = translateKey(key)
    if isinstance(keyObj, str) and (keyObj.isdigit() or keyObj in ["ctrl", "shift"]):
        keyboard.release(keyObj)
        logKeys("release", keyObj)
        if keyObj in heldKeysOrdered:
            try:
                heldKeysOrdered.remove(keyObj)
            except ValueError:
                pass
    else:
        if isBlockedKey(keyObj):
            return
        pynputController.release(keyObj)
        logKeys("release", keyObj)
        if keyObj in heldKeys:
            heldKeys.remove(keyObj)
        if keyObj in heldKeysOrdered:
            try:
                heldKeysOrdered.remove(keyObj)
            except ValueError:
                pass

stopEvent = threading.Event()
clockThreadRef = None
keyboardHandlers = []
timerList = []

closeThread = False
paused = False
playThread = None
playbackSpeed = 1.0
sustainActive = False
heldNoteCount = 0

def getPianoFingerLimit():
    return int(configuration.configData.get("midiPlayer", {}).get("fingerLimit", 11))

def findVelocityKey(velocity):
    velocityMap = configuration.configData["midiPlayer"]["pianoMap"]["velocityMap"]
    thresholds = sorted(int(k) for k in velocityMap.keys())
    minimum = 0
    maximum = len(thresholds) - 1
    index = 0
    while minimum <= maximum:
        index = (minimum + maximum) // 2
        if index == 0 or index == len(thresholds) - 1:
            break
        if thresholds[index] < velocity:
            minimum = index + 1
        else:
            maximum = index - 1
    return velocityMap[str(thresholds[index])]

def pressAndMaybeRelease(key):
    global heldNoteCount
    limit = getPianoFingerLimit()
    if limit <= 10 and heldNoteCount >= limit:
        if heldKeysOrdered:
            oldest = heldKeysOrdered[0]
            log(f"Finger limit ({limit}) reached, releasing oldest: {oldest}")
            release(oldest)
            heldNoteCount = max(0, heldNoteCount - 1)
        else:
            log(f"Finger limit ({limit}) reached, skipping note")
            return
    heldNoteCount += 1
    press(key)
    if configuration.configData["midiPlayer"]["customHoldLength"]["enabled"]:
        def _timerRelease():
            global heldNoteCount
            release(key)
            heldNoteCount = max(0, heldNoteCount - 1)
        t = threading.Timer(configuration.configData["midiPlayer"]["customHoldLength"]["noteLength"], _timerRelease)
        timerList.append(t)
        t.start()

def simulateKey(msgType, note, velocity):
    allow88 = configuration.configData["midiPlayer"]["88Keys"]

    letterNoteMap = configuration.configData["midiPlayer"]["pianoMap"]["61keyMap"]
    lowNotes = configuration.configData["midiPlayer"]["pianoMap"]["88keyMap"]["lowNotes"]
    highNotes = configuration.configData["midiPlayer"]["pianoMap"]["88keyMap"]["highNotes"]

    if not allow88:
        if str(note) not in letterNoteMap:
            log(f"out of range: {note}")
            return
    else:
        if str(note) not in letterNoteMap and str(note) not in lowNotes and str(note) not in highNotes:
            log(f"out of range: {note}")
            return

    if str(note) in letterNoteMap:
        key = letterNoteMap[str(note)]
    elif allow88 and str(note) in lowNotes:
        key = lowNotes[str(note)]
    elif allow88 and str(note) in highNotes:
        key = highNotes[str(note)]
    else:
        log(f"out of range: {note}")
        return

    if msgType == "note_on":
        if configuration.configData["midiPlayer"]["velocity"]:
            if configuration.configData.get("midiPlayer", {}).get("humanize", {}).get("enabled", False):
                jitter = configuration.configData["midiPlayer"]["humanize"].get("velocityJitter", 5.0)
                velocity = int(max(1, min(127, velocity + random.uniform(-jitter, jitter))))
            velocityKey = findVelocityKey(velocity)
            press("alt")
            press(velocityKey)
            release(velocityKey)
            release("alt")

        if 36 <= note <= 96:
            if configuration.configData["midiPlayer"]["noDoubles"]:
                if re.search("[!@$%^*(]", key):
                    release(letterNoteMap[str(note - 1)])
                else:
                    release(key.lower())
            if re.search("[!@$%^*(]", key):
                press("shift")
                pressAndMaybeRelease(letterNoteMap[str(note - 1)])
                release("shift")
            elif key.isupper():
                press("shift")
                pressAndMaybeRelease(key.lower())
                release("shift")
            else:
                pressAndMaybeRelease(key)
        else:
            release(key.lower())
            press("ctrl")
            pressAndMaybeRelease(key.lower())
            release("ctrl")

    elif msgType == "note_off":
        global heldNoteCount
        if 36 <= note <= 96:
            if re.search("[!@$%^*(]", key):
                release(letterNoteMap[str(note - 1)])
            else:
                release(key.lower())
        else:
            release(key.lower())
        heldNoteCount = max(0, heldNoteCount - 1)
        if not sustainActive and message.value > configuration.configData["midiPlayer"]["sustainCutoff"]:
            sustainActive = True
            press("space")
        elif sustainActive and message.value < configuration.configData["midiPlayer"]["sustainCutoff"]:
            sustainActive = False
            release("space")
    elif message.type in ("note_on", "note_off"):
        try:
            if message.velocity == 0:
                simulateKey("note_off", message.note, message.velocity)
            else:
                simulateKey(message.type, message.note, message.velocity)
        except IndexError:
            pass
    return sustainActive

def playMidiOnce(midiFile, startOffset=0.0):
    global sustainActive, paused
    mid = mido.MidiFile(midiFile, clip=True)
    startTime = time.monotonic()
    currentTime = 0
    wasPaused = False
    skipping = startOffset > 0.0

    chase_notes = {}
    chase_sustain = 0
    recent_delays = []

    for msg in mid:
        if stopEvent.is_set() or closeThread:
            return False

        adjustedDelay = msg.time / playbackSpeed
        
        if configuration.configData.get("midiPlayer", {}).get("humanize", {}).get("enabled", False) and not msg.is_meta:
            humanize_cfg = configuration.configData["midiPlayer"]["humanize"]
            
            # 1. Rubato: slowing down slightly during fast segments
            if msg.type in ("note_on", "note_off"):
                recent_delays.append(msg.time)
                if len(recent_delays) > 5:
                    recent_delays.pop(0)
                avg_delay = sum(recent_delays) / len(recent_delays)
                if avg_delay < 0.1:  # playing fast
                    rubato_strength = humanize_cfg.get("rubatoStrength", 0.5)
                    factor = 1.0 + (0.1 - avg_delay) * rubato_strength * 3.0
                    adjustedDelay *= factor

            # 2. Micro-timing jitter (small random variance in timing)
            jitter_std = humanize_cfg.get("timingJitter", 0.005)
            if jitter_std > 0:
                adjustedDelay += random.gauss(0, jitter_std)
                adjustedDelay = max(0, adjustedDelay)
                
            # 3. Chord rolling (adds a tiny sleep/offset if notes are virtually simultaneous)
            if humanize_cfg.get("chordRoll", True) and msg.type == "note_on" and msg.velocity > 0:
                if msg.time < 0.005:
                    adjustedDelay += random.uniform(0.005, 0.015)

        elif configuration.configData["midiPlayer"]["randomFail"]["enabled"] and not msg.is_meta:
            if random.random() < configuration.configData["midiPlayer"]["randomFail"]["speed"] / 100:
                speedFactor = random.uniform(0.5, 1.5)
                adjustedDelay *= speedFactor

        currentTime += adjustedDelay

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
            if stopEvent.is_set() or closeThread:
                return False
            
            if paused and not wasPaused:
                wasPaused = True
                if configuration.configData["midiPlayer"]["releaseOnPause"]:
                    for key in list(heldKeys):
                        release(key)
                    if sustainActive:
                        release("space")
                        sustainActive = False
            
            if not paused and wasPaused:
                wasPaused = False

            while paused and not (stopEvent.is_set() or closeThread):
                pauseStart = time.monotonic()
                time.sleep(0.05)
                pauseDuration = time.monotonic() - pauseStart
                startTime += pauseDuration
                targetTime += pauseDuration
            
            remaining = targetTime - time.monotonic()
            if remaining > 0:
                sleepChunk = min(remaining, 0.005)
                time.sleep(sleepChunk)
                
        if msg.is_meta:
            continue
        
        if paused:
            if msg.type == "control_change" and msg.control == 64:
                if not configuration.configData["midiPlayer"]["sustain"]:
                    continue
                if msg.value > configuration.configData["midiPlayer"]["sustainCutoff"]:
                    sustainActive = True
                else:
                    sustainActive = False
            continue
        
        if hasattr(msg, "note"):
            _noteOffset = configuration.configData["midiPlayer"].get("pitchOffset", 0) + configuration.configData["midiPlayer"].get("transposeOffset", 0)
            if _noteOffset != 0:
                msg.note += _noteOffset
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
                        r = random.random()
                        if r < 0.6:
                            delta = random.choice([-1, 1])
                        elif r < 0.8:
                            delta = random.choice([-2, 2])
                        else:
                            delta = random.choice([-12, 12])
                    else:
                        delta = random.randint(-12, 12)
                    newNote = msg.note + delta
                    if msg.note not in activeTransposedNotes:
                        activeTransposedNotes[msg.note] = []
                    activeTransposedNotes[msg.note].append(newNote)
                    original = msg.note
                    msg.note = newNote
                    parseMidi(msg)
                    msg.note = original
                    continue
            if msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                if msg.note in activeTransposedNotes and activeTransposedNotes[msg.note]:
                    transNote = activeTransposedNotes[msg.note].pop(0)
                    if not activeTransposedNotes[msg.note]:
                        del activeTransposedNotes[msg.note]
                    original = msg.note
                    msg.note = transNote
                    parseMidi(msg)
                    msg.note = original
                    continue
                
        parseMidi(msg)
    
    return True

_startOffset = 0.0

def playMidiFile(midiFile):
    global _startOffset
    log("nanoMIDI Mid2VK Translator v3.0")
    log(f"Playing MIDI file: {midiFile}")
    offset = _startOffset
    _startOffset = 0.0
    while not (stopEvent.is_set() or closeThread):
        finished = playMidiOnce(midiFile, startOffset=offset)
        offset = 0.0
        if not configuration.configData["midiPlayer"]["loopSong"] or not finished or stopEvent.is_set() or closeThread:
            break
        for key in list(heldKeys):
            release(key)

    if not configuration.configData["midiPlayer"]["loopSong"]:
        from modules.functions.midiPlayerFunctions import stopPlayback
        stopPlayback()

def formatTime(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:0}:{minutes:02}:{secs:02}"

def clockThread(totalSeconds, updateCallback=None, startOffset=0.0):
    global closeThread, playbackSpeed, paused
    currentSeconds = startOffset
    while not (stopEvent.is_set() or closeThread):
        if not paused:
            shown = min(currentSeconds, totalSeconds)
            formattedTime = f"{formatTime(shown)} / {formatTime(totalSeconds)}"
            if configuration.configData['appUI']['timestamp']:
                if updateCallback:
                    updateCallback(formattedTime, shown, totalSeconds)
                else:
                    log(formattedTime)
            currentSeconds += 1
            for _ in range(10):
                if stopEvent.is_set() or closeThread:
                    break
                time.sleep(0.1 / playbackSpeed)
        else:
            time.sleep(0.1)

def startPlayback(midiFile, updateCallback=None, startOffset=0.0):
    global playThread, stopEvent, clockThreadRef, closeThread, paused, _startOffset
    if playThread is not None and isinstance(playThread, threading.Thread) and playThread.is_alive():
        stopEvent.set()
        closeThread = True
        playThread.join(timeout=1.5)
        if clockThreadRef is not None and isinstance(clockThreadRef, threading.Thread):
            clockThreadRef.join(timeout=1.5)

    stopEvent.clear()
    closeThread = False
    paused = False
    _startOffset = startOffset
    totalSeconds = mido.MidiFile(midiFile, clip=True).length
    playThread = threading.Thread(target=playMidiFile, args=(midiFile,), daemon=True)
    clockThreadRef = threading.Thread(target=clockThread, args=(totalSeconds, updateCallback, startOffset), daemon=True)
    clockThreadRef.start()
    playThread.start()

def pausePlayback():
    global paused, sustainActive
    paused = not paused
    
    if paused:
        if configuration.configData["midiPlayer"]["releaseOnPause"]:
            for key in list(heldKeys):
                release(key)
            if sustainActive:
                release("space")
                sustainActive = False
    
    log("Playback paused." if paused else "Playback resumed.")

def changeSpeed(amount):
    global playbackSpeed
    playbackSpeed = max(0.1, min(5.0, playbackSpeed + amount))
    log(f"Speed: {playbackSpeed * 100:.0f}%")

def stopPlayback():
    global closeThread, stopEvent, playThread, clockThreadRef, keyboardHandlers, timerList, heldNoteCount
    if closeThread or stopEvent.is_set():
        return
    
    stopEvent.set()
    closeThread = True
    heldNoteCount = 0
    for key in list(heldKeys):
        try:
            release(key)
        except Exception:
            pass
    for t in list(timerList):
        try:
            t.cancel()
        except Exception:
            pass
    timerList.clear()
    try:
        for h in list(keyboardHandlers):
            try:
                keyboard.unhook(h)
            except Exception:
                pass
        keyboardHandlers.clear()
    except Exception:
        pass
    if playThread is not None and isinstance(playThread, threading.Thread):
        try:
            playThread.join(timeout=1.0)
        except Exception:
            pass
    if clockThreadRef is not None and isinstance(clockThreadRef, threading.Thread):
        try:
            clockThreadRef.join(timeout=1.0)
        except Exception:
            pass
    log("Playback fully stopped.")