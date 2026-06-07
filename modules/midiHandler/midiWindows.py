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

# --- win32msg helpers ---
try:
    import win32api
    import win32con
    import win32gui
    _win32Available = True
except ImportError:
    _win32Available = False

_VK_MAP = {
    **{ch: ord(ch.upper()) for ch in 'abcdefghijklmnopqrstuvwxyz'},
    **{str(d): ord(str(d)) for d in range(10)},
    'space': win32con.VK_SPACE if _win32Available else 0x20,
    'shift': win32con.VK_SHIFT if _win32Available else 0x10,
    'ctrl':  win32con.VK_CONTROL if _win32Available else 0x11,
    'alt':   win32con.VK_MENU if _win32Available else 0x12,
    'up':    win32con.VK_UP if _win32Available else 0x26,
    'down':  win32con.VK_DOWN if _win32Available else 0x28,
    'left':  win32con.VK_LEFT if _win32Available else 0x25,
    'right': win32con.VK_RIGHT if _win32Available else 0x27,
    # Shift symbols → base key VK
    '!': ord('1'), '@': ord('2'), '#': ord('3'), '$': ord('4'),
    '%': ord('5'), '^': ord('6'), '&': ord('7'), '*': ord('8'),
    '(': ord('9'), ')': ord('0'),
    # Extra keys used by 50-key map
    '-': 0xBD, '=': 0xBB, '[': 0xDB, ']': 0xDD,
    '\\': 0xDC, ';': 0xBA, "'": 0xDE, ',': 0xBC,
    '.': 0xBE, '/': 0xBF,
}
_NEEDS_SHIFT_MIDI = set('!@#$%^&*()ABCDEFGHIJKLMNOPQRSTUVWXYZ')

def _getMidiTargetHwnd():
    if not _win32Available:
        return None
    title = configuration.configData.get('midiPlayer', {}).get('targetWindow', '')
    if not title:
        return None
    hwnd = win32gui.FindWindow(None, title)
    return hwnd if hwnd else None

def listOpenWindowsMidi():
    titles = []
    if not _win32Available:
        return titles
    def _enum(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title and title.strip():
                titles.append(title)
    win32gui.EnumWindows(_enum, None)
    return sorted(set(titles))

pressedKeys = set()
heldKeys = set()
heldKeysOrdered = []
activeTransposedNotes = {}
active_modifiers = {"up": 0, "down": 0, "right shift": 0}

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
    "space": pynputKeyboard.Key.space,
    "up": pynputKeyboard.Key.up,
    "down": pynputKeyboard.Key.down,
    "left": pynputKeyboard.Key.left,
    "right": pynputKeyboard.Key.right,
    "right shift": pynputKeyboard.Key.shift_r
}

# ── keyboard implementation ──────────────────────────────────────
def _press_keyboard(key):
    keyboard.press(key)
    logKeys("press", key)
    if key not in heldKeysOrdered:
        heldKeysOrdered.append(key)

def _release_keyboard(key):
    keyboard.release(key)
    logKeys("release", key)
    if key in heldKeysOrdered:
        try:
            heldKeysOrdered.remove(key)
        except ValueError:
            pass

# ── pynput implementation ────────────────────────────────────────
_pynputController = None
_blockedKeys = {f"f{i}" for i in range(1, 13)} | {"tab", "backspace", "esc"}

def _getPynputController():
    global _pynputController
    if _pynputController is None:
        _pynputController = pynputKeyboard.Controller()
    return _pynputController

def _translateKey(key):
    keyLower = key.lower() if isinstance(key, str) else key
    if isinstance(keyLower, str) and keyLower in specialKeyMap:
        return specialKeyMap[keyLower]
    elif isinstance(keyLower, str) and len(keyLower) == 1:
        return keyLower
    elif isinstance(key, pynputKeyboard.Key):
        return key
    else:
        raise ValueError(f"Unsupported key for pynput: {key}")

def _isBlockedKey(keyObj):
    if isinstance(keyObj, str):
        return keyObj.lower() in _blockedKeys
    if isinstance(keyObj, pynputKeyboard.Key):
        name = getattr(keyObj, "name", None)
        if isinstance(name, str) and name.lower() in _blockedKeys:
            return True
        s = str(keyObj).lower()
        if s.startswith("key.f") and any(s.startswith(f"key.f{i}") for i in range(1, 13)):
            return True
        return False
    return False

