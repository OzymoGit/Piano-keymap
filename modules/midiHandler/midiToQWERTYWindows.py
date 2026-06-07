import re
import keyboard
import mido
import threading

from pynput import keyboard as pynputKeyboard
from modules.functions import mainFunctions
from modules import configuration

# --- win32msg helpers (loaded lazily so non-Windows imports don't fail) ---
try:
    import win32api
    import win32con
    import win32gui
    _win32Available = True
except ImportError:
    _win32Available = False

# Virtual-key code map for win32msg mode
_VK_MAP = {
    # Letters a-z
    **{ch: ord(ch.upper()) for ch in 'abcdefghijklmnopqrstuvwxyz'},
    # Digits
    **{str(d): ord(str(d)) for d in range(10)},
    # Special keys
    'space': win32con.VK_SPACE if _win32Available else 0x20,
    'shift': win32con.VK_SHIFT if _win32Available else 0x10,
    'ctrl':  win32con.VK_CONTROL if _win32Available else 0x11,
    'alt':   win32con.VK_MENU if _win32Available else 0x12,
    # Symbols that require Shift (mapped to their base VK)
    '!': ord('1'), '@': ord('2'), '#': ord('3'), '$': ord('4'),
    '%': ord('5'), '^': ord('6'), '&': ord('7'), '*': ord('8'),
    '(': ord('9'), ')': ord('0'),
}

# Characters that need Shift to produce
_NEEDS_SHIFT = set('!@#$%^&*()ABCDEFGHIJKLMNOPQRSTUVWXYZ')

def listOpenWindows():
    """Return a list of visible window titles for the Target Window dropdown."""
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

def getTargetHwnd():
    """Find the HWND for the configured target window title."""
    if not _win32Available:
        return None
    title = configuration.configData.get('midiToQwerty', {}).get('targetWindow', '')
    if not title:
        return None
    hwnd = win32gui.FindWindow(None, title)
    return hwnd if hwnd else None

pressedKeys = set()
heldKeys = set()
activeTransposedNotes = {}

log = mainFunctions.log

inPort = None
midiThread = None

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

if configuration.configData["midiToQwerty"]["inputModule"] == "keyboard":
    def press(key):
        keyboard.press(key)
        logKeys("press", key)
    def release(key):
        keyboard.release(key)
        logKeys("release", key)

elif configuration.configData["midiToQwerty"]["inputModule"] == "pynput":
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
            raise ValueError(f"Unsupported key for pynput: {key}")

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
        if isBlockedKey(keyObj):
            return
        pynputController.press(keyObj)
        logKeys("press", keyObj)
        heldKeys.add(keyObj)

    def release(key):
        keyObj = translateKey(key)
        if isBlockedKey(keyObj):
            return
        pynputController.release(keyObj)
        logKeys("release", keyObj)
        if keyObj in heldKeys:
            heldKeys.remove(keyObj)

elif configuration.configData["midiToQwerty"]["inputModule"] == "win32msg":
    # Sends WM_KEYDOWN / WM_KEYUP directly to a target window's message queue.
    # The window does NOT need to be focused.
    _shiftDown = False

    def _postKey(vk, down):
        hwnd = getTargetHwnd()
        if not hwnd or not _win32Available:
            log("win32msg: no target window found")
            return
        scanCode = win32api.MapVirtualKey(vk, 0)
        
        isExtended = vk in (win32con.VK_UP, win32con.VK_DOWN, win32con.VK_LEFT, win32con.VK_RIGHT, win32con.VK_MENU, win32con.VK_CONTROL)
        extendedBit = 1 if isExtended else 0
        
        if down:
            lParam = 1 | (scanCode << 16) | (extendedBit << 24)
            win32api.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, lParam)
        else:
            lParam = 1 | (scanCode << 16) | (extendedBit << 24) | (1 << 30) | (1 << 31)
            win32api.PostMessage(hwnd, win32con.WM_KEYUP, vk, lParam)

    def press(key):
        global _shiftDown
        keyStr = str(key)
        # Handle modifier keys
        if keyStr.lower() == 'shift':
            if not _shiftDown:
                _shiftDown = True
                _postKey(_VK_MAP['shift'], True)
            logKeys("press", key)
            return
        if keyStr.lower() == 'ctrl':
            _postKey(_VK_MAP['ctrl'], True)
            logKeys("press", key)
            return
        if keyStr.lower() == 'alt':
            _postKey(_VK_MAP['alt'], True)
            logKeys("press", key)
            return
        # Resolve VK code
        vk = _VK_MAP.get(keyStr)
        if vk is None:
            log(f"win32msg: no VK for key '{keyStr}'")
            return
        # Auto-shift for uppercase / symbols
        needShift = keyStr in _NEEDS_SHIFT
        if needShift and not _shiftDown:
            _postKey(_VK_MAP['shift'], True)
        _postKey(vk, True)
        logKeys("press", key)
        heldKeys.add(keyStr)

    def release(key):
        global _shiftDown
        keyStr = str(key)
        if keyStr.lower() == 'shift':
            if _shiftDown:
                _shiftDown = False
                _postKey(_VK_MAP['shift'], False)
            logKeys("release", key)
            return
        if keyStr.lower() == 'ctrl':
            _postKey(_VK_MAP['ctrl'], False)
            logKeys("release", key)
            return
        if keyStr.lower() == 'alt':
            _postKey(_VK_MAP['alt'], False)
            logKeys("release", key)
            return
        vk = _VK_MAP.get(keyStr)
        if vk is None:
            return
        needShift = keyStr in _NEEDS_SHIFT
        _postKey(vk, False)
        if needShift and not _shiftDown:
            _postKey(_VK_MAP['shift'], False)
        logKeys("release", key)
        if keyStr in heldKeys:
            heldKeys.remove(keyStr)

