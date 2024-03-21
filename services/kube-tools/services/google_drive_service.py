from clients.google_drive_client import GoogleDriveClient
from domain.google import GoogleDriveReportModel


class GoogleDriveService:
    def __init__(
        self,
        client: GoogleDriveClient
    ):
        self._google_drive_client = client

    async def get_drive_report(
        self
    ):
        data = await self._google_drive_client.get_drive_file_details()

        results = [GoogleDriveReportModel.from_response(item)
                   for item in data]

        return results
