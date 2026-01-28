import io
import wave
import dashscope
import os
import uuid
from config import settings

def init_dashscope_api_key():
    """
    Set your DashScope API-key.
    """
    api_key = settings.get('DASHSCOPE_API_KEY') or settings.get('dashscope_api_key')
    if api_key:
        dashscope.api_key = api_key
    else:
        raise RuntimeError("DASHSCOPE_API_KEY is not set in settings or environment variables")

def pcm_to_wav(pcm_data, sample_rate=24000, channels=1, sample_width=2):
    """
    Encapsulate PCM data into WAV format.
    """
    wav_buf = io.BytesIO()
    with wave.open(wav_buf, 'wb') as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    return wav_buf.getvalue()

def save_audio(wav_audio_data, output_dir, base_url):
    """
    Save WAV audio data to local file and return the URL.
    """
    file_name = f"{uuid.uuid4()}.wav"
    file_path = os.path.join(output_dir, file_name)
    with open(file_path, "wb") as f:
        f.write(wav_audio_data)
    
    clean_base_url = str(base_url).rstrip('/')
    return f"{clean_base_url}/output/{file_name}"
