import io
import base64
import threading
import queue
from dashscope.audio.qwen_tts_realtime import QwenTtsRealtimeCallback

class HttpCallback(QwenTtsRealtimeCallback):
    def __init__(self):
        self.complete_event = threading.Event()
        self.buffer = io.BytesIO()
        self.error_msg = None

    def on_open(self) -> None:
        pass

    def on_close(self, close_status_code, close_msg) -> None:
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