def _press_pynput(key):
    keyObj = _translateKey(key)
    if _isBlockedKey(keyObj):
        return
    _getPynputController().press(keyObj)
    logKeys("press", keyObj)
    heldKeys.add(keyObj)
    if keyObj not in heldKeysOrdered:
        heldKeysOrdered.append(keyObj)

def _release_pynput(key):
    keyObj = _translateKey(key)
    if _isBlockedKey(keyObj):
        return
    _getPynputController().release(keyObj)
    logKeys("release", keyObj)
    if keyObj in heldKeys:
        heldKeys.remove(keyObj)
    if keyObj in heldKeysOrdered:
        try:
            heldKeysOrdered.remove(keyObj)
        except ValueError:
            pass

# ── win32msg implementation ──────────────────────────────────────
_shiftDownMidi = False

def _postKeyMidi(vk, down):
    hwnd = _getMidiTargetHwnd()
    if not hwnd or not _win32Available:
        log("win32msg: no target window found")
        return
    scanCode = win32api.MapVirtualKey(vk, 0)
    
    # Determine if extended key (like Arrows, R-Ctrl, Alt)
    isExtended = vk in (win32con.VK_UP, win32con.VK_DOWN, win32con.VK_LEFT, win32con.VK_RIGHT, win32con.VK_MENU, win32con.VK_CONTROL)
    extendedBit = 1 if isExtended else 0
    
    if down:
        # Key down flags:
        # Bit 31 (Transition): 0
        # Bit 30 (Previous state): 0
        # Bit 29 (Context): 0
        # Bit 24 (Extended): extendedBit
        # Bit 16-23: scanCode
        # Bit 0-15: 1 (repeat count)
        lParam = 1 | (scanCode << 16) | (extendedBit << 24)
        win32api.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, lParam)
    else:
        # Key up flags:
        # Bit 31 (Transition): 1
        # Bit 30 (Previous state): 1
        # Bit 29 (Context): 0
        # Bit 24 (Extended): extendedBit
        # Bit 16-23: scanCode
        # Bit 0-15: 1 (repeat count)
        lParam = 1 | (scanCode << 16) | (extendedBit << 24) | (1 << 30) | (1 << 31)
        win32api.PostMessage(hwnd, win32con.WM_KEYUP, vk, lParam)

def _press_win32msg(key):
    global _shiftDownMidi
    keyStr = str(key)
    if keyStr.lower() == 'shift':
        if not _shiftDownMidi:
            _shiftDownMidi = True
            _postKeyMidi(_VK_MAP['shift'], True)
        logKeys("press", key)
        return
    if keyStr.lower() in ('ctrl', 'right shift'):
        _postKeyMidi(_VK_MAP.get(keyStr.lower(), _VK_MAP['ctrl']), True)
        logKeys("press", key)
        return
    if keyStr.lower() == 'alt':
        _postKeyMidi(_VK_MAP['alt'], True)
        logKeys("press", key)
        return
    if keyStr.lower() in ('up', 'down', 'left', 'right'):
        vk = _VK_MAP.get(keyStr.lower())
        if vk:
            _postKeyMidi(vk, True)
            logKeys("press", key)
        return
    vk = _VK_MAP.get(keyStr)
    if vk is None:
        log(f"win32msg: no VK for '{keyStr}'")
        return
    needShift = keyStr in _NEEDS_SHIFT_MIDI
    if needShift and not _shiftDownMidi:
        _postKeyMidi(_VK_MAP['shift'], True)
    _postKeyMidi(vk, True)
    logKeys("press", key)
    heldKeys.add(keyStr)
    if keyStr not in heldKeysOrdered:
        heldKeysOrdered.append(keyStr)

