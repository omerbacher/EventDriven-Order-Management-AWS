import os
import json
import boto3
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from botocore.exceptions import ClientError

# ---------- config ----------
TABLE_NAME = os.environ.get("ORDERS_TABLE", "orders")

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "PUT,PATCH,OPTIONS",
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

def parse_json_body(event):
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

        body = parse_json_body(event)
        if not body:
            return response(400, {"status": "error", "message": "Missing request body"})

        update_parts = []
        expr_attr_names = {}
        expr_attr_values = {}

        # price
        if "price" in body:
            try:
                price_val = Decimal(str(body["price"]))
            except (InvalidOperation, ValueError, TypeError):
                return response(400, {"status": "error", "message": "price must be a number"})
            if price_val <= 0:
                return response(400, {"status": "error", "message": "price must be > 0"})

            expr_attr_names["#price"] = "price"
            expr_attr_values[":price"] = price_val
            update_parts.append("#price = :price")

        # description
        if "description" in body:
            desc_val = str(body["description"]).strip()
            if not desc_val:
                return response(400, {"status": "error", "message": "description cannot be empty"})

            expr_attr_names["#desc"] = "description"
            expr_attr_values[":desc"] = desc_val
            update_parts.append("#desc = :desc")

        if not update_parts:
            return response(400, {
                "status": "error",
                "message": "Nothing to update. Send price and/or description."
            })

        # always update lastModifiedDate
        expr_attr_names["#lmd"] = "lastModifiedDate"
        expr_attr_values[":lmd"] = datetime.now(timezone.utc).isoformat()
        update_parts.append("#lmd = :lmd")

        update_expression = "SET " + ", ".join(update_parts)

        result = table.update_item(
            Key={"orderId": order_id, "entityType": "ORDER"},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expr_attr_names,
            ExpressionAttributeValues=expr_attr_values,
            ConditionExpression="attribute_exists(orderId)",
            ReturnValues="ALL_NEW",
        )

        return response(200, {"status": "success", "order": result.get("Attributes", {})})

    except json.JSONDecodeError:
        return response(400, {"status": "error", "message": "Invalid JSON body"})
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code == "ConditionalCheckFailedException":
            return response(404, {"status": "error", "message": "Order not found", "orderId": order_id})
        print("ClientError:", str(e))
        return response(500, {"status": "error", "message": "Failed to update order"})
    except Exception as e:
        print("ERROR:", str(e))
        return response(500, {"status": "error", "message": "Failed to update order"})
