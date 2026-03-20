"""Cloud storage connectors — download files from S3, GCS, and Azure Blob.

Detects cloud URLs by prefix:
  s3://bucket/key       → AWS S3
  gs://bucket/key       → Google Cloud Storage
  az://container/blob   → Azure Blob Storage

Each connector downloads to a temp file and returns the local path.
The caller is responsible for cleanup.
"""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _retry_download(func, *args, max_retries: int = 3, base_delay: float = 1.0, **kwargs):
    """Retry a download function with exponential backoff on transient errors."""
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt >= max_retries:
                raise
            # Retry on common transient errors
            exc_name = type(e).__name__
            if any(kw in exc_name for kw in ("Timeout", "Connection", "BrokenPipe", "Reset")):
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Cloud download failed (attempt %d/%d): %s — retrying in %.1fs",
                    attempt + 1,
                    max_retries + 1,
                    e,
                    delay,
                )
                time.sleep(delay)
                continue
            raise  # non-transient error, don't retry
    raise last_exc


def is_cloud_url(path: str) -> bool:
    """Check if a string is a cloud storage URL."""
    return path.startswith("s3://") or path.startswith("gs://") or path.startswith("az://")


def fetch_cloud(url: str, max_bytes: int | None = None) -> Path:
    """Download a file from cloud storage to a temp file.

    Args:
        url: Cloud storage URL (s3://, gs://, az://)
        max_bytes: Maximum file size in bytes (raises if exceeded)

    Returns:
        Path to the downloaded temp file
    """
    if url.startswith("s3://"):
        return _fetch_s3(url, max_bytes)
    elif url.startswith("gs://"):
        return _fetch_gcs(url, max_bytes)
    elif url.startswith("az://"):
        return _fetch_azure(url, max_bytes)
    else:
        raise ValueError(f"Unknown cloud URL scheme: {url}")


def _parse_s3_url(url: str) -> tuple[str, str]:
    """Parse s3://bucket/key into (bucket, key)."""
    path = url[5:]  # strip "s3://"
    parts = path.split("/", 1)
    if len(parts) != 2 or not parts[1]:
        raise ValueError(f"Invalid S3 URL: {url}. Expected s3://bucket/key")
    return parts[0], parts[1]


def _parse_gcs_url(url: str) -> tuple[str, str]:
    """Parse gs://bucket/key into (bucket, key)."""
    path = url[5:]  # strip "gs://"
    parts = path.split("/", 1)
    if len(parts) != 2 or not parts[1]:
        raise ValueError(f"Invalid GCS URL: {url}. Expected gs://bucket/key")
    return parts[0], parts[1]


def _parse_azure_url(url: str) -> tuple[str, str]:
    """Parse az://container/blob into (container, blob_name)."""
    path = url[5:]  # strip "az://"
    parts = path.split("/", 1)
    if len(parts) != 2 or not parts[1]:
        raise ValueError(f"Invalid Azure URL: {url}. Expected az://container/blob")
    return parts[0], parts[1]


def _fetch_s3(url: str, max_bytes: int | None = None) -> Path:
    """Download a file from AWS S3."""
    try:
        import boto3
    except ImportError:
        raise ImportError("S3 support requires boto3. Install with: pip install ingestible[cloud]")

    bucket, key = _parse_s3_url(url)
    ext = Path(key).suffix or ".bin"
    logger.info("Downloading from S3: %s/%s", bucket, key)

    s3 = boto3.client("s3")

    # Check size before download
    if max_bytes is not None:
        head = s3.head_object(Bucket=bucket, Key=key)
        size = head.get("ContentLength", 0)
        if size > max_bytes:
            raise ValueError(f"S3 object too large ({size} bytes). Max: {max_bytes} bytes")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    tmp.close()
    # Download with retry
    _retry_download(s3.download_file, bucket, key, tmp.name)
    logger.info("Downloaded S3 object to %s", tmp.name)
    return Path(tmp.name)


def _fetch_gcs(url: str, max_bytes: int | None = None) -> Path:
    """Download a file from Google Cloud Storage."""
    try:
        from google.cloud import storage
    except ImportError:
        raise ImportError(
            "GCS support requires google-cloud-storage. Install with: pip install ingestible[cloud]"
        )

    bucket_name, blob_name = _parse_gcs_url(url)
    ext = Path(blob_name).suffix or ".bin"
    logger.info("Downloading from GCS: %s/%s", bucket_name, blob_name)

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)

    # Check size before download
    if max_bytes is not None:
        blob.reload()
        if blob.size and blob.size > max_bytes:
            raise ValueError(f"GCS object too large ({blob.size} bytes). Max: {max_bytes} bytes")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    tmp.close()
    _retry_download(blob.download_to_filename, tmp.name)
    logger.info("Downloaded GCS object to %s", tmp.name)
    return Path(tmp.name)


def _fetch_azure(url: str, max_bytes: int | None = None) -> Path:
    """Download a file from Azure Blob Storage."""
    try:
        from azure.storage.blob import BlobServiceClient
    except ImportError:
        raise ImportError(
            "Azure Blob support requires azure-storage-blob. "
            "Install with: pip install ingestible[cloud]"
        )

    import os

    container_name, blob_name = _parse_azure_url(url)
    ext = Path(blob_name).suffix or ".bin"
    logger.info("Downloading from Azure Blob: %s/%s", container_name, blob_name)

    # Connection string from environment
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    if not conn_str:
        raise ValueError(
            "AZURE_STORAGE_CONNECTION_STRING environment variable is required for Azure Blob access"
        )

    client = BlobServiceClient.from_connection_string(conn_str)
    blob_client = client.get_blob_client(container=container_name, blob=blob_name)

    # Check size before download
    if max_bytes is not None:
        props = blob_client.get_blob_properties()
        if props.size and props.size > max_bytes:
            raise ValueError(f"Azure blob too large ({props.size} bytes). Max: {max_bytes} bytes")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    tmp.close()

    def _do_azure_download():
        with open(tmp.name, "wb") as f:
            download = blob_client.download_blob()
            download.readinto(f)

    _retry_download(_do_azure_download)
    logger.info("Downloaded Azure blob to %s", tmp.name)
    return Path(tmp.name)
