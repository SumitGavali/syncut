# src/synccut/workers/storage.py
import boto3
import os

def upload_file_to_s3(file_path, bucket_name, object_name=None):
    """Upload a file to an S3-compatible bucket."""
    if object_name is None:
        object_name = os.path.basename(file_path)

    # Connects boto3 directly to Upstash using your .env values
    s3_client = boto3.client(
        's3',
        endpoint_url=os.environ.get('S3_ENDPOINT_URL'),
        aws_access_key_id=os.environ.get('S3_ACCESS_KEY_ID'),
        aws_secret_access_key=os.environ.get('S3_SECRET_ACCESS_KEY')
    )
    
    # Uploads the file into your "synccut" bucket
    s3_client.upload_file(file_path, bucket_name, object_name)
    
    # Correct URL Generation for Upstash:
    # This matches the "Public URL" domain shown in your dashboard screenshot
    public_base_url = "https://b5b0f54136fa.blob.upstash.io"
    return f"{public_base_url}/{object_name}"
