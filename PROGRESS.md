# Task Checklist - YouTube Transcription and Playback Seeking

- [x] Update `requirements.txt` with dependencies (`yt-dlp`, `imageio-ffmpeg`, `piano-transcription-inference`, `librosa`, `torch`, `soundfile`)
- [x] Modify `main.py` to include static ffmpeg directory in PATH and register the new YT Transcribe tab
- [x] Implement transcription core functions in `modules/functions/ytTranscribeFunctions.py` (download, checkpoint verification, slicing, transcription)
- [x] Build the YT Transcribe UI tab in `ui/ytTranscribe.py` (Search panel, thumbnails, selection panel, progress bar)
- [x] Implement seeking mechanism in playback engines (`modules/midiHandler/midiWindows.py` and `modules/midiHandler/useOutput.py`)
- [x] Update MIDI Player UI in `ui/midiPlayer.py` with a seek slider progress bar
- [x] Connect seek slider to playback control in `modules/functions/midiPlayerFunctions.py`
- [ ] Verify search, slice-transcribe, auto-play, and timeline seeking
