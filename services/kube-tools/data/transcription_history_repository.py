from datetime import datetime
from typing import List, Optional, Dict, Any
from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient


class TranscriptionHistoryRepository(MongoRepositoryAsync):
    """Repository for storing and retrieving transcription history."""

    def __init__(self, client: AsyncIOMotorClient):
        super().__init__(
            client=client,
            database='Transcriptions',
            collection='TranscriptionHistory'
        )

    async def save_transcription(
        self,
        filename: str,
        transcribed_text: str,
        language: Optional[str] = None,
        file_size: Optional[int] = None,
        duration: Optional[float] = None,
        user_id: Optional[str] = None
    ) -> str:
        """
        Save a transcription record to the database.

        Args:
            filename: Original audio file name
            transcribed_text: The transcribed text
            language: Language code (e.g., 'en', 'es', 'fr')
            file_size: Size of the audio file in bytes
            duration: Duration of transcription process in seconds
            user_id: Optional user identifier

        Returns:
            The inserted document's _id as string
        """
        document = {
            'filename': filename,
            'transcribed_text': transcribed_text,
            'language': language,
            'file_size': file_size,
            'duration': duration,
            'user_id': user_id,
            'created_date': datetime.utcnow(),
            'text_length': len(transcribed_text)
        }

        result = await self.collection.insert_one(document)
        return str(result.inserted_id)

    async def get_transcriptions(
        self,
        limit: int = 50,
        skip: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Retrieve transcription history.

        Args:
            limit: Maximum number of records to return
            skip: Number of records to skip (for pagination)

        Returns:
            List of transcription documents
        """
        cursor = (
            self.collection
            .find({})
            .sort('created_date', -1)  # Most recent first
            .skip(skip)
            .limit(limit)
        )

        results = []
        async for document in cursor:
            # Convert ObjectId to string for JSON serialization
            document['_id'] = str(document['_id'])
            results.append(document)

        return results
