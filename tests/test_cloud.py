"""Tests for cloud storage URL parsing and detection."""
import pytest

from ingestible.pipeline.cloud import is_cloud_url, _parse_s3_url, _parse_gcs_url, _parse_azure_url


class TestCloudURLDetection:
    def test_s3_url(self):
        assert is_cloud_url("s3://my-bucket/path/to/file.pdf")

    def test_gcs_url(self):
        assert is_cloud_url("gs://my-bucket/path/to/file.pdf")

    def test_azure_url(self):
        assert is_cloud_url("az://my-container/path/to/blob.pdf")

    def test_http_not_cloud(self):
        assert not is_cloud_url("http://example.com/file.pdf")

    def test_https_not_cloud(self):
        assert not is_cloud_url("https://example.com/file.pdf")

    def test_local_path_not_cloud(self):
        assert not is_cloud_url("/tmp/file.pdf")

    def test_empty_not_cloud(self):
        assert not is_cloud_url("")


class TestS3URLParsing:
    def test_basic(self):
        bucket, key = _parse_s3_url("s3://my-bucket/path/to/file.pdf")
        assert bucket == "my-bucket"
        assert key == "path/to/file.pdf"

    def test_nested_path(self):
        bucket, key = _parse_s3_url("s3://bucket/a/b/c/d.txt")
        assert bucket == "bucket"
        assert key == "a/b/c/d.txt"

    def test_invalid_no_key(self):
        with pytest.raises(ValueError, match="Invalid S3 URL"):
            _parse_s3_url("s3://bucket-only")


class TestGCSURLParsing:
    def test_basic(self):
        bucket, key = _parse_gcs_url("gs://my-bucket/file.pdf")
        assert bucket == "my-bucket"
        assert key == "file.pdf"

    def test_invalid_no_key(self):
        with pytest.raises(ValueError, match="Invalid GCS URL"):
            _parse_gcs_url("gs://bucket-only")


class TestAzureURLParsing:
    def test_basic(self):
        container, blob = _parse_azure_url("az://my-container/path/blob.pdf")
        assert container == "my-container"
        assert blob == "path/blob.pdf"

    def test_invalid_no_blob(self):
        with pytest.raises(ValueError, match="Invalid Azure URL"):
            _parse_azure_url("az://container-only")
