import os
import json
import re
import boto3

sns = boto3.client("sns")

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


def _list_all_subscriptions(topic_arn: str):
    subs = []
    next_token = None

    while True:
        kwargs = {"TopicArn": topic_arn}
        if next_token:
            kwargs["NextToken"] = next_token

        resp = sns.list_subscriptions_by_topic(**kwargs)
        subs.extend(resp.get("Subscriptions", []))

        next_token = resp.get("NextToken")
        if not next_token:
            break

    return subs


def lambda_handler(event, context):
    # Preflight
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}

    try:
        if SNS_TOPIC_ARN == "YOUR_SNS_TOPIC_ARN_HERE":
            return _resp(500, {"status": "error", "message": "SNS_TOPIC_ARN is not configured"})

        body = _parse_json_body(event)
        email = str(body.get("email", "")).strip()

        if not email:
            return _resp(400, {"status": "error", "message": "Email is required"})

        if not re.match(EMAIL_REGEX, email):
            return _resp(400, {"status": "error", "message": "Invalid email format"})

        subs = _list_all_subscriptions(SNS_TOPIC_ARN)

        for sub in subs:
            if sub.get("Protocol") == "email" and sub.get("Endpoint") == email:
                arn = sub.get("SubscriptionArn")

                if arn == "PendingConfirmation":
                    return _resp(400, {
                        "status": "error",
                        "message": "Email subscription is not confirmed yet",
                    })

                sns.unsubscribe(SubscriptionArn=arn)

                return _resp(200, {
                    "status": "success",
                    "message": "Unsubscribed successfully",
                    "email": email,
                })

        return _resp(404, {"status": "error", "message": "Email not subscribed"})

    except json.JSONDecodeError:
        return _resp(400, {"status": "error", "message": "Invalid JSON body"})
    except Exception as e:
        print("UnsubscribeEmail error:", str(e))
        return _resp(500, {"status": "error", "message": "Internal server error"})
