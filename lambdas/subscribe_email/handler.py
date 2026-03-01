import os
import json
import re
import boto3

sns = boto3.client("sns")

# In real deployment, set this as an environment variable:
# SNS_TOPIC_ARN = arn:aws:sns:...
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "YOUR_SNS_TOPIC_ARN_HERE")

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}

EMAIL_REGEX = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def _resp(status_code: int, payload: dict):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(payload),
    }


def _parse_json_body(event):
    body = event.get("body")
    if body is None:
        return {}

    if isinstance(body, str):
        body = body.strip()
        if not body:
            return {}
        return json.loads(body)

    if isinstance(body, dict):
        return body

    return {}


def lambda_handler(event, context):
    # Preflight
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}

    try:
        body = _parse_json_body(event)
        email = str(body.get("email", "")).strip()

        if not email:
            return _resp(400, {"status": "error", "message": "Email is required"})

        if not re.match(EMAIL_REGEX, email):
            return _resp(400, {"status": "error", "message": "Invalid email format"})

        if SNS_TOPIC_ARN == "YOUR_SNS_TOPIC_ARN_HERE":
            # Safe fallback for GitHub showcase
            return _resp(500, {"status": "error", "message": "SNS_TOPIC_ARN is not configured"})

        sns.subscribe(
            TopicArn=SNS_TOPIC_ARN,
            Protocol="email",
            Endpoint=email,
        )

        return _resp(200, {
            "status": "success",
            "message": "Confirmation email sent. Please check your inbox.",
            "email": email,
        })

    except json.JSONDecodeError:
        return _resp(400, {"status": "error", "message": "Invalid JSON body"})
    except Exception as e:
        print("SubscribeEmail error:", str(e))
        return _resp(500, {"status": "error", "message": "Internal server error"})