stopEvent = threading.Event()
keyboardHandlers = []
timerList = []
closeThread = False
sustainActive = False

def findVelocityKey(velocity):
    velocityMap = configuration.configData["midiToQwerty"]["pianoMap"]["velocityMap"]
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
    press(key)
    if configuration.configData["midiToQwerty"]["customHoldLength"]["enabled"]:
        t = threading.Timer(configuration.configData["midiToQwerty"]["customHoldLength"]["noteLength"], lambda: release(key))
        timerList.append(t)
        t.start()

def simulateKey(msgType, note, velocity):
    if not -15 <= note - 36 <= 88:
        log(f"out of range: {note}")
        return

    key = None
    letterNoteMap = configuration.configData["midiToQwerty"]["pianoMap"]["61keyMap"]
    lowNotes = configuration.configData["midiToQwerty"]["pianoMap"]["88keyMap"]["lowNotes"]
    highNotes = configuration.configData["midiToQwerty"]["pianoMap"]["88keyMap"]["highNotes"]

    if str(note) in letterNoteMap:
        key = letterNoteMap[str(note)]
    elif str(note) in lowNotes:
        key = lowNotes[str(note)]
    elif str(note) in highNotes:
        key = highNotes[str(note)]

    if not key:
        log(f"no mapping: {note}")
        return
    
    pianoWidget = mainFunctions.getApp().frames["miditoqwerty"].piano

    if msgType == "note_on":
        pianoWidget.down(note, velocity)

        if configuration.configData["midiToQwerty"]["velocity"]:
            velocityKey = findVelocityKey(velocity)
            press("alt")
            press(velocityKey)
            release(velocityKey)
            release("alt")

        if 36 <= note <= 96:
            if configuration.configData["midiToQwerty"]["noDoubles"]:
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
        pianoWidget.up(note)

        if 36 <= note <= 96:
            if re.search("[!@$%^*(]", key):
                release(letterNoteMap[str(note - 1)])
            else:
                release(key.lower())
        else:
            release(key.lower())

def parseMidi(message):
    global sustainActive
    if message.type == "control_change" and configuration.configData["midiToQwerty"]["sustain"]:
        if not sustainActive and message.value > configuration.configData["midiToQwerty"]["sustainCutoff"]:
            sustainActive = True
            press("space")
        elif sustainActive and message.value < configuration.configData["midiToQwerty"]["sustainCutoff"]:
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

def startMidiInput(portName=None):
    global inPort, midiThread, stopEvent, closeThread
    stopEvent.clear()
    closeThread = False
    log("nanoMIDI Mid2VK Translator v1.0 (Live Input)")
    try:
        if portName:
            inPort = mido.open_input(portName)
        else:
            inPort = mido.open_input()
    except Exception as e:
        log(f"Could not open MIDI input: {e}")
        return

    def midiLoop():
        for msg in inPort:
            if stopEvent.is_set() or closeThread:
                break
            parseMidi(msg)

    midiThread = threading.Thread(target=midiLoop, daemon=True)
    midiThread.start()
    return midiThread


def stopMidiInput():
    global closeThread, stopEvent, keyboardHandlers, timerList, inPort, midiThread
    stopEvent.set()
    closeThread = True

    if inPort:
        try:
            inPort.close()
        except Exception:
            pass
        inPort = None

    if midiThread and midiThread.is_alive():
        try:
            midiThread.join(timeout=1.0)
        except Exception:
            pass
        midiThread = None

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

    try:
        pianoWidget = mainFunctions.getApp().frames["miditoqwerty"].piano
        for note in pianoWidget.currentNotes():
            pianoWidget.up(note)
    except Exception:
        pass

    log("MIDI input stopped.")