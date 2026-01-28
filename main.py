import io
import base64
import threading
import queue
import json
import os
import uuid
import dashscope
from dashscope.audio.qwen_tts_realtime import *
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import uvicorn
import wave
from config import settings

app = FastAPI()

# Configure output directory
SAVE_TO_LOCAL = settings.get("SAVE_TO_LOCAL", True)
if isinstance(SAVE_TO_LOCAL, str):
    SAVE_TO_LOCAL = SAVE_TO_LOCAL.lower() == "true"

OUTPUT_DIR = settings.get("OUTPUT_DIR", "output")

if SAVE_TO_LOCAL:
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    # Mount static files to serve saved audio
    app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")


def init_dashscope_api_key():
    """
    Set your DashScope API-key.
    """
    api_key = settings.get('DASHSCOPE_API_KEY') or settings.get('dashscope_api_key')
    if api_key:
        dashscope.api_key = api_key
    else:
        raise RuntimeError("DASHSCOPE_API_KEY is not set in settings or environment variables")


# Initialize API key on startup
init_dashscope_api_key()


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


class TTSRequest(BaseModel):
    text: str
    model: str
    voice: Optional[str] = 'Cherry',
    return_url: Optional[bool] = False


class HttpCallback(QwenTtsRealtimeCallback):
    def __init__(self):
        self.complete_event = threading.Event()
        self.buffer = io.BytesIO()
        self.error_msg = None

    def on_open(self) -> None:
        pass

    def on_close(self, close_status_code, close_msg) -> None:
        # print(f'connection closed: {close_status_code}, {close_msg}')
        self.complete_event.set()

    def on_event(self, response: str) -> None:
        try:
            type = response.get('type')
            if 'response.audio.delta' == type:
                recv_audio_b64 = response.get('delta')
                if recv_audio_b64:
                    self.buffer.write(base64.b64decode(recv_audio_b64))
            elif 'session.finished' == type:
                self.complete_event.set()
            elif 'error' == type:
                self.error_msg = response.get('message', 'Unknown error')
                self.complete_event.set()
        except Exception as e:
            self.error_msg = str(e)
            self.complete_event.set()

    def wait_for_finished(self, timeout=30):
        return self.complete_event.wait(timeout=timeout)

    def get_audio_data(self):
        return self.buffer.getvalue()


class SSECallback(QwenTtsRealtimeCallback):
    def __init__(self):
        self.queue = queue.Queue()
        self.error_msg = None

    def on_open(self) -> None:
        pass

    def on_close(self, close_status_code, close_msg) -> None:
        self.queue.put(None)

    def on_event(self, response: dict) -> None:
        try:
            event_type = response.get('type')
            if 'response.audio.delta' == event_type:
                audio_delta = response.get('delta')
                if audio_delta:
                    self.queue.put({"audio": audio_delta, "is_end": False})
            elif 'session.finished' == event_type:
                self.queue.put(None)
            elif 'error' == event_type:
                self.error_msg = response.get('message', 'Unknown error')
                self.queue.put({"error": self.error_msg})
                self.queue.put(None)
        except Exception as e:
            self.error_msg = str(e)
            self.queue.put({"error": self.error_msg})
            self.queue.put(None)


@app.post("/tts")
async def text_to_speech(request: TTSRequest, http_request: Request):
    callback = HttpCallback()

    # Initialize QwenTtsRealtime for each request to ensure isolation
    qwen_tts_realtime = QwenTtsRealtime(
        model=request.model,
        callback=callback,
        url=settings.get('dashscope.url', 'wss://dashscope.aliyuncs.com/api-ws/v1/realtime')
    )

    try:
        qwen_tts_realtime.connect()
        qwen_tts_realtime.update_session(
            voice=request.voice,
            response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
            mode='server_commit',
            format='pcm',
        )

        qwen_tts_realtime.append_text(request.text)
        qwen_tts_realtime.finish()

        # Wait for the generation to complete
        if not callback.wait_for_finished(timeout=60):
            raise HTTPException(status_code=504, detail="TTS synthesis timed out")

        if callback.error_msg:
            raise HTTPException(status_code=500, detail=f"TTS synthesis error: {callback.error_msg}")

        audio_data = callback.get_audio_data()

        if not audio_data:
            raise HTTPException(status_code=500, detail="No audio data generated")

        headers = {
            "X-Session-Id": qwen_tts_realtime.get_session_id() or "",
            "X-First-Audio-Delay": str(qwen_tts_realtime.get_first_audio_delay() or 0)
        }

        # Encapsulate PCM data into WAV format
        wav_audio_data = pcm_to_wav(audio_data)

        file_url = None
        if SAVE_TO_LOCAL:
            # Save to local file
            file_name = f"{uuid.uuid4()}.wav"
            file_path = os.path.join(OUTPUT_DIR, file_name)
            with open(file_path, "wb") as f:
                f.write(wav_audio_data)
            
            base_url = str(http_request.base_url).rstrip('/')
            file_url = f"{base_url}/output/{file_name}"

        if request.return_url:
            if not SAVE_TO_LOCAL:
                raise HTTPException(status_code=400, detail="Local saving is disabled, cannot return URL")
            return Response(content=json.dumps({"url": file_url}), media_type="application/json", headers=headers)

        return Response(content=wav_audio_data, media_type="audio/wav", headers=headers)

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Ensure resources are cleaned up if necessary
        # QwenTtsRealtime might need explicit closing if not handled by callback
        pass


@app.post("/tts_stream")
async def text_to_speech_stream(request: TTSRequest, http_request: Request):
    callback = SSECallback()

    # Initialize QwenTtsRealtime for each request to ensure isolation
    qwen_tts_realtime = QwenTtsRealtime(
        model=request.model,
        callback=callback,
        url=settings.get('dashscope.url', 'wss://dashscope.aliyuncs.com/api-ws/v1/realtime')
    )

    def generate():
        audio_accumulator = io.BytesIO()
        try:
            qwen_tts_realtime.connect()
            qwen_tts_realtime.update_session(
                voice=request.voice,
                response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
                mode='server_commit',
                format='pcm',
            )

            qwen_tts_realtime.append_text(request.text)
            qwen_tts_realtime.finish()

            while True:
                try:
                    item = callback.queue.get(timeout=30)
                    if item is None:
                        # Handle accumulated audio
                        pcm_data = audio_accumulator.getvalue()
                        if pcm_data and SAVE_TO_LOCAL:
                            wav_data = pcm_to_wav(pcm_data)
                            file_name = f"{uuid.uuid4()}.wav"
                            file_path = os.path.join(OUTPUT_DIR, file_name)
                            with open(file_path, "wb") as f:
                                f.write(wav_data)
                            
                            base_url = str(http_request.base_url).rstrip('/')
                            file_url = f"{base_url}/output/{file_name}"
                            yield f"data: {json.dumps({'is_end': True, 'url': file_url})}\n\n"
                        else:
                            yield f"data: {json.dumps({'is_end': True})}\n\n"
                        break
                    
                    if isinstance(item, dict) and "audio" in item:
                        audio_accumulator.write(base64.b64decode(item["audio"]))

                    yield f"data: {json.dumps(item)}\n\n"
                except queue.Empty:
                    yield f"data: {json.dumps({'error': 'Timeout waiting for audio'})}\n\n"
                    break
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            # Clean up if needed
            pass

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/health")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.get('server.host', '0.0.0.0'),
        port=settings.get('server.port', 9000)
    )
