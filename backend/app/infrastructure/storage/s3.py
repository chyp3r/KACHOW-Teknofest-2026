import asyncio
import logging
from typing import Any

import boto3
from botocore.exceptions import ClientError

from app.infrastructure.storage.base import BaseStorage

logger = logging.getLogger(__name__)


class S3Storage(BaseStorage):
    """S3-compatible Object Storage implementation using boto3 (compatible with AWS S3 and MinIO)."""

    def __init__(
        self, bucket_name: str, endpoint_url: str, access_key: str, secret_key: str
    ):
        """Initialize S3 Storage client and ensure bucket exists.

        Args:
            bucket_name: Name of the bucket.
            endpoint_url: S3/MinIO API URL.
            access_key: API Access Key.
            secret_key: API Secret Key.
        """
        self.bucket_name = bucket_name
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

        # Pre-verify or create bucket
        try:
            self.s3_client.create_bucket(Bucket=bucket_name)
            logger.info(f"S3 bucket '{bucket_name}' verified/created.")
        except ClientError as e:
            # Bucket might already exist or permissions might prevent creation
            logger.debug(f"Bucket creation check warning: {e}")

    async def put_file(self, file_path: str, content: bytes) -> str:
        """Upload file content asynchronously to S3/MinIO."""
        def _upload():
            self.s3_client.put_object(
                Bucket=self.bucket_name, Key=file_path, Body=content
            )

        await asyncio.to_thread(_upload)
        logger.debug(f"Uploaded file to S3: {file_path}")
        return f"s3://{self.bucket_name}/{file_path}"

    async def get_file(self, file_path: str) -> bytes:
        """Download file content asynchronously from S3/MinIO."""
        def _download():
            try:
                response = self.s3_client.get_object(
                    Bucket=self.bucket_name, Key=file_path
                )
                return response["Body"].read()
            except ClientError as e:
                if e.response["Error"]["Code"] == "NoSuchKey":
                    raise FileNotFoundError(f"S3 file not found: {file_path}")
                raise

        return await asyncio.to_thread(_download)

    async def delete_file(self, file_path: str) -> bool:
        """Delete file asynchronously from S3/MinIO."""
        def _delete():
            try:
                self.s3_client.delete_object(
                    Bucket=self.bucket_name, Key=file_path
                )
                return True
            except Exception as e:
                logger.error(
                    f"S3 file deletion failed for key={file_path}: {e}"
                )
                return False

        return await asyncio.to_thread(_delete)
