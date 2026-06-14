import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Optional
import boto3
from botocore.client import Config
from .config import Settings

class Storage(ABC):
    @abstractmethod
    def save_file(self, file_path: str, data: BinaryIO) -> str:
        """Save binary data to the storage and return its path/key."""
        pass

    @abstractmethod
    def get_file(self, file_key: str) -> bytes:
        """Get file data as bytes."""
        pass

    @abstractmethod
    def delete_file(self, file_key: str) -> None:
        """Delete a file from storage."""
        pass


class LocalStorage(Storage):
    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def save_file(self, file_path: str, data: BinaryIO) -> str:
        dest_path = self.base_path / file_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(data.read())
        return file_path

    def get_file(self, file_key: str) -> bytes:
        src_path = self.base_path / file_key
        if not src_path.exists():
            raise FileNotFoundError(f"File not found: {file_key}")
        with open(src_path, "rb") as f:
            return f.read()

    def delete_file(self, file_key: str) -> None:
        src_path = self.base_path / file_key
        if src_path.exists():
            os.remove(src_path)


class S3Storage(Storage):
    def __init__(self, bucket: str, endpoint_url: Optional[str], access_key: Optional[str], secret_key: Optional[str]):
        self.bucket = bucket
        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4")
        )

    def save_file(self, file_path: str, data: BinaryIO) -> str:
        self.s3.upload_fileobj(data, self.bucket, file_path)
        return file_path

    def get_file(self, file_key: str) -> bytes:
        import io
        buf = io.BytesIO()
        self.s3.download_fileobj(self.bucket, file_key, buf)
        return buf.getvalue()

    def delete_file(self, file_key: str) -> None:
        self.s3.delete_object(Bucket=self.bucket, Key=file_key)


def get_storage(settings: Settings) -> Storage:
    if settings.storage_provider == "s3":
        if not settings.s3_bucket:
            raise ValueError("s3_bucket must be set when storage_provider is 's3'")
        return S3Storage(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key
        )
    return LocalStorage(settings.storage_local_path)
