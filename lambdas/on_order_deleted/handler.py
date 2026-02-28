import json
import boto3
from datetime import datetime

s3 = boto3.client("s3")

BUCKET_NAME = "deleted-orders-backup"

def lambda_handler(event, context):
    """
    Triggered asynchronously when an order is deleted.
    Saves deleted order details as a TXT file in S3.
    """

    try:
        # EventBridge payload
        order = event.get("detail")

        if not order or "orderId" not in order:
            return {
                "statusCode": 400,
                "body": "Invalid event payload"
            }

        order_id = order["orderId"]
        timestamp = datetime.utcnow().isoformat()

        content = (
            f"Order ID: {order.get('orderId')}\n"
            f"Price: {order.get('price')}\n"
            f"Description: {order.get('description')}\n"
            f"Creation Date: {order.get('creationDate')}\n"
            f"Last Modified Date: {order.get('lastModifiedDate')}\n"
            f"Deleted At: {timestamp}\n"
        )

        file_key = f"deleted_orders/{order_id}.txt"

        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=file_key,
            Body=content.encode("utf-8"),
            ContentType="text/plain"
        )

        return {
            "statusCode": 200,
            "body": f"Backup created for order {order_id}"
        }

    except Exception as e:
        print("ERROR:", str(e))
        return {
            "statusCode": 500,
            "body": "Failed to archive deleted order"
        }
