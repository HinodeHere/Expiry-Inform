# 🛒 AI-Powered Food & Expiry Tracker

A self-hosted, local web application that uses computer vision (OCR) to automatically scan, parse, and track expiration labels, best-by dates, and product shelf lives from packaging. Designed to handle messy real-world packaging, dot-matrix printer flaws, and split labels.

---

## ✨ Features

* **Multi-Image Scanning:** Upload multiple photos of the same product at once (ideal for packaging where the production date and shelf life/batch are printed on separate sides).
* **Robust AI Date Parsing Engine:**
  * **Direct Expiry:** Parses full dates (`YYYY-MM-DD`) and month/year formats (`MM.YYYY`).
  * **Western "Best By" Dates:** Features fuzzy dot-matrix OCR error-correction (handles common AI hallucinations like `HUG` for `AUG`, `0CT` for `OCT`, etc.).
  * **Chinese Food & Industrial Standards:** Calculates exact expiration dates using production dates and shelf life strings (e.g., `12个月`, `30天`).
  * **Universal Date Sorter:** A fallback safety net that extracts all dates from jumbled OCR text, sorts them chronologically, and smartly assigns production vs. expiration dates.
* **Interactive Inventory Dashboard:**
  * **Table View:** Clean, color-coded list highlighting items that are expired, expiring today, or safe.
  * **Calendar View:** An interactive monthly calendar grid mapping your expiring items directly onto their exact calendar dates.
* **Database & Management:** Backed by SQLite to track inventory, with options to mark items as consumed or overridden manually when necessary.
* **Transparent Debugging:** If the OCR text cannot be parsed, the app displays the raw text read by the AI so you can easily identify formatting or printing issues.

---

## 🛠️ Tech Stack

* **Backend:** Python, FastAPI, OpenCV, RapidOCR (ONNX Runtime)
* **Frontend:** HTML5, CSS3, Vanilla JavaScript (Responsive UI)
* **Database:** SQLite
* **Deployment:** Docker / Docker Compose

---

## 📂 Project Structure


food_tracker/
│
├── main.py              # FastAPI backend & OCR processing logic
├── index.html           # Main scanning & manual input interface
├── inventory.html       # Inventory dashboard & calendar grid view
├── requirements.txt     # Python dependencies
├── Dockerfile           # Container configuration
└── inventory.db         # SQLite database (auto-generated)
🚀 Getting Started & Installation
Prerequisites
Make sure Docker is installed and running on your system.

1. Set up the Project Files
Ensure your project directory contains main.py, index.html, inventory.html, requirements.txt, and your Dockerfile.

2. Build and Run with Docker
Open your terminal inside the project directory and run the following commands:

# Build the Docker image
docker build -t food_tracker_app .

# Run the container (mapping port 8000 and persisting the SQLite database)
docker run -d -p 8000:8000 -v $(pwd):/app --name food_tracker_app food_tracker_app
3. Open the Web App
Open your web browser and navigate to:

Plaintext
http://localhost:8000
💡 How to Use
Click "📸 Snap Photo of Expiry Label" (you can select single or multiple images simultaneously if details are split across different sides of the package).

The local AI will scan the images, extract the dates, and autofill the form fields.

Type a Product Name and click "Save to Database".

Click "📦 View Inventory" at the top right to check your items in either the Table View or Calendar View, and click "✔️ Consume" once an item is used up.
