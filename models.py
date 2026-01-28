from pydantic import BaseModel
from typing import Optional

class TTSRequest(BaseModel):
    text: str
    model: str
    voice: Optional[str] = 'Cherry'
    return_url: Optional[bool] = False
