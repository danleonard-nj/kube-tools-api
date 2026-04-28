"""Transcription HTTP routes.

Endpoints
---------
POST  /api/transcribe                              — upload audio + transcribe
GET   /api/transcribe/history                      — legacy history list
POST  /api/transcription/feedback                  — flag a bad transcription
GET   /api/transcription/feedback                  — list feedback rows
GET   /api/transcription/feedback/<transcription_id> — full row + audio link
GET   /api/transcription/audio/<storage_ref>       — stream retained GridFS audio
POST  /api/transcription/internal/archive          — async worker: archive Opus + PNG
GET   /api/transcription/archive/<storage_ref>     — stream archived audio/overlay
"""

from __future__ import annotations

import base64
import io
from datetime import datetime
from typing import Any, Dict, Optional

from quart import Blueprint, Response, request

from data.transcription_history_repository import TranscriptionHistoryRepository
from data.transcription_run_repository import TranscriptionRunRepository
from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from services.event_service import EventService
from services.transcription.opus_encoder import (
    CODEC as OPUS_CODEC,
    CONTENT_TYPE as OPUS_CONTENT_TYPE,
    FILE_EXT as OPUS_FILE_EXT,
    OpusEncodeError,
    encode_opus,
)
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
      - ``polish`` (bool, default false) — run an LLM cleanup pass over the
        merged transcript (skipped automatically when ``diarize`` is true).
      - ``polish_model`` (str, optional) — override the polish model
        (defaults to ``gpt-4o-mini``).
      - ``archive`` (bool, default true) — dispatch the async archive
        event after a successful transcription.  Set to false during
        local debugging to skip Service Bus / GridFS round-tripping.
    """
    try:
        transcription_service: TranscriptionService = container.resolve(TranscriptionService)
        upload_cache: UploadCache = container.resolve(UploadCache)
        event_service: EventService = container.resolve(EventService)

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
        polish = form_data.get("polish", "false").lower() in ("true", "1", "yes")
        polish_model = form_data.get("polish_model") or None
        archive = form_data.get("archive", "true").lower() in ("true", "1", "yes")

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
                polish=polish,
                polish_model=polish_model,
            )
        except ValueError as e:
            # Unknown provider name from get_provider().
            return {"error": str(e)}, 400
        audio_stream.close()
        release_memory()

        # Fan out the archive job. Best-effort: failures here must not
        # break the user-visible transcription response.
        transcription_id = result.get("transcription_id") if isinstance(result, dict) else None
        if transcription_id and archive:
            try:
                await event_service.dispatch_transcription_archive(
                    transcription_id=transcription_id,
                    upload_id=upload_id,
                )
            except Exception as exc:
                logger.warning(
                    f"archive event dispatch failed tx={transcription_id}: {exc}",
                    exc_info=True,
                )
        elif transcription_id and not archive:
            logger.info(
                f"archive: skipped (archive=false) tx={transcription_id}"
            )

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
        if run.get("archive_audio_ref"):
            run["archive_audio_url"] = f"/api/transcription/archive/{run['archive_audio_ref']}"
        if run.get("archive_overlay_ref"):
            run["archive_overlay_url"] = f"/api/transcription/archive/{run['archive_overlay_ref']}"
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


# ---------------------------------------------------------------------------
# Archive (lossy, every successful transcription)
# ---------------------------------------------------------------------------

@transcription_bp.configure(
    "/api/transcription/internal/archive", methods=["POST"], auth_scheme="default",
)
async def archive_transcription(container):
    """Internal endpoint invoked by the async event relay.

    Body: ``{transcription_id, upload_id}``.

    Idempotent: a run that already has ``archive_audio_ref`` short-circuits.
    Upload-cache miss is logged and acked (returns 200) so the worker
    doesn't loop on permanently-expired uploads.
    """
    try:
        runs: TranscriptionRunRepository = container.resolve(TranscriptionRunRepository)
        upload_cache: UploadCache = container.resolve(UploadCache)

        body: Dict[str, Any] = await request.get_json() or {}
        transcription_id = body.get("transcription_id")
        upload_id = body.get("upload_id")
        if not transcription_id or not upload_id:
            return {"error": "transcription_id and upload_id are required"}, 400

        run = await runs.get_run(transcription_id)
        if run is None:
            # Nothing to archive against — ack to avoid retry storms.
            logger.warning(
                f"archive: run not found tx={transcription_id} upload={upload_id}"
            )
            return {"status": "not_found", "transcription_id": transcription_id}, 200

        already_archived = bool(run.get("archive_audio_ref"))
        if already_archived:
            return {
                "status": "already_archived",
                "transcription_id": transcription_id,
                "archive_audio_ref": run["archive_audio_ref"],
                "archive_overlay_ref": run.get("archive_overlay_ref"),
            }, 200

        # ── Audio: pull from upload cache → encode Opus → store ──
        audio_ref: Optional[str] = None
        audio_size: Optional[int] = None
        encode_status = "skipped"
        audio_bytes = await upload_cache.get(upload_id)
        if audio_bytes is None:
            logger.info(
                f"archive: upload expired tx={transcription_id} upload={upload_id}"
            )
            encode_status = "upload_expired"
        else:
            try:
                opus_bytes = await encode_opus(audio_bytes)
            except OpusEncodeError as exc:
                logger.error(
                    f"archive: opus encode failed tx={transcription_id}: {exc}"
                )
                # Fall through and still try the overlay.
                encode_status = "encode_failed"
            else:
                base = run.get("filename") or transcription_id
                # Strip any existing extension and append .ogg.
                stem = base.rsplit(".", 1)[0] if "." in base else base
                audio_ref = await runs.store_archive_audio(
                    audio_bytes=opus_bytes,
                    filename=f"{stem}.{OPUS_FILE_EXT}",
                    transcription_id=transcription_id,
                    codec=OPUS_CODEC,
                    content_type=OPUS_CONTENT_TYPE,
                )
                audio_size = len(opus_bytes)
                encode_status = "ok"
            finally:
                # Drop the raw bytes from cache once we've handled them
                # to free Redis memory ahead of TTL.  Safe because the
                # feedback path also tries the cache but tolerates miss.
                try:
                    await upload_cache.delete(upload_id)
                except Exception:
                    pass

        # ── Overlay: lift the inline base64 PNG off the run doc into GridFS ──
        overlay_ref: Optional[str] = None
        overlay_size: Optional[int] = None
        clear_inline_overlay = False
        inline_overlay = run.get("waveform_overlay")
        if inline_overlay:
            try:
                png_bytes = base64.b64decode(inline_overlay)
                overlay_ref = await runs.store_archive_overlay(
                    png_bytes=png_bytes,
                    transcription_id=transcription_id,
                )
                overlay_size = len(png_bytes)
                clear_inline_overlay = True
            except Exception as exc:
                logger.warning(
                    f"archive: overlay store failed tx={transcription_id}: {exc}"
                )

        await runs.set_archive_refs(
            transcription_id=transcription_id,
            audio_ref=audio_ref,
            audio_codec=OPUS_CODEC if audio_ref else None,
            audio_size_bytes=audio_size,
            overlay_ref=overlay_ref,
            overlay_size_bytes=overlay_size,
            clear_inline_overlay=clear_inline_overlay,
        )

        logger.info(
            f"archive: tx={transcription_id} encode={encode_status} "
            f"audio_ref={audio_ref} overlay_ref={overlay_ref}"
        )
        return {
            "status": "ok",
            "transcription_id": transcription_id,
            "encode_status": encode_status,
            "archive_audio_ref": audio_ref,
            "archive_audio_size_bytes": audio_size,
            "archive_overlay_ref": overlay_ref,
            "archive_overlay_size_bytes": overlay_size,
        }, 200

    except Exception as e:
        logger.error(f"archive endpoint failed: {e}", exc_info=True)
        return {"error": f"Unexpected error: {type(e).__name__}: {e}"}, 500


@transcription_bp.configure(
    "/api/transcription/archive/<storage_ref>", methods=["GET"], auth_scheme="default",
)
async def stream_archive(container, storage_ref: str):
    """Stream archived audio or overlay bytes from GridFS by storage ref."""
    try:
        runs: TranscriptionRunRepository = container.resolve(TranscriptionRunRepository)
        item = await runs.fetch_archive(storage_ref)
        if item is None:
            return {"error": f"archive ref {storage_ref} not found"}, 404
        meta = item.get("metadata") or {}
        mime = meta.get("content_type") or "application/octet-stream"
        return Response(item["data"], mimetype=mime)
    except Exception as e:
        logger.error(f"archive stream failed: {e}", exc_info=True)
        return {"error": f"Unexpected error: {type(e).__name__}: {e}"}, 500

