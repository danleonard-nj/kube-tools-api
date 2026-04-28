"""Configuration model for the transcription pipeline / providers."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class TranscriptionConfig(BaseModel):
    """Selects the active speech-to-text provider and its kwargs.

    Example config block::

        "transcription": {
            "provider": "openai",
            "openai": { "model": "gpt-4o-transcribe" },
            "azure":  { "speech_key": "...", "region": "eastus" },
            "google": { "model": "latest_long" },
            "whisper":{ "model_size": "large-v3", "beam_size": 5 }
        }
    """

    provider: str = "openai"
    openai: Dict[str, Any] = Field(default_factory=dict)
    azure: Dict[str, Any] = Field(default_factory=dict)
    google: Dict[str, Any] = Field(default_factory=dict)
    whisper: Dict[str, Any] = Field(default_factory=dict)

    def kwargs_for(self, provider_name: Optional[str] = None) -> Dict[str, Any]:
        name = (provider_name or self.provider).lower()
        return dict(getattr(self, name, {}) or {})
