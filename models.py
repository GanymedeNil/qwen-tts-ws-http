from pydantic import BaseModel
from typing import Optional

class TTSRequest(BaseModel):
    text: str
    model: str
    voice: Optional[str] = 'Cherry'
    language_type: Optional[str] = 'Auto'
    sample_rate: Optional[int] = 24000
    speech_rate: Optional[float] = 1.0
    volume: Optional[float] = 50
    pitch_rate: Optional[float] = 1.0
    return_url: Optional[bool] = False
