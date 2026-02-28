import os
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import boto3

# ---------- config ----------
TABLE_NAME = os.environ.get("ORDERS_TABLE", "orders")

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

# ---------- helpers ----------
def response(status_code: int, payload: dict):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(payload),
    }

def parse_json_body(event):
    body = event.get("body")

    if body is None:
        return {}

    # If API Gateway sent base64 body
    if event.get("isBase64Encoded") is True and isinstance(body, str):
        import base64
        body = base64.b64decode(body).decode("utf-8")

    if isinstance(body, str):
        body = body.strip()
        if not body:
            return {}
        return json.loads(body)

    if isinstance(body, dict):
        return body

    return {}

# ---------- lambda ----------
def lambda_handler(event, context):
    # Preflight
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}

    try:
        body = parse_json_body(event)

        description = str(body.get("description", "")).strip()
        price_raw = body.get("price", None)

        if not description:
            return response(400, {"status": "error", "message": "description is required"})

        if price_raw is None:
            return response(400, {"status": "error", "message": "price is required"})

        try:
            price = Decimal(str(price_raw))
        except (InvalidOperation, ValueError, TypeError):
            return response(400, {"status": "error", "message": "price must be a number"})

        if price <= 0:
            return response(400, {"status": "error", "message": "price must be > 0"})

        order_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        item = {
            "orderId": order_id,
            "entityType": "ORDER",
            "creationDate": now,
            "lastModifiedDate": now,
            "price": price,
            "description": description,
        }

        table.put_item(Item=item)

        return response(
            201,
            {"status": "success", "message": "Order created successfully", "orderId": order_id},
        )

    except json.JSONDecodeError:
        return response(400, {"status": "error", "message": "Invalid JSON body"})
    except Exception as e:
        print("ERROR:", str(e))
        return response(500, {"status": "error", "message": "Internal server error"})
