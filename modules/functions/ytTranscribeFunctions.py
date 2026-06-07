import os
import sys
import subprocess
import threading
import urllib.request
import io
import json
import logging
import platform
import datetime

logger = logging.getLogger(__name__)

# Try to import optional packages
try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None

try:
    import librosa
except ImportError:
    librosa = None

try:
    import soundfile
except ImportError:
    soundfile = None

try:
    import torch
except ImportError:
    torch = None

try:
    from piano_transcription_inference import PianoTranscription, sample_rate
except ImportError:
    PianoTranscription = None
    sample_rate = 16000

def get_ffmpeg_path():
    """Ensure imageio-ffmpeg is path-configured."""
    if imageio_ffmpeg is not None:
        try:
            exe = imageio_ffmpeg.get_ffmpeg_exe()
            dir_path = os.path.dirname(exe)
            if dir_path not in os.environ["PATH"]:
                os.environ["PATH"] += os.pathsep + dir_path
            return exe
        except Exception as e:
            logger.exception("Failed to get imageio_ffmpeg exe path")
    return None

# Path where user can drop a cookies.txt file (Netscape format)
_docs = os.path.join(os.path.expanduser("~"), "Documents")
COOKIES_FILE = os.path.join(_docs, "nanoMIDIPlayer", "www.youtube.com_cookies.txt")

def get_ydl_cookie_opts():
    """Return yt-dlp cookie and JS runtime options dict."""
    opts = {
        'js_runtimes': {'node': {}, 'deno': {}, 'bun': {}}
    }
    # 1. User-supplied cookies file
    if os.path.exists(COOKIES_FILE):
        logger.info(f"Using cookies file: {COOKIES_FILE}")
        opts["cookiefile"] = COOKIES_FILE
        return opts
    # 2. Try to read from Chrome (only works when Chrome is closed)
    try:
        import yt_dlp as _ydl
        test_opts = {
            "quiet": True, "no_warnings": True,
            "cookiesfrombrowser": ("chrome", None, None, None)
        }
        opts["cookiesfrombrowser"] = ("chrome", None, None, None)
        return opts
    except Exception:
        pass
    # 3. No cookies available
    return opts

def check_dependencies():
    """Return dictionary of dependency statuses."""
    return {
        "yt-dlp": yt_dlp is not None,
        "imageio-ffmpeg": imageio_ffmpeg is not None,
        "librosa": librosa is not None,
        "soundfile": soundfile is not None,
        "torch": torch is not None,
        "piano-transcription-inference": PianoTranscription is not None
    }

def install_dependencies(progress_callback=None):
    """Installs dependencies in a background thread."""
    def run_install():
        packages = ["yt-dlp", "imageio-ffmpeg", "librosa", "soundfile", "torch", "piano-transcription-inference"]
        total = len(packages)
        for i, pkg in enumerate(packages):
            if progress_callback:
                progress_callback(f"Installing {pkg} ({i+1}/{total})...", (i / total) * 100)
            try:
                subprocess.run([sys.executable, "-m", "pip", "install", pkg], capture_output=True, check=True)
            except Exception as e:
                logger.error(f"Failed to install {pkg}: {e}")
                if progress_callback:
                    progress_callback(f"Failed to install {pkg}. Please check internet connection.", -1)
                return
        
        # Reload imported packages dynamically
        global yt_dlp, imageio_ffmpeg, librosa, soundfile, torch, PianoTranscription, sample_rate
        try:
            import yt_dlp
            import imageio_ffmpeg
            import librosa
            import soundfile
            import torch
            from piano_transcription_inference import PianoTranscription, sample_rate
            get_ffmpeg_path()
            if progress_callback:
                progress_callback("All dependencies installed successfully! Restarting UI components...", 100)
        except Exception as e:
            logger.error(f"Reloading dependencies failed: {e}")
            if progress_callback:
                progress_callback("Dependencies installed but import failed. Please restart the app.", -1)

    threading.Thread(target=run_install, daemon=True).start()

