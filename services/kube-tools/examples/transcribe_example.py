#!/usr/bin/env python3
"""
Example script demonstrating how to use the /api/transcribe endpoint.

This script shows both curl command examples and a Python client example.
"""

import asyncio
import aiohttp
import os

# Example curl commands for testing the transcribe endpoint:

CURL_EXAMPLES = """
# Basic transcription (auto-detect language):
curl -X POST "http://localhost:5000/api/transcribe" \
     -H "Authorization: Bearer <your-token>" \
     -F "audio=@recording.mp3"

# Transcription with explicit language:
curl -X POST "http://localhost:5000/api/transcribe" \
     -H "Authorization: Bearer <your-token>" \
     -F "audio=@recording.wav" \
     -F "language=en"

# Transcription with different audio formats:
curl -X POST "http://localhost:5000/api/transcribe" \
     -H "Authorization: Bearer <your-token>" \
     -F "audio=@recording.m4a"
"""


async def test_transcribe_endpoint():
    """
    Example Python client for testing the transcribe endpoint.
    """

    # Configuration
    base_url = "http://localhost:5000"
    token = os.getenv("API_TOKEN", "your-token-here")
    audio_file_path = "test_audio.mp3"  # Replace with actual audio file

    # Check if audio file exists
    if not os.path.exists(audio_file_path):
        print(f"Audio file not found: {audio_file_path}")
        print("Please provide a valid audio file path for testing.")
        return

    headers = {
        "Authorization": f"Bearer {token}"
    }

    # Prepare multipart form data
    data = aiohttp.FormData()
    data.add_field('audio',
                   open(audio_file_path, 'rb'),
                   filename=os.path.basename(audio_file_path),
                   content_type='audio/mpeg')
    data.add_field('language', 'en')  # Optional language specification

    async with aiohttp.ClientSession() as session:
        try:
            print(f"Sending transcription request for: {audio_file_path}")

            async with session.post(
                f"{base_url}/api/transcribe",
                headers=headers,
                data=data
            ) as response:

                if response.status == 200:
                    result = await response.json()
                    print(f"Transcription successful!")
                    print(f"Text: {result['text']}")
                else:
                    error_data = await response.json()
                    print(f"Transcription failed with status {response.status}")
                    print(f"Error: {error_data.get('error', 'Unknown error')}")

        except Exception as e:
            print(f"Request failed: {str(e)}")

if __name__ == "__main__":
    print("=== Audio Transcription Endpoint Examples ===")
    print("\n1. Curl Examples:")
    print(CURL_EXAMPLES)

    print("\n2. Python Client Test:")
    print("Running Python client test...")

    # Uncomment the line below to run the Python client test
    # asyncio.run(test_transcribe_endpoint())
