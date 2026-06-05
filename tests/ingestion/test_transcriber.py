from unittest.mock import patch, MagicMock
from ingestion.youtube.transcriber import transcribe_video

def test_transcribe_video_returns_text():
    mock_segments = [
        MagicMock(text=" Good morning everyone."),
        MagicMock(text=" Welcome to TCS Q4 earnings call."),
    ]
    mock_info = MagicMock()

    with patch("ingestion.youtube.transcriber.yt_dlp.YoutubeDL") as mock_ydl_cls, \
         patch("ingestion.youtube.transcriber.WhisperModel") as mock_whisper_cls:
        mock_ydl = MagicMock()
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (mock_segments, mock_info)
        mock_whisper_cls.return_value = mock_model

        result = transcribe_video("abc123", audio_path="/tmp/abc123")
    assert "TCS" in result

def test_transcribe_video_returns_empty_on_download_failure():
    with patch("ingestion.youtube.transcriber.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl = MagicMock()
        mock_ydl.download.side_effect = Exception("Video unavailable")
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl
        result = transcribe_video("bad_id", audio_path="/tmp/bad_id")
    assert result == ""
