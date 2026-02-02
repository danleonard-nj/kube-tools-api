import io
from quart import Blueprint, Response, request
from framework.rest.blueprints.meta import MetaBlueprint
from framework.logger.providers import get_logger
from services.transcription_service import TranscriptionService, TranscriptionServiceError
from data.transcription_history_repository import TranscriptionHistoryRepository

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
    - Optional form field 'diarize': 'true' or 'false' to enable/disable diarization (default: false)

    Returns:
    - JSON response (when diarize=false): { "text": "transcribed text here" }
    - JSON response (when diarize=true): { "text": "full transcript", "segments": [{"start": 0.0, "end": 3.5, "text": "..."}] }

    Example usage with curl:
    curl -X POST "http://localhost:5000/api/transcribe" \
         -H "Authorization: Bearer <token>" \
         -F "audio=@recording.mp3" \
         -F "language=en" \
         -F "diarize=true"
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
            available_fields = list(files.keys())
            available_msg = f" Available form fields: {available_fields}" if available_fields else " No form fields found in request."
            return {
                'error': f'No audio file provided. Please upload an audio file using the "audio" form field.{available_msg}'
            }, 400

        audio_file = files['audio']
        if not audio_file.filename:
            return {
                'error': f'Invalid audio file. No filename provided. (Content-Type: {audio_file.content_type})'
            }, 400

        # Get optional language parameter
        language = form_data.get('language')

        # Get optional diarize parameter (default to false)
        diarize_str = form_data.get('diarize', 'false').lower()
        diarize = diarize_str in ('true', '1', 'yes')

        logger.info(f"Received audio file: {audio_file.filename}, language: {language or 'auto-detect'}, diarize: {diarize}")

        # Read the audio file data into memory
        audio_data = audio_file.read()
        audio_stream = io.BytesIO(audio_data)
        file_size = len(audio_data)

        # Perform transcription
        result = await transcription_service.transcribe_audio(
            audio_file=audio_stream,
            filename=audio_file.filename,
            language=language,
            file_size=file_size,
            diarize=diarize
        )

        # Service returns either a string (non-diarized) or dict (diarized)
        if isinstance(result, dict):
            # Diarized response with segments
            return result, 200
        else:
            # Simple text response
            return {'text': result}, 200

    except TranscriptionServiceError as e:
        file_info = f"File: {audio_file.filename if 'audio_file' in locals() else 'unknown'}, Size: {file_size if 'file_size' in locals() else 'unknown'} bytes, Language: {language if 'language' in locals() else 'auto-detect'}"
        logger.error(f"Transcription service error: {str(e)} - {file_info}")
        return {
            'error': f'Transcription failed: {str(e)} ({file_info})'
        }, 500

    except Exception as e:
        context_info = f"File: {audio_file.filename if 'audio_file' in locals() else 'unknown'}, Size: {file_size if 'file_size' in locals() else 'unknown'} bytes"
        logger.error(f"Unexpected error during transcription: {str(e)} - {context_info}", exc_info=True)
        return {
            'error': f'An unexpected error occurred during transcription. Error: {type(e).__name__}: {str(e)} ({context_info})'
        }, 500


@transcription_bp.configure('/api/transcribe/history', methods=['GET'], auth_scheme='default')
async def get_transcription_history(container):
    """
    Endpoint to retrieve transcription history.

    Query parameters:
    - limit: Number of results to return (default: 50, max: 100)
    - skip: Number of results to skip for pagination (default: 0)

    Returns:
    - JSON response: { "transcriptions": [list of transcription records] }

    Example usage with curl:
    curl -X GET "http://localhost:5000/api/transcribe/history?limit=10&skip=0" \
         -H "Authorization: Bearer <token>"
    """
    try:
        # Resolve the repository from DI container
        transcription_repository: TranscriptionHistoryRepository = container.resolve(TranscriptionHistoryRepository)

        # Get query parameters
        limit = int(request.args.get('limit', 50))
        skip = int(request.args.get('skip', 0))

        # Validate parameters
        if limit > 100:
            limit = 100
        if limit < 1:
            limit = 1
        if skip < 0:
            skip = 0

        logger.info(f"Retrieving transcription history: limit={limit}, skip={skip}")

        # Get transcriptions from repository
        transcriptions = await transcription_repository.get_transcriptions(
            limit=limit,
            skip=skip
        )

        return {'transcriptions': transcriptions}, 200

    except ValueError as e:
        received_params = f"limit: {request.args.get('limit', 'not provided')}, skip: {request.args.get('skip', 'not provided')}"
        return {
            'error': f'Invalid limit or skip parameter. Must be integers. Received - {received_params}. Error: {str(e)}'
        }, 400

    except Exception as e:
        params_info = f"limit: {limit if 'limit' in locals() else 'unknown'}, skip: {skip if 'skip' in locals() else 'unknown'}"
        logger.error(f"Unexpected error retrieving transcription history: {str(e)} - Parameters: {params_info}", exc_info=True)
        return {
            'error': f'An unexpected error occurred while retrieving history. Error: {type(e).__name__}: {str(e)} (Parameters: {params_info})'
        }, 500
