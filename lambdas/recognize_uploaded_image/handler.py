import os
import json
import uuid
import base64
import boto3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

rekognition = boto3.client("rekognition")
s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

# Safe placeholders for GitHub showcase (configure in AWS via env vars)
BUCKET_NAME = os.environ.get("UPLOAD_BUCKET_NAME", "YOUR_UPLOAD_BUCKET_NAME_HERE")
TABLE_NAME = os.environ.get("ORDERS_TABLE", "orders")

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


def _resp(status_code: int, payload: dict):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(payload, default=str),
    }


def _parse_json_body(event):
    body = event.get("body")
    if body is None:
        return {}

    if event.get("isBase64Encoded") is True and isinstance(body, str):
        body = base64.b64decode(body).decode("utf-8")

    if isinstance(body, str):
        body = body.strip()
        if not body:
            return {}
        return json.loads(body)

    if isinstance(body, dict):
        return body

    return {}


def _decode_base64_image(image_base64: str):
    try:
        return base64.b64decode(image_base64)
    except Exception:
        return None


def _validate_description(user_description: str, detected_label: str, confidence: Decimal):
    if not user_description or user_description.strip() == "":
        return {
            "status": "no_description",
            "message": f"No description provided. System detected: {detected_label} ({float(confidence)}% confidence)"
        }

    user_desc_lower = user_description.lower().strip()
    detected_lower = detected_label.lower().strip()

    if (
        user_desc_lower == detected_lower
        or detected_lower in user_desc_lower
        or user_desc_lower in detected_lower
    ):
        return {
            "status": "match",
            "message": f"Description matches detected object: {detected_label} ({float(confidence)}% confidence)"
        }

    return {
        "status": "mismatch",
        "message": f'WARNING: description "{user_description}" does not match detected "{detected_label}" ({float(confidence)}% confidence)'
    }


def lambda_handler(event, context):
    # Preflight
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}

    try:
        body = _parse_json_body(event)

        confirm = bool(body.get("confirm", False))
        image_base64 = body.get("image")
        user_description = str(body.get("description", "")).strip()

        if not image_base64:
            return _resp(400, {"status": "error", "message": "No image provided"})

        image_bytes = _decode_base64_image(image_base64)
        if not image_bytes:
            return _resp(400, {"status": "error", "message": "Invalid base64 image format"})

        # Rekognition detect labels
        rek_resp = rekognition.detect_labels(
            Image={"Bytes": image_bytes},
            MaxLabels=10,
            MinConfidence=50,
        )

        labels = rek_resp.get("Labels", [])
        if not labels:
            return _resp(400, {"status": "error", "message": "Could not identify any objects in the image"})

        detected_labels = []
        for label in labels:
            name = label.get("Name", "Unknown")
            conf = label.get("Confidence", 0)

            try:
                conf_dec = Decimal(str(round(float(conf), 2)))
            except (InvalidOperation, ValueError, TypeError):
                conf_dec = Decimal("0")

            detected_labels.append({"name": name, "confidence": conf_dec})

        top_label = detected_labels[0]["name"]
        top_confidence = detected_labels[0]["confidence"]

        validation_result = _validate_description(user_description, top_label, top_confidence)

        # Validation-only mode (no writes)
        if not confirm:
            return _resp(200, {
                "status": "validation_only",
                "recognition": {
                    "topDetectedObject": top_label,
                    "confidence": float(top_confidence),
                    "allDetectedLabels": [
                        {"name": l["name"], "confidence": float(l["confidence"])}
                        for l in detected_labels
                    ],
                },
                "validation": validation_result,
            })

        # Safety: if not configured, don't write
        if BUCKET_NAME == "YOUR_UPLOAD_BUCKET_NAME_HERE":
            return _resp(500, {"status": "error", "message": "UPLOAD_BUCKET_NAME is not configured"})

        order_id = str(uuid.uuid4())
        image_key = f"images/{order_id}.jpg"

        # Upload image to S3
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=image_key,
            Body=image_bytes,
            ContentType="image/jpeg",
        )

        # Create order in DynamoDB
        table = dynamodb.Table(TABLE_NAME)

        now = datetime.now(timezone.utc).isoformat()
        final_description = user_description if user_description else f"{top_label} (Auto-detected)"

        order_data = {
            "entityType": "ORDER",
            "orderId": order_id,
            "description": final_description,
            "price": Decimal("100"),
            "creationDate": now,
            "lastModifiedDate": now,
            "imageKey": image_key,
            "detectedLabels": detected_labels,
            "topDetectedLabel": top_label,
            "recognitionConfidence": top_confidence,
            "validationStatus": validation_result["status"],
            "validationMessage": validation_result["message"],
        }

        table.put_item(Item=order_data)

        return _resp(201, {
            "status": "success",
            "message": "Order created from uploaded image",
            "orderId": order_id,
            "description": final_description,
            "price": 100,
            "imageKey": image_key,
            "validation": validation_result,
        })

    except json.JSONDecodeError:
        return _resp(400, {"status": "error", "message": "Invalid JSON body"})
    except Exception as e:
        print("recognize_uploaded_image error:", str(e))
        return _resp(500, {"status": "error", "message": "Internal server error"})
