"""Transcription HTTP routes.

Endpoints
---------
POST  /api/transcribe                              — upload audio + transcribe
GET   /api/transcribe/history                      — legacy history list
POST  /api/transcription/feedback                  — flag a bad transcription
GET   /api/transcription/feedback                  — list feedback rows
GET   /api/transcription/feedback/<transcription_id> — full row + audio link
GET   /api/transcription/audio/<storage_ref>       — stream retained GridFS audio
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Dict, Optional

from quart import Blueprint, Response, request

from data.transcription_history_repository import TranscriptionHistoryRepository
from data.transcription_run_repository import TranscriptionRunRepository
from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from services.transcription.upload_cache import UploadCache
from services.transcription_service import TranscriptionService, TranscriptionServiceError
from utilities.memory import release_memory

logger = get_logger(__name__)

transcription_bp = MetaBlueprint("transcription_bp", __name__)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Transcribe
# ---------------------------------------------------------------------------

@transcription_bp.configure("/api/transcribe", methods=["POST"], auth_scheme="default")
async def transcribe_audio(container):
    """Upload audio + transcribe.

    Form fields:
      - ``audio`` (file, required)
      - ``language`` (str, optional)
      - ``diarize`` (bool, default false)
      - ``return_waveform`` (bool, default false)
      - ``provider`` (str, optional) — override the configured speech-to-text
        engine. Supported: ``openai``, ``azure``, ``google``, ``whisper``.
    """
    try:
        transcription_service: TranscriptionService = container.resolve(TranscriptionService)
        upload_cache: UploadCache = container.resolve(UploadCache)

        files = await request.files
        form_data = await request.form
        if "audio" not in files:
            return {"error": "No audio file provided. Use the 'audio' form field."}, 400

        audio_file = files["audio"]
        if not audio_file.filename:
            return {"error": "Invalid audio file: missing filename"}, 400

        language = form_data.get("language")
        diarize = form_data.get("diarize", "false").lower() in ("true", "1", "yes")
        return_waveform = form_data.get("return_waveform", "false").lower() in ("true", "1", "yes")
        provider_name = form_data.get("provider") or None

        audio_data = audio_file.read()
        file_size = len(audio_data)
        upload_id = await upload_cache.put(audio_data)

        audio_stream = io.BytesIO(audio_data)
        del audio_data

        try:
            result = await transcription_service.transcribe_audio(
                audio_file=audio_stream,
                filename=audio_file.filename,
                upload_id=upload_id,
                language=language,
                file_size=file_size,
                diarize=diarize,
                return_waveform_overlay=return_waveform,
                provider_name=provider_name,
            )
        except ValueError as e:
            # Unknown provider name from get_provider().
            return {"error": str(e)}, 400
        audio_stream.close()
        release_memory()

        return result, 200

    except TranscriptionServiceError as e:
        logger.error(f"Transcription service error: {e}")
        return {"error": f"Transcription failed: {e}"}, 500
    except Exception as e:
        logger.error(f"Unexpected error during transcription: {e}", exc_info=True)
        return {"error": f"Unexpected error: {type(e).__name__}: {e}"}, 500


# ---------------------------------------------------------------------------
# Legacy history
# ---------------------------------------------------------------------------

@transcription_bp.configure("/api/transcribe/history", methods=["GET"], auth_scheme="default")
async def get_transcription_history(container):
    try:
        repo: TranscriptionHistoryRepository = container.resolve(TranscriptionHistoryRepository)
        try:
            limit = int(request.args.get("limit", 50))
            skip = int(request.args.get("skip", 0))
        except ValueError as e:
            return {"error": f"Invalid limit/skip: {e}"}, 400
        limit = max(1, min(limit, 100))
        skip = max(0, skip)
        transcriptions = await repo.get_transcriptions(limit=limit, skip=skip)
        return {"transcriptions": transcriptions}, 200
    except Exception as e:
        logger.error(f"Error retrieving transcription history: {e}", exc_info=True)
        return {"error": f"Unexpected error: {type(e).__name__}: {e}"}, 500


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

@transcription_bp.configure("/api/transcription/feedback", methods=["POST"], auth_scheme="default")
async def submit_feedback(container):
    """Flag a transcription as bad and (best-effort) retain its audio."""
    try:
        runs: TranscriptionRunRepository = container.resolve(TranscriptionRunRepository)
        upload_cache: UploadCache = container.resolve(UploadCache)
        body: Dict[str, Any] = await request.get_json() or {}

        transcription_id = body.get("transcription_id")
        if not transcription_id:
            return {"error": "transcription_id is required"}, 400

        run = await runs.get_run(transcription_id)
        if run is None:
            return {"error": f"transcription_id {transcription_id} not found"}, 404

        upload_id = run.get("upload_id")
        audio_status = "upload_expired"
        audio_storage_ref: Optional[str] = run.get("audio_storage_ref")

        if upload_id:
            audio_bytes = await upload_cache.get(upload_id)
            if audio_bytes is not None:
                audio_storage_ref = await runs.store_audio(
                    audio_bytes=audio_bytes,
                    filename=run.get("filename") or f"{transcription_id}.bin",
                    transcription_id=transcription_id,
                )
                audio_status = "retained"
            else:
                logger.info("feedback: upload expired id=%s tx=%s", upload_id, transcription_id)

        feedback = {
            "rating": "bad",
            "reason": body.get("reason"),
            "notes": body.get("notes"),
            "submitted_at": datetime.utcnow(),
        }
        await runs.set_feedback(
            transcription_id=transcription_id,
            feedback=feedback,
            audio_status=audio_status,
            audio_storage_ref=audio_storage_ref,
        )
        return {"status": "ok", "audio_retained": audio_status == "retained"}, 200
    except Exception as e:
        logger.error(f"feedback submit failed: {e}", exc_info=True)
        return {"error": f"Unexpected error: {type(e).__name__}: {e}"}, 500


@transcription_bp.configure("/api/transcription/feedback", methods=["GET"], auth_scheme="default")
async def list_feedback(container):
    """Paginated list of runs with feedback != null."""
    try:
        runs: TranscriptionRunRepository = container.resolve(TranscriptionRunRepository)
        try:
            limit = int(request.args.get("limit", 50))
            offset = int(request.args.get("offset", 0))
        except ValueError as e:
            return {"error": f"Invalid limit/offset: {e}"}, 400
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        verbose = request.args.get("verbose", "false").lower() in ("true", "1", "yes")

        results = await runs.list_with_feedback(
            pipeline_version=request.args.get("pipeline_version"),
            reason=request.args.get("reason"),
            after=_parse_iso(request.args.get("after")),
            before=_parse_iso(request.args.get("before")),
            limit=limit, offset=offset, verbose=verbose,
        )
        return {"results": results, "count": len(results)}, 200
    except Exception as e:
        logger.error(f"feedback list failed: {e}", exc_info=True)
        return {"error": f"Unexpected error: {type(e).__name__}: {e}"}, 500


@transcription_bp.configure(
    "/api/transcription/feedback/<transcription_id>", methods=["GET"], auth_scheme="default",
)
async def get_feedback_detail(container, transcription_id: str):
    """Full row including VAD stream and chunk plan."""
    try:
        runs: TranscriptionRunRepository = container.resolve(TranscriptionRunRepository)
        run = await runs.get_run(transcription_id)
        if run is None:
            return {"error": f"transcription_id {transcription_id} not found"}, 404

        if run.get("audio_storage_ref"):
            run["audio_url"] = f"/api/transcription/audio/{run['audio_storage_ref']}"
        return run, 200
    except Exception as e:
        logger.error(f"feedback detail failed: {e}", exc_info=True)
        return {"error": f"Unexpected error: {type(e).__name__}: {e}"}, 500


@transcription_bp.configure(
    "/api/transcription/audio/<storage_ref>", methods=["GET"], auth_scheme="default",
)
async def stream_retained_audio(container, storage_ref: str):
    """Stream audio bytes from GridFS by storage ref."""
    try:
        runs: TranscriptionRunRepository = container.resolve(TranscriptionRunRepository)
        data = await runs.fetch_audio(storage_ref)
        if data is None:
            return {"error": f"audio ref {storage_ref} not found"}, 404
        return Response(data, mimetype="application/octet-stream")
    except Exception as e:
        logger.error(f"audio stream failed: {e}", exc_info=True)
        return {"error": f"Unexpected error: {type(e).__name__}: {e}"}, 500