def search_youtube(query):
    """Search YouTube and return video list."""
    if yt_dlp is None:
        return []

    ffmpeg_exe = get_ffmpeg_path()
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'playlistend': 10,
    }
    if ffmpeg_exe:
        ydl_opts['ffmpeg_location'] = ffmpeg_exe
    ydl_opts.update(get_ydl_cookie_opts())
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch10:{query}", download=False)
            if 'entries' in result:
                videos = []
                for entry in result['entries']:
                    if not entry:
                        continue
                    duration_sec = entry.get('duration')
                    if duration_sec is None:
                        duration_sec = 0
                    mins = int(duration_sec // 60)
                    secs = int(duration_sec % 60)
                    duration_str = f"{mins}:{secs:02}"
                    videos.append({
                        'id': entry.get('id'),
                        'title': entry.get('title', 'Unknown Title'),
                        'duration_str': duration_str,
                        'duration_sec': duration_sec,
                        'url': f"https://www.youtube.com/watch?v={entry.get('id')}",
                        'thumbnail': f"https://img.youtube.com/vi/{entry.get('id')}/mqdefault.jpg",
                        'channel': entry.get('channel', entry.get('uploader', 'Unknown Channel'))
                    })
                return videos
    except Exception as e:
        logger.error(f"Search failed: {e}")
    return []

def download_checkpoint(destination, progress_callback=None):
    """Download pretrained pth checkpoint."""
    url = "https://zenodo.org/records/4034264/files/CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth"
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            total_size = int(response.info().get('Content-Length', 0))
            block_size = 1024 * 64
            downloaded = 0
            
            with open(destination, 'wb') as f:
                while True:
                    buffer = response.read(block_size)
                    if not buffer:
                        break
                    f.write(buffer)
                    downloaded += len(buffer)
                    if progress_callback and total_size > 0:
                        percent = (downloaded / total_size) * 100
                        progress_callback(f"Downloading checkpoint: {percent:.1f}%", percent)
    except Exception as e:
        logger.error(f"Failed to download checkpoint: {e}")
        if os.path.exists(destination):
            try:
                os.remove(destination)
            except:
                pass
        raise e

def transcribe_youtube_video(video_url, start_time_sec, end_time_sec, use_cuda, progress_callback=None):
    """Main transcription workflow running in a thread. end_time_sec=None means full video."""
    def worker():
        try:
            # 1. Dependency checks
            deps = check_dependencies()
            if not all(deps.values()):
                missing = [k for k, v in deps.items() if not v]
                if progress_callback:
                    progress_callback(f"Missing libraries: {', '.join(missing)}", -1)
                return

            # Ensure ffmpeg path
            get_ffmpeg_path()

            # 2. Check/Download Checkpoint
            checkpoint_dir = os.path.expanduser("~/piano_transcription_inference_data")
            checkpoint_path = os.path.join(checkpoint_dir, "note_F1=0.9677_pedal_F1=0.9186.pth")
            if not os.path.exists(checkpoint_path):
                if progress_callback:
                    progress_callback("Locating checkpoint...", 0)
                try:
                    download_checkpoint(checkpoint_path, progress_callback)
                except Exception as e:
                    if progress_callback:
                        progress_callback("Failed to download model checkpoint. Zenodo may be offline.", -1)
                    return

            # 3. Download audio via yt-dlp
            from modules import configuration
            midis_dir = os.path.join(configuration.baseDirectory, "Midis")
            os.makedirs(midis_dir, exist_ok=True)

            if progress_callback:
                progress_callback("Fetching video audio from YouTube...", 10)

            # Retrieve video title
            ydl_opts_info = {'quiet': True, 'no_warnings': True}
            ydl_opts_info.update(get_ydl_cookie_opts())
            video_title = "transcribed_song"
            try:
                with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                    info = ydl.extract_info(video_url, download=False)
                    video_title = info.get('title', 'transcribed_song')
                    video_title = "".join([c for c in video_title if c.isalpha() or c.isdigit() or c in ' -_']).strip()
            except Exception as e:
                logger.warning(f"Could not retrieve video title: {e}")

            # Temp wav file path
            temp_wav_path = os.path.join(midis_dir, "temp_yt_audio.wav")
            if os.path.exists(temp_wav_path):
                try:
                    os.remove(temp_wav_path)
                except:
                    pass

            ffmpeg_exe = get_ffmpeg_path()
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(midis_dir, 'temp_yt_audio_raw.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
            }
            ydl_opts.update(get_ydl_cookie_opts())

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video_url])
                
                # yt-dlp downloaded temp_yt_audio_raw.*
                import glob
                raw_files = glob.glob(os.path.join(midis_dir, 'temp_yt_audio_raw.*'))
                if not raw_files:
                    raise Exception("Audio file was not downloaded.")
                raw_file = raw_files[0]

                # Manually convert to wav using ffmpeg
                import subprocess
                subprocess.run([
                    ffmpeg_exe, '-y', 
                    '-i', raw_file, 
                    '-ac', '1', 
                    '-ar', '16000', 
                    temp_wav_path
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                # Clean up raw file
                try: os.remove(raw_file)
                except: pass

            except Exception as e:
                logger.error(f"Download failed: {e}")
                if progress_callback:
                    progress_callback("Failed to download audio from YouTube. Check link or internet connection.", -1)
                return

            if not os.path.exists(temp_wav_path):
                # Sometimes output file gets named slightly differently or has lowercase extension
                temp_wav_path = os.path.join(midis_dir, "temp_yt_audio.wav")
                if not os.path.exists(temp_wav_path):
                    # Look for wav in directory
                    files = [f for f in os.listdir(midis_dir) if f.startswith("temp_yt_audio") and f.endswith(".wav")]
                    if files:
                        temp_wav_path = os.path.join(midis_dir, files[0])
                    else:
                        if progress_callback:
                            progress_callback("Downloaded file was not converted to WAV. FFMpeg error.", -1)
                        return

            # 4. Slicing with librosa
            if progress_callback:
                progress_callback("Slicing audio segment...", 40)

            # end_time_sec=None means use the full audio from start_time_sec
            duration = None
            if end_time_sec is not None and end_time_sec > start_time_sec:
                duration = end_time_sec - start_time_sec

            try:
                audio, _ = librosa.load(
                    temp_wav_path,
                    sr=sample_rate,
                    mono=True,
                    offset=float(start_time_sec),
                    duration=duration
                )
            except Exception as e:
                logger.error(f"Librosa load failed: {e}")
                if progress_callback:
                    progress_callback(f"Failed to decode audio: {e}", -1)
                return

            # Delete the large temp WAV file to save space
            try:
                os.remove(temp_wav_path)
            except:
                pass

            # 5. Transcribing using ByteDance Model
            if progress_callback:
                progress_callback("Transcribing piano keys (AI processing)...", 60)

            device = 'cuda' if (use_cuda and torch.cuda.is_available()) else 'cpu'
            output_midi_path = os.path.join(midis_dir, f"{video_title}.mid")
            
            # Avoid overwrite issues if same name exists, append number
            counter = 1
            while os.path.exists(output_midi_path):
                output_midi_path = os.path.join(midis_dir, f"{video_title}_{counter}.mid")
                counter += 1

            try:
                transcriptor = PianoTranscription(device=device, checkpoint_path=checkpoint_path)
                # This performs transcription and outputs to output_midi_path
                transcriptor.transcribe(audio, output_midi_path)
            except Exception as e:
                logger.error(f"Transcription failed: {e}")
                if progress_callback:
                    progress_callback(f"Model error during transcription: {e}", -1)
                return

            # 6. Save to history
            save_history_entry(video_title, video_url, output_midi_path)

            # 7. Auto-load and play the MIDI file
            if progress_callback:
                progress_callback("Transcription completed! Preparing playback...", 95)
            
            # Switch to main thread to load and play
            from main import App
            from modules.functions import mainFunctions
            app = mainFunctions.getApp()
            if app:
                app.after(100, lambda: autoplay_midi(output_midi_path, app))

            if progress_callback:
                progress_callback("Success!", 100)

        except Exception as e:
            logger.exception("Error in transcription worker thread")
            if progress_callback:
                progress_callback(f"An unexpected error occurred: {e}", -1)

    threading.Thread(target=worker, daemon=True).start()

# ── History Tracking ─────────────────────────────────────────────────
_history_file = os.path.join(_docs, "nanoMIDIPlayer", "history.json")

def load_history():
    """Load transcription history from disk."""
    try:
        if os.path.exists(_history_file):
            with open(_history_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load history: {e}")
    return []

def save_history_entry(video_title, video_url, midi_path):
    """Append a new entry to transcription history."""
    try:
        history = load_history()
        entry = {
            'title': video_title,
            'url': video_url,
            'midi_path': midi_path,
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        history.insert(0, entry)  # newest first
        # Keep max 200 entries
        history = history[:200]
        os.makedirs(os.path.dirname(_history_file), exist_ok=True)
        with open(_history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to save history: {e}")

def autoplay_midi(midi_file_path, app):
    """Register the new MIDI file in the MIDI player and start playback."""
    from modules.functions import midiPlayerFunctions

    try:
        # Switch tab to MIDI Player
        app.showFrame("midi")

        # Load, update UI, and play the MIDI file
        midiPlayerFunctions.selectAndPlayFile(midi_file_path)

    except Exception as e:
        logger.error(f"Autoplay failed: {e}")
