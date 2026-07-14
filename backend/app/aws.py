"""Amazon Rekognition helpers (CompareFaces, DetectFaces, DetectText only).

All functions are synchronous (boto3) — call via threadpool from async code,
or directly inside Celery tasks. 8s read timeout, single attempt: an AWS infra
failure must never block or falsely flag a worker.
"""
import logging

from botocore.config import Config

from app.config import settings

logger = logging.getLogger("hogo.aws")

_REK_CONFIG = Config(connect_timeout=3, read_timeout=8, retries={"max_attempts": 1})


class RekognitionUnavailable(Exception):
    """Infra-level failure (timeout, throttle, credentials) — never the worker's fault."""


def rekognition_client():
    import boto3

    return boto3.client(
        "rekognition",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        config=_REK_CONFIG,
    )


def compare_faces(source_bytes: bytes, target_bytes: bytes) -> float:
    """Return best similarity score 0-100 between reference (source) and punch selfie (target).

    Returns 0.0 when Rekognition finds no matching face (or no face at all in
    either image — that is a real mismatch, not an infra failure).
    Raises RekognitionUnavailable on infra errors.
    """
    from botocore.exceptions import BotoCoreError, ClientError

    client = rekognition_client()
    try:
        resp = client.compare_faces(
            SourceImage={"Bytes": source_bytes},
            TargetImage={"Bytes": target_bytes},
            SimilarityThreshold=0,
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "InvalidParameterException":
            # no detectable face in one of the images → genuine mismatch
            return 0.0
        logger.warning("Rekognition CompareFaces failed: %s", code)
        raise RekognitionUnavailable(code) from e
    except BotoCoreError as e:
        logger.warning("Rekognition CompareFaces infra error: %s", e)
        raise RekognitionUnavailable(str(e)) from e
    matches = resp.get("FaceMatches", [])
    if not matches:
        return 0.0
    return max(m.get("Similarity", 0.0) for m in matches)


def detect_faces_count(image_bytes: bytes) -> int:
    """Number of faces detected in the image. Raises RekognitionUnavailable on infra errors."""
    from botocore.exceptions import BotoCoreError, ClientError

    client = rekognition_client()
    try:
        resp = client.detect_faces(Image={"Bytes": image_bytes}, Attributes=["DEFAULT"])
    except (ClientError, BotoCoreError) as e:
        logger.warning("Rekognition DetectFaces failed: %s", e)
        raise RekognitionUnavailable(str(e)) from e
    return len(resp.get("FaceDetections", resp.get("FaceDetails", [])))


def detect_text(image_bytes: bytes) -> list[dict]:
    """LINE-level text detections: [{text, confidence(0-100)}].
    Raises RekognitionUnavailable on infra errors."""
    from botocore.exceptions import BotoCoreError, ClientError

    client = rekognition_client()
    try:
        resp = client.detect_text(Image={"Bytes": image_bytes})
    except (ClientError, BotoCoreError) as e:
        logger.warning("Rekognition DetectText failed: %s", e)
        raise RekognitionUnavailable(str(e)) from e
    return [
        {"text": t.get("DetectedText", ""), "confidence": t.get("Confidence", 0.0)}
        for t in resp.get("TextDetections", [])
        if t.get("Type") == "LINE"
    ]
