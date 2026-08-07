import os
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

# Environment variables injected via docker-compose.yml
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.qq.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "your_email@qq.com")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD", "your_auth_code")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL", "your_email@qq.com")

DB_PATH = "/app/data/inventory.db"


def check_expirations_and_email():
    # Validate credentials before processing
    if SENDER_EMAIL == "your_email@qq.com" or SENDER_PASSWORD == "your_auth_code":
        print("[Warning] Email notifier skipping: SMTP credentials are not configured.")
        return

    if not os.path.exists(DB_PATH):
        print("[Warning] Database file does not exist yet. Skipping check.")
        return

    today = datetime.now().date()
    warning_limit = today + timedelta(days=7)

    # Query all unconsumed items expiring within the next 7 days or already expired
    query = """
        SELECT product_name, expiration_date 
        FROM inventory 
        WHERE is_consumed = 0 AND expiration_date <= ?
        ORDER BY expiration_date ASC
    """

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(query, (warning_limit.strftime('%Y-%m-%d'),))
        expiring_items = cursor.fetchall()

    if not expiring_items:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] No items expiring soon. No email sent.")
        return

    # Build HTML Email Table
    html_content = "<h2>🛒 Food Expiration Tracker Alert</h2>"
    html_content += "<p>The following items in your inventory require attention:</p>"
    html_content += "<table border='1' cellpadding='8' cellspacing='0' style='border-collapse: collapse; font-family: sans-serif;'>"
    html_content += "<tr style='background-color: #f2f2f2;'><th>Product Name</th><th>Expiration Date</th><th>Status</th></tr>"

    for name, exp_date_str in expiring_items:
        exp_date = datetime.strptime(exp_date_str, '%Y-%m-%d').date()
        days_left = (exp_date - today).days

        if days_left < 0:
            status = f"<span style='color: red; font-weight: bold;'>⚠️ EXPIRED ({abs(days_left)} days ago)</span>"
        elif days_left == 0:
            status = "<span style='color: red; font-weight: bold;'>⚠️ Expires Today!</span>"
        elif days_left <= 3:
            status = f"<span style='color: orange; font-weight: bold;'>🕒 Critical: {days_left} day(s) left</span>"
        else:
            status = f"<span style='color: #007bff;'>📅 Warning: {days_left} day(s) left</span>"

        html_content += f"<tr><td><b>{name}</b></td><td>{exp_date_str}</td><td>{status}</td></tr>"

    html_content += "</table><br><p>Log in to your local web UI to mark items as consumed when done!</p>"

    # Compose Email Message
    msg = MIMEMultipart()
    msg['Subject'] = f"⚠️ Food Inventory Alert: {len(expiring_items)} item(s) pending"
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))

    # Send Email via Adaptive SMTP
    try:
        if SMTP_PORT == 465:
            # SSL Connection
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=15)
        else:
            # TLS/STARTTLS Connection (e.g., Port 587 or 25)
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()

        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        server.quit()
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Expiration email sent for {len(expiring_items)} item(s).")
    except Exception as e:
        print(f"[Error] Failed to send email: {e}")


if __name__ == "__main__":
    check_expirations_and_email()