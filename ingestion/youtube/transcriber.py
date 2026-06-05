import yt_dlp
from faster_whisper import WhisperModel

def transcribe_video(
    video_id: str,
    audio_path: str,
    whisper_model: str = "base",
    device: str = "cpu",
    compute_type: str = "int8",
) -> str:
    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": audio_path,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "64",
        }],
        "quiet": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        print(f"[transcriber] Download failed for {video_id}: {e}")
        return ""

    try:
        model = WhisperModel(whisper_model, device=device, compute_type=compute_type)
        segments, _ = model.transcribe(audio_path + ".mp3")
        return "".join(seg.text for seg in segments)
    except Exception as e:
        print(f"[transcriber] Transcription failed for {video_id}: {e}")
        return ""
