"""Storage adapter for files in / files out.

Integration Standard 7:
Inputs accepted as an upload or a URL.
Outputs saved to S3-compatible storage (MinIO) or local file storage
and returned as download links.
"""

from __future__ import annotations
import os
import shutil
import uuid
from typing import Optional, Tuple
import httpx


class StorageAdapter:
    def __init__(self, base_dir: str = "./data/storage", public_url_base: str = "/api/v1/storage/download"):
        self.base_dir = os.path.abspath(base_dir)
        self.public_url_base = public_url_base
        os.makedirs(self.base_dir, exist_ok=True)

    def save_bytes(self, data: bytes, filename: str) -> Tuple[str, str]:
        """Saves bytes to storage. Returns (absolute_path, download_url)."""
        file_id = f"{uuid.uuid4().hex[:12]}_{filename}"
        dest_path = os.path.join(self.base_dir, file_id)
        with open(dest_path, "wb") as f:
            f.write(data)
        download_url = f"{self.public_url_base}/{file_id}"
        return dest_path, download_url

    def save_file_from_path(self, local_path: str, filename: Optional[str] = None) -> Tuple[str, str]:
        fname = filename or os.path.basename(local_path)
        file_id = f"{uuid.uuid4().hex[:12]}_{fname}"
        dest_path = os.path.join(self.base_dir, file_id)
        shutil.copyfile(local_path, dest_path)
        download_url = f"{self.public_url_base}/{file_id}"
        return dest_path, download_url

    async def ingest_input(self, file_bytes: Optional[bytes] = None, file_name: Optional[str] = None, url: Optional[str] = None) -> Tuple[str, str]:
        """Ingests file either from uploaded bytes or from external URL."""
        if file_bytes is not None and file_name is not None:
            return self.save_bytes(file_bytes, file_name)

        if url is not None:
            # Check if it's already a local file path
            if os.path.isfile(url):
                return self.save_file_from_path(url)

            # Download from remote URL
            fname = os.path.basename(url.split("?")[0]) or "downloaded_media.mp4"
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return self.save_bytes(resp.content, fname)

        raise ValueError("Neither file upload nor URL was provided")


storage = StorageAdapter()