def _release_win32msg(key):
    global _shiftDownMidi
    keyStr = str(key)
    if keyStr.lower() == 'shift':
        if _shiftDownMidi:
            _shiftDownMidi = False
            _postKeyMidi(_VK_MAP['shift'], False)
        logKeys("release", key)
        return
    if keyStr.lower() in ('ctrl', 'right shift'):
        _postKeyMidi(_VK_MAP.get(keyStr.lower(), _VK_MAP['ctrl']), False)
        logKeys("release", key)
        return
    if keyStr.lower() == 'alt':
        _postKeyMidi(_VK_MAP['alt'], False)
        logKeys("release", key)
        return
    if keyStr.lower() in ('up', 'down', 'left', 'right'):
        vk = _VK_MAP.get(keyStr.lower())
        if vk:
            _postKeyMidi(vk, False)
            logKeys("release", key)
        return
    vk = _VK_MAP.get(keyStr)
    if vk is None:
        return
    needShift = keyStr in _NEEDS_SHIFT_MIDI
    _postKeyMidi(vk, False)
    if needShift and not _shiftDownMidi:
        _postKeyMidi(_VK_MAP['shift'], False)
    logKeys("release", key)
    if keyStr in heldKeys:
        heldKeys.remove(keyStr)
    if keyStr in heldKeysOrdered:
        try:
            heldKeysOrdered.remove(keyStr)
        except ValueError:
            pass

# ── dynamic dispatcher (reads config on every call) ──────────────
def press(key):
    module = configuration.configData.get("midiPlayer", {}).get("inputModule", "pynput")
    if module == "keyboard":
        _press_keyboard(key)
    elif module == "win32msg":
        _press_win32msg(key)
    else:
        _press_pynput(key)

def release(key):
    module = configuration.configData.get("midiPlayer", {}).get("inputModule", "pynput")
    if module == "keyboard":
        _release_keyboard(key)
    elif module == "win32msg":
        _release_win32msg(key)
    else:
        _release_pynput(key)

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
current_playback_id = 0

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
    global heldNoteCount, active_modifiers
    note = note + configuration.configData["midiPlayer"].get("pitchOffset", 0) + configuration.configData["midiPlayer"].get("transposeOffset", 0)

    if configuration.configData.get("midiPlayer", {}).get("use50Keys", False):
        while note < 36:
            note += 12
        while note > 85:
            note -= 12

        fiftyKeyMap = {
            36: "1", 37: "2", 38: "3", 39: "4", 40: "5", 41: "6", 42: "7", 43: "8", 44: "9", 45: "0", 46: "-", 47: "=",
            48: "q", 49: "w", 50: "e", 51: "r", 52: "t", 53: "y", 54: "u", 55: "i", 56: "o", 57: "p", 58: "[", 59: "]",
            60: "\\", 61: "a", 62: "s", 63: "d", 64: "f", 65: "g", 66: "h", 67: "j", 68: "k", 69: "l", 70: ";", 71: "'",
            72: "z", 73: "x", 74: "c", 75: "v", 76: "b", 77: "n", 78: "m", 79: ",", 80: ".", 81: "/", 82: "up", 83: "down",
            84: "left", 85: "right"
        }
        key = fiftyKeyMap[note]

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

            pressAndMaybeRelease(key)

        elif msgType == "note_off":
            release(key)
            heldNoteCount = max(0, heldNoteCount - 1)
        return

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
        if 36 <= note <= 96:
            if re.search("[!@$%^*(]", key):
                release(letterNoteMap[str(note - 1)])
            else:
                release(key.lower())
        else:
            release(key.lower())
        heldNoteCount = max(0, heldNoteCount - 1)

def parseMidi(message):
    global sustainActive
    if message.type == "control_change" and configuration.configData["midiPlayer"]["sustain"]:
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

