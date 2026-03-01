import json
import os
import boto3

s3 = boto3.client("s3")

# Use environment variable in real deployment
BUCKET_NAME = os.environ.get("BACKUP_BUCKET_NAME", "your-backup-bucket")
DELETED_PREFIX = "deleted_orders/"


def lambda_handler(event, context):
    try:
        records = event.get("Records", [])
        if not records:
            return _response(400, {"error": "No SNS records found"})

        record = records[0]
        message_str = record.get("Sns", {}).get("Message")

        if not message_str:
            return _response(400, {"error": "Missing SNS message payload"})

        message = json.loads(message_str)

        order_id = message.get("orderId", "unknown")

        lines = [
            f"Event Type: {message.get('eventType')}",
            f"Order ID: {order_id}",
            f"Price: {message.get('price')}",
            f"Description: {message.get('description')}",
            f"Deleted At: {message.get('deletedAt')}",
        ]

        content = "\n".join(lines)
        key = f"{DELETED_PREFIX}{order_id}.txt"

        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="text/plain"
        )

        return _response(200, {
            "status": "success",
            "message": "Backup file created",
            "file": key
        })

    except Exception as e:
        print("Archive Lambda error:", str(e))
        return _response(500, {"error": "Failed to archive deleted order"})


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "body": json.dumps(body)
    }
