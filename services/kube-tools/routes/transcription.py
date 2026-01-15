import io
from quart import Blueprint, Response, request
from framework.rest.blueprints.meta import MetaBlueprint
from framework.logger.providers import get_logger
from services.transcription_service import TranscriptionService, TranscriptionServiceError

logger = get_logger(__name__)

# Create blueprint following the established pattern
transcription_bp = MetaBlueprint('transcription_bp', __name__)


@transcription_bp.configure('/api/transcribe', methods=['POST'], auth_scheme='default')
async def transcribe_audio(container):
    """
    Endpoint to transcribe uploaded audio files using OpenAI's Whisper model.

    Expected request:
    - Content-Type: multipart/form-data
    - Form field 'audio': audio file (supports various formats: mp3, wav, m4a, etc.)
    - Optional form field 'language': language code (e.g., 'en', 'es', 'fr')

    Returns:
    - JSON response: { "text": "transcribed text here" }

    Example usage with curl:
    curl -X POST "http://localhost:5000/api/transcribe" \
         -H "Authorization: Bearer <token>" \
         -F "audio=@recording.mp3" \
         -F "language=en"
    """
    try:
        # Resolve the transcription service from DI container
        transcription_service: TranscriptionService = container.resolve(TranscriptionService)

        logger.info("Processing transcription request")

        # Get the uploaded files from the multipart form
        files = await request.files
        form_data = await request.form

        # Check if audio file was provided
        if 'audio' not in files:
            return {'error': 'No audio file provided. Please upload an audio file using the "audio" form field.'}, 400

        audio_file = files['audio']
        if not audio_file.filename:
            return {'error': 'Invalid audio file. No filename provided.'}, 400

        # Get optional language parameter
        language = form_data.get('language')

        logger.info(f"Received audio file: {audio_file.filename}, language: {language or 'auto-detect'}")

        # Read the audio file data into memory
        audio_data = await audio_file.read()
        audio_stream = io.BytesIO(audio_data)

        # Perform transcription
        transcribed_text = await transcription_service.transcribe_audio(
            audio_file=audio_stream,
            filename=audio_file.filename,
            language=language
        )

        # Return the transcribed text in the expected JSON format
        return {'text': transcribed_text}, 200

    except TranscriptionServiceError as e:
        logger.error(f"Transcription service error: {str(e)}")
        return {'error': f'Transcription failed: {str(e)}'}, 500

    except Exception as e:
        logger.error(f"Unexpected error during transcription: {str(e)}")
        return {'error': 'An unexpected error occurred during transcription'}, 500