def playMidiOnce(midiFile, playback_id, startOffset=0.0):
    global sustainActive, paused
    import math
    mid = mido.MidiFile(midiFile, clip=True)
    startTime = time.monotonic()
    playbackStartWall = time.monotonic()
    currentTime = 0
    wasPaused = False
    skipping = startOffset > 0.0

    chase_notes = {}
    chase_sustain = 0
    recent_delays = []
    # For bottom-to-top chord rolling: track last note_on time and min pitch in chord
    last_noteon_time = -1.0
    chord_notes_in_window = []  # list of pitches in current simultaneous chord

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

                # Fast-segment rubato (slow down slightly when notes are dense)
                rubato_strength = humanize_cfg.get("rubatoStrength", 0.5)
                if avg_delay < 0.12:
                    fast_factor = 1.0 + (0.12 - avg_delay) * rubato_strength * 2.5
                    adjustedDelay *= fast_factor

                # Sine-wave tempo breathing (slow/fast with a natural 8-second cycle)
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
                chord_threshold = 0.015  # notes within 15ms are considered a chord
                if msg.time < chord_threshold:
                    # New note in an existing chord window
                    chord_notes_in_window.append(msg.note)
                    # Position in chord: higher pitch = later attack
                    # Sort the window to find this note's rank (0=bass, highest=treble)
                    sorted_chord = sorted(chord_notes_in_window)
                    rank = sorted_chord.index(msg.note)
                    roll_step = humanize_cfg.get("chordRollStep", 0.008)  # seconds per note
                    adjustedDelay += rank * roll_step
                else:
                    # New chord group, reset tracker
                    chord_notes_in_window = [msg.note]

            # --- 4. NOTE-OFF DURATION JITTER (legato/staccato variation) ---
            # Slightly vary when note_off events fire to simulate imprecise release timing
            if msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                off_jitter_std = humanize_cfg.get("noteOffJitter", 0.004)
                if off_jitter_std > 0:
                    adjustedDelay += random.gauss(0, off_jitter_std)
                    adjustedDelay = max(0, adjustedDelay)

        elif configuration.configData["midiPlayer"]["randomFail"]["enabled"] and not msg.is_meta:
            if random.random() < configuration.configData["midiPlayer"]["randomFail"]["speed"] / 100:
                speedFactor = random.uniform(0.5, 1.5)
                adjustedDelay *= speedFactor

        currentTime += adjustedDelay

        # Skip messages that occur before the seek offset
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
                # Recalibrate start so the remaining time flows naturally
                startTime = time.monotonic() - currentTime

                # Chase/Trigger sustained notes and pedal state at the seek position
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

            while paused and playback_id == current_playback_id:
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
                            delta = random.choice([-1, 1])   # adjacent key (most common slip)
                        elif r < 0.80:
                            delta = random.choice([-2, 2])   # two semitones (less common)
                        elif r < 0.92:
                            delta = random.choice([-3, 3])   # whole step + one more
                        else:
                            delta = random.choice([-12, 12]) # octave slip (rare)
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

                # --- 5b. DYNAMIC VELOCITY SHAPING: emphasise higher pitches slightly ---
                if configuration.configData.get("midiPlayer", {}).get("humanize", {}).get("enabled", False):
                    humanize_cfg2 = configuration.configData["midiPlayer"]["humanize"]
                    vel_shape = humanize_cfg2.get("velocityShaping", 0.3)
                    if vel_shape > 0:
                        # Notes above middle C (60) get a gentle accent, below get softened
                        pitch_bias = (msg.note - 60) / 60.0  # range roughly -1 to +1
                        velocity_delta = int(pitch_bias * vel_shape * 12)
                        msg.velocity = max(1, min(127, msg.velocity + velocity_delta))

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

def playMidiFile(midiFile, playback_id):
    global _startOffset
    log("nanoMIDI Mid2VK Translator v3.0")
    log(f"Playing MIDI file: {midiFile}")
    offset = _startOffset
    _startOffset = 0.0
    while playback_id == current_playback_id:
        finished = playMidiOnce(midiFile, playback_id, startOffset=offset)
        offset = 0.0  # only use offset on first play
        if not configuration.configData["midiPlayer"]["loopSong"] or not finished or playback_id != current_playback_id:
            break
        for key in list(heldKeys):
            release(key)

    if playback_id == current_playback_id and not configuration.configData["midiPlayer"]["loopSong"]:
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
            if configuration.configData['appUI']['timestamp']:
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


def startPlayback(midiFile, updateCallback=None, startOffset=0.0):
    global playThread, clockThreadRef, paused, _startOffset, current_playback_id
    current_playback_id += 1
    my_playback_id = current_playback_id
    
    paused = False
    _startOffset = startOffset
    totalSeconds = mido.MidiFile(midiFile, clip=True).length
    playThread = threading.Thread(target=playMidiFile, args=(midiFile, my_playback_id), daemon=True)
    clockThreadRef = threading.Thread(target=clockThread, args=(totalSeconds, my_playback_id, updateCallback, startOffset), daemon=True)
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
    global current_playback_id, keyboardHandlers, timerList, heldNoteCount
    current_playback_id += 1
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
    log("Playback fully stopped.")