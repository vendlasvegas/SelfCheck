# models/image_loader.py
import io
import logging
from pathlib import Path
from PIL import Image
import googleapiclient.http
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

class GoogleDriveImageLoader:
    """Handles loading images from Google Drive folder with caching."""

    def __init__(self, credentials_path, folder_id):
        self.folder_id = folder_id
        self.cache_dir = Path.home() / "SelfCheck" / "ImageCache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.file_map = {}  # filename -> file_id mapping
        self.drive_service = None
        self._init_drive_service(credentials_path)

    def _init_drive_service(self, credentials_path):
        """Initialize Google Drive API service."""
        try:
            scopes = [
                "https://www.googleapis.com/auth/drive.readonly",
            ]
            creds = Credentials.from_service_account_file(str(credentials_path), scopes=scopes)
            self.drive_service = build('drive', 'v3', credentials=creds)
            self._build_file_map()
            logging.info("Google Drive service initialized successfully")
        except Exception as e:
            logging.error("Failed to initialize Google Drive service: %s", e)
            self.drive_service = None

    def _build_file_map(self):
        """Build a mapping of filename to file_id for the specified folder."""
        if not self.drive_service:
            return

        try:
            query = f"'{self.folder_id}' in parents and trashed=false"
            results = self.drive_service.files().list(
                q=query,
                fields="files(id, name)"
            ).execute()

            files = results.get('files', [])
            self.file_map = {file['name']: file['id'] for file in files}
            logging.info("Found %d files in Google Drive folder", len(self.file_map))

        except Exception as e:
            logging.error("Failed to build file map from Google Drive: %s", e)

    def get_image(self, filename):
        """
        Get image from Google Drive, with local caching.
        Returns PIL Image object or None if not found.
        """
        if not filename or not self.drive_service:
            return None

        # Check local cache first
        cache_path = self.cache_dir / filename
        if cache_path.exists():
            try:
                return Image.open(cache_path)
            except Exception as e:
                logging.warning("Failed to load cached image %s: %s", filename, e)
                # Remove corrupted cache file
                try:
                    cache_path.unlink()
                except:
                    pass

        # Download from Google Drive
        file_id = self.file_map.get(filename)
        if not file_id:
            logging.warning("File not found in Google Drive: %s", filename)
            return None

        try:
            # Download file content
            request = self.drive_service.files().get_media(fileId=file_id)
            file_content = io.BytesIO()

            downloader = googleapiclient.http.MediaIoBaseDownload(file_content, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()

            # Save to cache
            file_content.seek(0)
            with open(cache_path, 'wb') as f:
                f.write(file_content.read())

            # Load as PIL Image
            file_content.seek(0)
            image = Image.open(file_content)
            logging.info("Downloaded and cached image: %s", filename)
            return image

        except Exception as e:
            logging.error("Failed to download image %s from Google Drive: %s", filename, e)
            return None
