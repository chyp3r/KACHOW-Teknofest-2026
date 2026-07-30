import pytest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError

from app.infrastructure.storage.s3 import S3Storage

@pytest.fixture
def mock_boto3():
    with patch("app.infrastructure.storage.s3.boto3") as mock_boto3:
        yield mock_boto3

@pytest.mark.asyncio
async def test_s3_init_success(mock_boto3):
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client
    
    storage = S3Storage("test-bucket", "http://minio", "access", "secret")
    assert storage.bucket_name == "test-bucket"
    mock_client.create_bucket.assert_called_once_with(Bucket="test-bucket")

@pytest.mark.asyncio
async def test_s3_init_exception(mock_boto3):
    mock_client = MagicMock()
    mock_client.create_bucket.side_effect = ClientError(
        {"Error": {"Code": "BucketAlreadyExists"}}, "CreateBucket"
    )
    mock_boto3.client.return_value = mock_client
    
    storage = S3Storage("test-bucket", "http://minio", "access", "secret")
    assert storage.bucket_name == "test-bucket"

@pytest.mark.asyncio
async def test_s3_put_file(mock_boto3):
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client
    storage = S3Storage("test-bucket", "http://minio", "access", "secret")
    
    uri = await storage.put_file("f.txt", b"data")
    assert uri == "s3://test-bucket/f.txt"
    mock_client.put_object.assert_called_once_with(
        Bucket="test-bucket", Key="f.txt", Body=b"data"
    )

@pytest.mark.asyncio
async def test_s3_get_file_success(mock_boto3):
    mock_client = MagicMock()
    mock_body = MagicMock()
    mock_body.read.return_value = b"data"
    mock_client.get_object.return_value = {"Body": mock_body}
    mock_boto3.client.return_value = mock_client
    
    storage = S3Storage("test-bucket", "http://minio", "access", "secret")
    data = await storage.get_file("f.txt")
    assert data == b"data"
    mock_client.get_object.assert_called_once_with(Bucket="test-bucket", Key="f.txt")

@pytest.mark.asyncio
async def test_s3_get_file_not_found(mock_boto3):
    mock_client = MagicMock()
    mock_client.get_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey"}}, "GetObject"
    )
    mock_boto3.client.return_value = mock_client
    
    storage = S3Storage("test-bucket", "http://minio", "access", "secret")
    with pytest.raises(FileNotFoundError):
        await storage.get_file("f.txt")

@pytest.mark.asyncio
async def test_s3_get_file_other_exception(mock_boto3):
    mock_client = MagicMock()
    mock_client.get_object.side_effect = ClientError(
        {"Error": {"Code": "InternalError"}}, "GetObject"
    )
    mock_boto3.client.return_value = mock_client
    
    storage = S3Storage("test-bucket", "http://minio", "access", "secret")
    with pytest.raises(ClientError):
        await storage.get_file("f.txt")

@pytest.mark.asyncio
async def test_s3_delete_file_success(mock_boto3):
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client
    
    storage = S3Storage("test-bucket", "http://minio", "access", "secret")
    assert await storage.delete_file("f.txt") is True
    mock_client.delete_object.assert_called_once_with(Bucket="test-bucket", Key="f.txt")

@pytest.mark.asyncio
async def test_s3_delete_file_exception(mock_boto3):
    mock_client = MagicMock()
    mock_client.delete_object.side_effect = Exception("error")
    mock_boto3.client.return_value = mock_client
    
    storage = S3Storage("test-bucket", "http://minio", "access", "secret")
    assert await storage.delete_file("f.txt") is False
