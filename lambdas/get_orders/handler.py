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
def response(status_code: int, payload: dict):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(payload, cls=DecimalEncoder),
    }

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

# ---------- lambda ----------
def lambda_handler(event, context):

    # Preflight
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}

    try:
        items = []
        response_data = table.scan()

        items.extend(response_data.get("Items", []))

        # Pagination handling (important for production)
        while "LastEvaluatedKey" in response_data:
            response_data = table.scan(
                ExclusiveStartKey=response_data["LastEvaluatedKey"]
            )
            items.extend(response_data.get("Items", []))

        if not items:
            return response(404, {
                "status": "error",
                "message": "No orders found"
            })

        orders = [
            {
                "orderId": item.get("orderId"),
                "description": item.get("description"),
                "price": item.get("price"),
                "creationDate": item.get("creationDate")
            }
            for item in items
        ]

        return response(200, {
            "status": "success",
            "message": f"Orders fetched: {len(orders)}",
            "orders": orders
        })

    except Exception as e:
        print("ERROR:", str(e))
        return response(500, {
            "status": "error",
            "message": "Failed to fetch orders"
        })
