import os
import json
import boto3
from decimal import Decimal

# ---------- config ----------
TABLE_NAME = os.environ.get("ORDERS_TABLE", "orders")

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
}

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

# ---------- helpers ----------
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            if obj % 1 == 0:
                return int(obj)
            return float(obj)
        return super().default(obj)

def response(status_code: int, payload: dict):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(payload, cls=DecimalEncoder),
    }

# ---------- lambda ----------
def lambda_handler(event, context):
    # Preflight
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}

    try:
        path_params = event.get("pathParameters") or {}
        order_id = path_params.get("orderId")

        if not order_id:
            return response(400, {"status": "error", "message": "Missing orderId"})

        resp = table.get_item(
            Key={
                "orderId": order_id,
                "entityType": "ORDER"
            }
        )

        item = resp.get("Item")
        if not item:
            return response(404, {"status": "error", "message": "Order not found"})

        clean_item = {
            "orderId": item.get("orderId"),
            "creationDate": item.get("creationDate"),
            "lastModifiedDate": item.get("lastModifiedDate"),
            "price": item.get("price"),
            "description": item.get("description"),
        }

        return response(200, {"status": "success", "order": clean_item})

    except Exception as e:
        print("ERROR:", str(e))
        return response(500, {"status": "error", "message": "Failed to fetch order"})
