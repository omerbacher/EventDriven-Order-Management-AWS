import os
import json
import boto3
from datetime import datetime, timezone
from decimal import Decimal
from botocore.exceptions import ClientError

# ---------- config ----------
TABLE_NAME = os.environ.get("ORDERS_TABLE", "orders")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN")

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "DELETE,OPTIONS",
}

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

sns = boto3.client("sns")

# ---------- helpers ----------
def response(status_code: int, payload: dict):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(payload),
    }

def to_float_if_decimal(x):
    if isinstance(x, Decimal):
        return float(x)
    return x

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

        # get order (for message payload)
        resp = table.get_item(Key={"orderId": order_id, "entityType": "ORDER"})
        order = resp.get("Item")
        if not order:
            return response(404, {"status": "error", "message": "Order not found", "orderId": order_id})

        # delete (guard with condition)
        table.delete_item(
            Key={"orderId": order_id, "entityType": "ORDER"},
            ConditionExpression="attribute_exists(orderId)",
        )

        message = {
            "eventType": "ORDER_DELETED",
            "orderId": order.get("orderId"),
            "description": order.get("description", ""),
            "price": to_float_if_decimal(order.get("price", 0)),
            "deletedAt": datetime.now(timezone.utc).isoformat(),
        }

        # publish only if configured (safe for GitHub/demo)
        if SNS_TOPIC_ARN:
            sns.publish(TopicArn=SNS_TOPIC_ARN, Message=json.dumps(message))

        return response(200, {
            "status": "success",
            "message": "Order deleted" + (" and notification sent" if SNS_TOPIC_ARN else ""),
            "orderId": order_id
        })

    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code == "ConditionalCheckFailedException":
            return response(404, {"status": "error", "message": "Order not found", "orderId": order_id})

        print("ClientError:", str(e))
        return response(500, {"status": "error", "message": "Failed to delete order"})
    except Exception as e:
        print("ERROR:", str(e))
        return response(500, {"status": "error", "message": "Failed to delete order"})
