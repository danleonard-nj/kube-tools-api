import io
import pytest
from quart import Quart
from services.calendar_service import CalendarService
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_create_event_from_image(monkeypatch):
    # Arrange
    fake_image = b"fake_image_bytes"
    fake_text = "Meeting at 10am"
    fake_gpt_result = '{"summary": "Test Event", "start": {"dateTime": "2025-06-15T10:00:00"}, "end": {"dateTime": "2025-06-15T11:00:00"}}'
    fake_event = {"id": "123", "summary": "Test Event"}

    service = CalendarService(
        auth_service=AsyncMock(),
        repository=AsyncMock(),
        gpt_client=AsyncMock(),
        config=AsyncMock()
    )
    service._gpt_client.generate_response_with_image = AsyncMock(return_value=fake_gpt_result)
    service.create_calendar_event = AsyncMock(return_value=fake_event)

    # Act
    result = await service.create_event_from_image(fake_image, fake_text)

    # Assert
    assert "event" in result
    assert result["event"]["summary"] == "Test Event"
