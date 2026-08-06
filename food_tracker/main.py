import os
import re
import sqlite3
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from rapidocr_onnxruntime import RapidOCR

app = FastAPI(title="Local Food Tracker API")

# Initialize the CPU-optimized ONNX model
# This runs locally in RAM, requiring no internet or paid APIs
ocr = RapidOCR() 

DB_PATH = "/app/data/inventory.db"

def init_db():
    """Create the SQLite database and table if they don't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT DEFAULT 'Unknown Item',
            production_date DATE NOT NULL,
            shelf_life_duration TEXT NOT NULL,
            expiration_date DATE NOT NULL,
            is_consumed BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_expiration ON inventory(expiration_date)')
    conn.commit()
    conn.close()

# Run DB initialization on startup
init_db()

def extract_dates_and_calculate(ocr_text_list):
    """
    Parses OCR text for Production Date and Shelf Life, then calculates Expiration.
    """
    text = "".join(ocr_text_list)
    
    # 1. Regex: Match Production Date (e.g., 2026年08月01日, 2026-08-01, 2026/08/01, 2026.08.01)
    prod_pattern = r'(20\d{2})[-/年.](1[0-2]|0?[1-9])[-/月.](3[01]|[12]\d|0?[1-9])日?'
    prod_match = re.search(prod_pattern, text)
    
    # 2. Regex: Match Shelf life (e.g., 12个月, 90天, 1年)
    shelf_pattern = r'(\d+)\s*(个月|天|年)'
    shelf_match = re.search(shelf_pattern, text)

    if not prod_match or not shelf_match:
        return None, None, None, "Could not find both Production Date and Shelf Life."

    # Parse Production Date
    year, month, day = map(int, prod_match.groups())
    prod_date = datetime(year, month, day)
    
    # Parse Shelf Life
    duration_val = int(shelf_match.group(1))
    duration_unit = shelf_match.group(2)
    shelf_life_str = f"{duration_val}{duration_unit}"

    # 3. Calendar Math to find the final Expiration Date
    if duration_unit == '个月':
        exp_date = prod_date + relativedelta(months=duration_val)
    elif duration_unit == '天':
        exp_date = prod_date + timedelta(days=duration_val)
    elif duration_unit == '年':
        exp_date = prod_date + relativedelta(years=duration_val)
    else:
        return None, None, None, "Unknown duration unit."

    # Standard practice: subtract 1 day (e.g., Jan 1 + 1 year shelf life expires Dec 31)
    exp_date -= timedelta(days=1)
    
    return prod_date.date(), exp_date.date(), shelf_life_str, None


@app.post("/api/scan")
async def scan_food_label(file: UploadFile = File(...)):
    """Endpoint to receive an image, run OCR, and return the calculated dates."""
    image_bytes = await file.read()
    
    # Run RapidOCR on the image bytes
    result, _ = ocr(image_bytes)
    
    if not result:
        return JSONResponse(status_code=400, content={"error": "No text detected. Please use manual override."})
    
    # Extract text blocks from the OCR result format
    text_blocks = [line[1] for line in result]
    
    prod_date, exp_date, shelf_life_str, error = extract_dates_and_calculate(text_blocks)
    
    if error:
        return JSONResponse(status_code=422, content={"error": f"{error} Please use manual override.", "raw_ocr": text_blocks})

    return {
        "status": "success",
        "production_date": str(prod_date),
        "shelf_life": shelf_life_str,
        "calculated_expiration": str(exp_date)
    }

@app.post("/api/add")
async def add_inventory_item(product_name: str, prod_date: str, shelf_life: str, exp_date: str):
    """Endpoint to save the final confirmed data to SQLite."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO inventory (product_name, production_date, shelf_life_duration, expiration_date)
        VALUES (?, ?, ?, ?)
    ''', (product_name, prod_date, shelf_life, exp_date))
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": f"Added {product_name} to database."}