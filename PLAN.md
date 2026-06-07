# Implementation Plan - Auto Piano Transcription, Search, and Timeline Seeking

This plan updates the proposed changes to address the new feature requirements:
1. **Time-range slicing (Skip ads/intro/outro):** Choose the section to transcribe *before* transcription to save processing time and bandwidth.
2. **YouTube Search directly in the App:** Search YouTube within the tab, display search results with video titles, durations, and thumbnails. Clicking a result selects it.
3. **MIDI Player Timeline Seeking:** A seek bar (slider) on the MIDI Player tab showing progress, which the user can drag or click to jump directly to any part of the song.
4. **Feasibility of Real-Time Transcribe & Play:** The ByteDance model requires batch processing of the audio segment first, so it cannot play notes *simultaneously* as they are transcribed. However, by transcribing only the selected slice, the processing time is extremely short, enabling near-instant playback.

---

## Progress so far:
- **YouTube Transcription Foundation:** We've successfully set up the core transcription engine (`ytTranscribeFunctions.py`), UI tab (`ytTranscribe.py`), and system dependencies.
- **Timeline Seeking in MIDI Player:** We've successfully replaced the static timeline label with an interactive seek slider (`ui/midiPlayer.py`), modified the playback engines (`midiWindows.py`, `midiDarwin.py`, `midiLinux.py`) to handle `startOffset`, and implemented the `seekPlayback` function in `midiPlayerFunctions.py`. We also patched `loadSavedFile` to sync the seek bar.

---

## Proposed Next Steps

### 1. Finalize YouTube Search & Range Selection

#### [PENDING] [main.py](file:///c:/Users/haipr/Documents/Code/Projects/nanoMIDIPlayer-main/main.py)
- Modify `main.py` to register the new YT Transcribe tab and properly initialize paths (e.g. static ffmpeg directory).

### 2. Verification and Testing

#### [PENDING] Manual Verification
1. **MIDI Player Seeking:** Drag the new seek bar to skip forward and backward. Verify notes update and keyboard simulation/device MIDI signals respond correctly. Check if `seekPlayback` stops current threads and starts correctly.
2. **YouTube Search:** Search for a piano tutorial. Verify thumbnails, titles, and durations are displayed. Click a result to select it.
3. **Slicing:** Enter start/end times. Verify the downloaded audio is sliced and only that segment is transcribed.
