# 🍏 FreshTrack

**FreshTrack** is a self-hosted, lightweight, OCR-powered smart inventory and food expiration tracker. Designed for mobile and desktop, it allows you to snap a photo of a food label, automatically extract the production and expiry dates using edge AI, and track your consumption habits over time.

## ✨ Features

* **📸 AI OCR Scanning:** Uses RapidOCR to read physical product labels and automatically calculate expiration dates based on production dates and shelf life.
* **📱 Responsive UI:** Features a mobile-first design with a sliding hamburger menu, iOS-style quantity steppers, and full Dark Mode support.
* **📦 Smart Inventory Dashboard:** Track what is expiring soon with color-coded warnings. Features one-tap "Consume 1" and "Consume All" tracking.
* **📊 Analytics Engine:** Visualizes your consumption vs. waste habits with a Chart.js doughnut chart and a detailed data log.
* **⚠️ Failed Scans Debugger:** Automatically saves the image and raw OCR text of failed scans so you can review why the AI missed a date.
* **📧 Automated Email Alerts:** Runs a background scheduler (APScheduler) to email you every morning at 8:00 AM with a list of items expiring within the next 7 days.
* **🔒 PIN Protected:** Secures all write/delete actions (adding, consuming, deleting) behind a custom numeric App PIN.

---

## 🛠️ Tech Stack

* **Backend:** Python, FastAPI, SQLite3
* **Frontend:** Vanilla JavaScript, HTML5, CSS3, Chart.js
* **OCR / Vision:** OpenCV, RapidOCR (ONNX Runtime)
* **Infrastructure:** Docker, Docker Compose

---

## 🚀 Installation & Deployment

FreshTrack is designed to be deployed instantly using Docker. 

### 1. Prerequisites
Ensure you have the following installed on your server or local machine:
* [Docker](https://docs.docker.com/get-docker/)
* [Docker Compose](https://docs.docker.com/compose/install/)
* Git

### 2. Clone the Repository
```bash
git clone [https://github.com/yourusername/FreshTrack.git](https://github.com/yourusername/FreshTrack.git)
cd FreshTrack
```

### 3. Configure Environment Variables
FreshTrack requires a few environment variables to handle security and email notifications. Create a `.env` file in the root of your project directory:

```bash
nano .env
```

Paste the following configuration into your `.env` file and update the values with your actual credentials:

```env
# --- SECURITY ---
# The PIN required to add, consume, or delete items in the web app
APP_PIN=123456

# --- EMAIL NOTIFICATIONS ---
# SMTP server settings (e.g., smtp.gmail.com or smtp.qq.com)
SMTP_SERVER=smtp.gmail.com
# Port (Use 587 for TLS, or 465 for SSL)
SMTP_PORT=587

# The email address sending the alerts and its App Password
SENDER_EMAIL=your_email@gmail.com
SENDER_PASSWORD=your_app_password

# The email address(es) receiving the alerts. 
# You can separate multiple emails with a comma (e.g., email1@gmail.com, email2@gmail.com)
RECEIVER_EMAIL=your_email@gmail.com
```

> **Note for Gmail users:** You cannot use your standard Google password for `SENDER_PASSWORD`. You must generate a 16-character [App Password](https://myaccount.google.com/apppasswords) from your Google Account security settings.

### 4. Build and Run the Container
Once your `.env` file is saved, use Docker Compose to build the image and start the application in detached mode:

```bash
docker-compose up -d --build
```

### 5. Access the Application
FreshTrack will now be running on port `8000`. 
* Open your browser and navigate to `http://localhost:8000` (or your server's IP/domain).
* To test the email functionality immediately without waiting for 8:00 AM, you can temporarily change the cron trigger in `main.py` or create a test route.

---

## 📂 Data Storage

All persistent data is stored safely outside the container in a mapped `./data` volume. This includes:
* `inventory.db`: Your SQLite database containing inventory, logs, and analytics.
* `failed_images/`: A directory containing the `.jpg` and `.txt` files of scans you flagged for review.

If you ever need to backup your inventory or move servers, simply copy the `./data` folder!

---

## 💡 Usage Tips

* **Scanning Labels:** Make sure the area is well-lit. The OCR is programmed to look for standard date formats (`YYYY-MM-DD`, `DD-MM-YYYY`) and keywords like `EXP`, `PROD`, `BEST BEFORE`, and `EX.`.
* **Fixing Bad Scans:** If the OCR grabs the wrong text (like a weight measurement instead of a name), hit the **"Output Incorrect? Save Image"** button. Navigate to the **Failed Scans** dashboard to see the exact raw text the AI read so you can update the Python regex rules if necessary.
* **First Time Setup:** When you click "Save to Database" or "Consume" for the first time on a new device, the app will prompt you for your `APP_PIN`. It will save this PIN in your browser's Local Storage so you don't have to type it every time.