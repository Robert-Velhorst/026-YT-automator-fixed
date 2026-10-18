import shutil
import subprocess
import tempfile
from pathlib import Path

from flask import current_app
from openai import OpenAI


MAX_PROVIDER_BYTES = 24 * 1024 * 1024


class TranscriptionUnavailable(RuntimeError):
    pass


def _transcribe(path, language):
    with path.open("rb") as stream:
        result = OpenAI(api_key=current_app.config["OPENAI_API_KEY"], timeout=180).audio.transcriptions.create(
            model=current_app.config["OPENAI_TRANSCRIPTION_MODEL"],
            file=stream,
            language=language,
        )
    return result.text.strip()


def _audio_chunks(video_path, target_dir):
    executable = current_app.config.get("FFMPEG_PATH", "ffmpeg")
    resolved = shutil.which(executable) if not Path(executable).is_file() else executable
    if not resolved:
        raise TranscriptionUnavailable(
            "This video exceeds the hosted transcription limit and FFmpeg is not available for local audio chunking"
        )
    pattern = str(target_dir / "audio-%04d.mp3")
    command = [
        str(resolved), "-hide_banner", "-loglevel", "error", "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", "-f", "segment",
        "-segment_time", "1200", "-reset_timestamps", "1", pattern,
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60 * 30, check=False)
    if result.returncode != 0:
        raise TranscriptionUnavailable("FFmpeg could not prepare audio for transcription")
    chunks = sorted(target_dir.glob("audio-*.mp3"))
    if not chunks or any(chunk.stat().st_size > MAX_PROVIDER_BYTES for chunk in chunks):
        raise TranscriptionUnavailable("Prepared audio chunks exceed the transcription provider limit")
    return chunks


def transcribe_video(video_file_path, language="en"):
    if not current_app.config.get("OPENAI_API_KEY"):
        raise TranscriptionUnavailable("OPENAI_API_KEY is not configured; paste or edit a transcript manually")
    path = Path(video_file_path)
    if not path.is_file():
        raise TranscriptionUnavailable("The source video file is missing")
    if path.stat().st_size <= MAX_PROVIDER_BYTES:
        return _transcribe(path, language)
    with tempfile.TemporaryDirectory(prefix="studiopilot-transcribe-") as directory:
        chunks = _audio_chunks(path, Path(directory))
        return "\n\n".join(text for text in (_transcribe(chunk, language) for chunk in chunks) if text)
