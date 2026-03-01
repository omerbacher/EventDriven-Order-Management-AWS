import json
import boto3
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.lib.units import cm

s3 = boto3.client("s3")

# Prefer env vars in real deployment. For now, keep as-is for your project.
BUCKET_NAME = "deleted-orders-backup"
DELETED_ORDERS_PREFIX = "deleted_orders/"   # <-- matches on_order_deleted
REPORT_PREFIX = "reports/"

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,OPTIONS"
}


def _resp(status_code: int, body: dict):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body)
    }


def _safe_decimal(value) -> Decimal:
    """
    Convert various string/number price formats to Decimal safely.
    Examples: "12", "12.5", "$1,234.00"
    """
    if value is None:
        return Decimal("0")

    s = str(value).strip()
    s = s.replace("$", "").replace(",", "")
    if s == "":
        return Decimal("0")

    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def scan_deleted_orders():
    """
    Scans S3 for deleted order TXT backups under DELETED_ORDERS_PREFIX.
    Each file is expected to contain:
      Order ID: ...
      Price: ...
      Description: ...
      Deleted At: ...
    """
    orders = []
    continuation_token = None

    while True:
        kwargs = {
            "Bucket": BUCKET_NAME,
            "Prefix": DELETED_ORDERS_PREFIX
        }
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token

        resp = s3.list_objects_v2(**kwargs)
        contents = resp.get("Contents", [])
        if not contents:
            break

        for obj in contents:
            key = obj.get("Key", "")
            if not key.endswith(".txt"):
                continue
            if key.endswith("/"):
                continue

            try:
                body = s3.get_object(Bucket=BUCKET_NAME, Key=key)["Body"].read().decode("utf-8", errors="replace")
            except Exception as e:
                print(f"Failed reading {key}: {e}")
                continue

            data = {}
            for line in body.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    data[k.strip()] = v.strip()

            orders.append({
                "order_id": data.get("Order ID", "N/A"),
                "price": _safe_decimal(data.get("Price", "0")),
                "description": data.get("Description", ""),
                "deleted_at": data.get("Deleted At", "")
            })

        if resp.get("IsTruncated"):
            continuation_token = resp.get("NextContinuationToken")
        else:
            break

    return orders


def lambda_handler(event, context):
    # ---------- CORS preflight ----------
    method = (event.get("requestContext", {}) or {}).get("http", {}).get("method")
    if method == "OPTIONS":
        return _resp(200, {"ok": True})

    try:
        orders = scan_deleted_orders()

        if not orders:
            return _resp(404, {
                "error": "No deleted orders found",
                "message": "No TXT backups were found in S3 under deleted_orders/."
            })

        total_orders = len(orders)
        total_revenue = sum((o["price"] for o in orders), Decimal("0"))

        filename = f"/tmp/deleted_orders_{uuid.uuid4()}.pdf"

        doc = SimpleDocTemplate(
            filename,
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm
        )

        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(
            name="TitleStyle",
            fontSize=20,
            textColor=colors.HexColor("#232F3E"),
            spaceAfter=16
        ))
        styles.add(ParagraphStyle(
            name="SectionTitle",
            fontSize=13,
            textColor=colors.HexColor("#FF9900"),
            spaceBefore=20,
            spaceAfter=8
        ))
        styles.add(ParagraphStyle(
            name="TableCell",
            fontSize=8,
            leading=10,
            wordWrap="CJK"
        ))

        elements = []

        # ---------- header ----------
        elements.append(Paragraph("Deleted Orders Executive Report", styles["TitleStyle"]))
        elements.append(Paragraph(
            f"Generated automatically on {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            styles["Normal"]
        ))

        # ---------- key metrics ----------
        elements.append(Spacer(1, 12))
        elements.append(Paragraph("Key Metrics", styles["SectionTitle"]))

        metrics_table = Table(
            [
                ["Total Deleted Orders", "Total Revenue Lost ($)"],
                [str(total_orders), f"${float(total_revenue):,.2f}"]
            ],
            colWidths=[8 * cm, 8 * cm]
        )
        metrics_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#232F3E")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(metrics_table)

        # ---------- bar chart (top 15 by price) ----------
        elements.append(Spacer(1, 20))
        elements.append(Paragraph("Revenue Impact per Order (Top 15)", styles["SectionTitle"]))

        try:
            # Sort by price descending and take top 15 to keep it readable
            top_orders = sorted(orders, key=lambda x: x["price"], reverse=True)[:15]
            if top_orders:
                chart = VerticalBarChart()
                chart.x = 35
                chart.y = 35
                chart.height = 200
                chart.width = 430

                chart.data = [[float(o["price"]) for o in top_orders]]
                chart.categoryAxis.categoryNames = [str(o["order_id"])[:6] for o in top_orders]
                chart.valueAxis.valueMin = 0
                chart.bars[0].fillColor = colors.HexColor("#FF9900")

                drawing = Drawing(500, 260)
                drawing.add(chart)
                elements.append(drawing)
        except Exception as e:
            print("Chart generation skipped:", e)

        # ---------- details table ----------
        elements.append(Spacer(1, 20))
        elements.append(Paragraph("Deleted Orders Details", styles["SectionTitle"]))

        table_data = [["Order ID", "Price ($)", "Description", "Deleted At"]]
        for o in orders:
            table_data.append([
                Paragraph(str(o["order_id"]), styles["TableCell"]),
                Paragraph(f"${float(o['price']):.2f}", styles["TableCell"]),
                Paragraph(str(o["description"]), styles["TableCell"]),
                Paragraph(str(o["deleted_at"]), styles["TableCell"]),
            ])

        details_table = Table(table_data, colWidths=[6 * cm, 3 * cm, 5 * cm, 4 * cm])
        details_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FF9900")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(details_table)

        elements.append(Spacer(1, 20))
        elements.append(Paragraph(
            "Generated by AWS Serverless Architecture (API Gateway, Lambda, DynamoDB, SNS, S3)",
            styles["Normal"]
        ))

        doc.build(elements)

        # ---------- upload + presigned url ----------
        key = f"{REPORT_PREFIX}deleted_orders_{uuid.uuid4()}.pdf"
        s3.upload_file(
            filename,
            BUCKET_NAME,
            key,
            ExtraArgs={"ContentType": "application/pdf"}
        )

        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET_NAME, "Key": key},
            ExpiresIn=3600
        )

        return _resp(200, {"pdf_url": url})

    except Exception as e:
        print("Lambda error:", e)
        return _resp(500, {"error": "PDF generation failed"})
