import io
import wave
import dashscope
import os
import uuid
import boto3
from config import settings

def init_dashscope_api_key():
    """
    Set your DashScope API-key.
    """
    api_key = settings.get('DASHSCOPE_API_KEY') or settings.get('dashscope_api_key')
    if api_key:
        dashscope.api_key = api_key
    else:
        raise RuntimeError("DASHSCOPE_API_KEY is not set in settings or environment variables")

def pcm_to_wav(pcm_data, sample_rate=24000, channels=1, sample_width=2):
    """
    Encapsulate PCM data into WAV format.
    """
    wav_buf = io.BytesIO()
    with wave.open(wav_buf, 'wb') as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    return wav_buf.getvalue()

def save_audio_to_s3(wav_audio_data):
    """
    Save WAV audio data to S3 and return the URL.
    """
    bucket = settings.get("s3.bucket")
    access_key = settings.get("s3.accessKeyId")
    secret_key = settings.get("s3.accessKeySecret")
    endpoint = settings.get("s3.endpoint")
    region = settings.get("s3.region")
    public_url_prefix = settings.get("s3.publicUrlPrefix")
    url_type = settings.get("s3.urlType").lower()
    expires_in = settings.get("s3.expiresIn")
    s3_client = boto3.client(
        's3',
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        endpoint_url=endpoint if endpoint else None,
        region_name=region if region else None,
        config=boto3.session.Config(signature_version='s3v4') if url_type == "private" else None
    )

    file_name = f"{uuid.uuid4()}.wav"
    
    upload_args = {
        "Bucket": bucket,
        "Key": file_name,
        "Body": wav_audio_data,
        "ContentType": 'audio/wav'
    }
    
    if url_type == "public":
        # Note: some S3 providers might require ACL='public-read' for public access
        # But we only add it if explicitly needed or keep it simple as before
        pass

    s3_client.put_object(**upload_args)
    
    if url_type == "private":
        return s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket, 'Key': file_name},
            ExpiresIn=expires_in
        )
    
    if public_url_prefix:
        return f"{public_url_prefix.rstrip('/')}/{file_name}"
    else:
        if endpoint:
            # For S3 compatible services, the URL structure might be different
            # Default to path-style if endpoint is provided
            return f"{endpoint.rstrip('/')}/{bucket}/{file_name}"
        return f"https://{bucket}.s3.{region}.amazonaws.com/{file_name}"

def save_audio(wav_audio_data, output_dir=None, base_url=None):
    """
    Save WAV audio data based on configuration and return the URL.
    """
    storage_type = settings.get("storageType", "local").lower()
    if storage_type == "s3":
        return save_audio_to_s3(wav_audio_data)
    else:
        # Default to local storage
        if not output_dir:
            output_dir = settings.get("outputDir", "output")
        
        file_name = f"{uuid.uuid4()}.wav"
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        file_path = os.path.join(output_dir, file_name)
        with open(file_path, "wb") as f:
            f.write(wav_audio_data)
        
        clean_base_url = str(base_url).rstrip('/')
        return f"{clean_base_url}/output/{file_name}"
