import io
import base64
import json
import os
import queue
from dashscope.audio.qwen_tts_realtime import QwenTtsRealtime, AudioFormat
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from config import settings, logger
from models import TTSRequest
from callbacks import HttpCallback, SSECallback
from utils import init_dashscope_api_key, pcm_to_wav, save_audio

app = FastAPI()

# Configure storage
ENABLE_SAVE = settings.get("enableSave", True)
if isinstance(ENABLE_SAVE, str):
    ENABLE_SAVE = ENABLE_SAVE.lower() == "true"

STORAGE_TYPE = settings.get("storageType", "local").lower()
OUTPUT_DIR = settings.get("outputDir", "output")
if ENABLE_SAVE and STORAGE_TYPE == "local":
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    # Mount static files to serve saved audio
    app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

# Initialize API key on startup
init_dashscope_api_key()


@app.post("/tts")
async def text_to_speech(request: TTSRequest, http_request: Request):
    logger.info(f"Received TTS request: voice={request.voice}, model={request.model}")
    callback = HttpCallback()

    # Initialize QwenTtsRealtime for each request to ensure isolation
    qwen_tts_realtime = QwenTtsRealtime(
        model=request.model,
        callback=callback,
        url=settings.get('dashscope.url', 'wss://dashscope.aliyuncs.com/api-ws/v1/realtime')
    )

    try:
        logger.debug("Connecting to DashScope...")
        qwen_tts_realtime.connect()
        logger.debug(f"Updating session: voice={request.voice}")
        qwen_tts_realtime.update_session(
            voice=request.voice,
            response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
            mode='server_commit',
            format='pcm',
        )

        logger.debug(f"Appending text: {request.text[:50]}...")
        qwen_tts_realtime.append_text(request.text)
        qwen_tts_realtime.finish()

        # Wait for the generation to complete
        logger.debug("Waiting for TTS synthesis to finish...")
        if not callback.wait_for_finished(timeout=60):
            logger.error("TTS synthesis timed out")
            raise HTTPException(status_code=504, detail="TTS synthesis timed out")

        if callback.error_msg:
            logger.error(f"TTS synthesis error: {callback.error_msg}")
            raise HTTPException(status_code=500, detail=f"TTS synthesis error: {callback.error_msg}")

        audio_data = callback.get_audio_data()

        if not audio_data:
            logger.error("No audio data generated")
            raise HTTPException(status_code=500, detail="No audio data generated")

        session_id = qwen_tts_realtime.get_session_id()
        first_audio_delay = qwen_tts_realtime.get_first_audio_delay()
        logger.info(f"TTS synthesis completed: session_id={session_id}, first_audio_delay={first_audio_delay}ms, audio_size={len(audio_data)} bytes")

        headers = {
            "X-Session-Id": session_id or "",
            "X-First-Audio-Delay": str(first_audio_delay or 0),
            "X-Usage-Characters":callback.get_usage_characters()
        }

        # Encapsulate PCM data into WAV format
        wav_audio_data = pcm_to_wav(audio_data)

        file_url = None
        if ENABLE_SAVE:
            logger.debug("Saving audio file...")
            file_url = save_audio(wav_audio_data, OUTPUT_DIR, http_request.base_url)
            logger.info(f"Audio saved: {file_url}")

        if request.return_url:
            if not ENABLE_SAVE:
                logger.warning("Saving is disabled, but return_url requested")
                raise HTTPException(status_code=400, detail="Saving is disabled, cannot return URL")
            return Response(content=json.dumps({"url": file_url}), media_type="application/json", headers=headers)

        return Response(content=wav_audio_data, media_type="audio/wav", headers=headers)

    except Exception as e:
        logger.exception(f"Unexpected error in /tts: {str(e)}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Ensure resources are cleaned up if necessary
        # QwenTtsRealtime might need explicit closing if not handled by callback
        pass


@app.post("/tts_stream")
async def text_to_speech_stream(request: TTSRequest, http_request: Request):
    logger.info(f"Received TTS stream request: voice={request.voice}, model={request.model}")
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
            logger.debug("Connecting to DashScope (stream)...")
            qwen_tts_realtime.connect()
            logger.debug(f"Updating session (stream): voice={request.voice}")
            qwen_tts_realtime.update_session(
                voice=request.voice,
                response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
                mode='server_commit',
                format='pcm',
            )

            logger.debug(f"Appending text (stream): {request.text[:50]}...")
            qwen_tts_realtime.append_text(request.text)
            qwen_tts_realtime.finish()

            while True:
                try:
                    item = callback.queue.get(timeout=30)
                    if item is None:
                        logger.debug("Stream finished (received None)")
                        # Handle accumulated audio
                        pcm_data = audio_accumulator.getvalue()
                        usage_characters = callback.get_usage_characters()
                        if pcm_data and ENABLE_SAVE:
                            logger.debug("Saving accumulated audio from stream...")
                            wav_data = pcm_to_wav(pcm_data)
                            file_url = save_audio(wav_data, OUTPUT_DIR, http_request.base_url)
                            logger.info(f"Stream audio saved: {file_url}")
                            yield f"data: {json.dumps({'is_end': True, 'url': file_url, 'usage_characters': usage_characters})}\n\n"
                        else:
                            yield f"data: {json.dumps({'is_end': True, 'usage_characters': usage_characters})}\n\n"
                        break
                    
                    if isinstance(item, dict) and "audio" in item:
                        audio_accumulator.write(base64.b64decode(item["audio"]))

                    yield f"data: {json.dumps(item)}\n\n"
                except queue.Empty:
                    logger.error("Stream synthesis timed out waiting for audio")
                    yield f"data: {json.dumps({'error': 'Timeout waiting for audio'})}\n\n"
                    break
        except Exception as e:
            logger.exception(f"Error in stream generation: {str(e)}")
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
