import io
import base64
import threading
import queue
from dashscope.audio.qwen_tts_realtime import QwenTtsRealtimeCallback
from config import logger

class HttpCallback(QwenTtsRealtimeCallback):
    def __init__(self):
        self.complete_event = threading.Event()
        self.buffer = io.BytesIO()
        self.error_msg = None
        self.usage_characters = 0

    def on_open(self) -> None:
        logger.debug("HttpCallback: Connection opened")

    def on_close(self, close_status_code, close_msg) -> None:
        logger.debug(f"HttpCallback: Connection closed, code={close_status_code}, msg={close_msg}")
        self.complete_event.set()

    def on_event(self, response: str) -> None:
        try:
            type = response.get('type')
            logger.debug(f"HttpCallback: Received event type={type}")
            if 'response.audio.delta' == type:
                recv_audio_b64 = response.get('delta')
                if recv_audio_b64:
                    audio_bytes = base64.b64decode(recv_audio_b64)
                    self.buffer.write(audio_bytes)
                    logger.debug(f"HttpCallback: Appended {len(audio_bytes)} bytes to buffer")
            elif 'response.done' == type:
                logger.debug('HttpCallback: Done event received')
                self.usage_characters = response.get('response', {}).get('usage', {}).get('characters', 0)
            elif 'session.finished' == type:
                logger.debug("HttpCallback: Session finished")
                self.complete_event.set()
            elif 'error' == type:
                self.error_msg = response.get('message', 'Unknown error')
                logger.error(f"HttpCallback: Error event received: {self.error_msg}")
                self.complete_event.set()
        except Exception as e:
            logger.exception(f"HttpCallback: Exception in on_event: {str(e)}")
            self.error_msg = str(e)
            self.complete_event.set()

    def wait_for_finished(self, timeout=30):
        return self.complete_event.wait(timeout=timeout)

    def get_audio_data(self):
        return self.buffer.getvalue()
    def get_usage_characters(self):
        return str(self.usage_characters)


class SSECallback(QwenTtsRealtimeCallback):
    def __init__(self):
        self.queue = queue.Queue()
        self.error_msg = None
        self.usage_characters = 0

    def on_open(self) -> None:
        logger.debug("SSECallback: Connection opened")

    def on_close(self, close_status_code, close_msg) -> None:
        logger.debug(f"SSECallback: Connection closed, code={close_status_code}, msg={close_msg}")
        self.queue.put(None)

    def on_event(self, response: dict) -> None:
        try:
            type = response.get('type')
            logger.debug(f"SSECallback: Received event type={type}")
            if 'response.audio.delta' == type:
                audio_delta = response.get('delta')
                if audio_delta:
                    logger.debug(f"SSECallback: Received audio delta, size={len(audio_delta)}")
                    self.queue.put({"audio": audio_delta, "is_end": False})
            elif 'response.done' == type:
                logger.debug('HttpCallback: Done event received')
                self.usage_characters = response.get('response', {}).get('usage', {}).get('characters', 0)
            elif 'session.finished' == type:
                logger.debug("SSECallback: Session finished")
                self.queue.put(None)
            elif 'error' == type:
                self.error_msg = response.get('message', 'Unknown error')
                logger.error(f"SSECallback: Error event received: {self.error_msg}")
                self.queue.put({"error": self.error_msg})
                self.queue.put(None)
        except Exception as e:
            logger.exception(f"SSECallback: Exception in on_event: {str(e)}")
            self.error_msg = str(e)
            self.queue.put({"error": self.error_msg})
            self.queue.put(None)

    def get_usage_characters(self):
        return str(self.usage_characters)