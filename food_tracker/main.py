import os
import re
import sqlite3
import cv2
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, List
from dateutil.relativedelta import relativedelta
from fastapi import FastAPI, UploadFile, File, Query
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from rapidocr_onnxruntime import RapidOCR

app = FastAPI(title="Local Food Tracker API")
ocr = RapidOCR()

DB_PATH = "/app/data/inventory.db"
FAILED_DIR = "/app/data/failed_images"

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(FAILED_DIR, exist_ok=True)
    
    with sqlite3.connect(DB_PATH) as conn:
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
        # Safe migration for new features (Quantity & Location)
        cursor.execute("PRAGMA table_info(inventory)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'quantity' not in columns:
            cursor.execute("ALTER TABLE inventory ADD COLUMN quantity INTEGER DEFAULT 1")
        if 'location' not in columns:
            cursor.execute("ALTER TABLE inventory ADD COLUMN location TEXT DEFAULT 'Unassigned'")
            
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_expiration ON inventory(expiration_date)')
        conn.commit()

init_db()

# Mount static folder so failed images can be viewed via URL
app.mount("/failed_data", StaticFiles(directory=FAILED_DIR), name="failed_data")

class ItemCreate(BaseModel):
    product_name: str
    production_date: str
    shelf_life_duration: str
    expiration_date: str
    quantity: Optional[int] = 1
    location: Optional[str] = "Unassigned"

class BatchRequest(BaseModel):
    item_ids: List[int]

def extract_dates_and_calculate(ocr_text_list):
    text = " ".join(ocr_text_list)

    # 1A: Direct Expiration Date (Strict Full Date)
    exp_prefix = r'(?:EXPIRY\s*DATE|EXPIRY|EXP\s*DATE|EXP|有效期至|限期使用日期)[\s:：]*'
    m_cn = re.search(exp_prefix + r'(20\d{2})年(1[0-2]|0?[1-9])月(3[01]|[12]\d|0?[1-9])日?', text, re.IGNORECASE)
    m_sym = re.search(exp_prefix + r'(20\d{2})([-/.]?)(1[0-2]|0?[1-9])\2(3[01]|[12]\d|0?[1-9])(?!\d)', text, re.IGNORECASE)
    
    if m_cn:
        try:
            y, m, d = map(int, m_cn.groups())
            return "", datetime(y, m, d).date(), "Direct EXP", None
        except ValueError: pass
    elif m_sym:
        try:
            y, m, d = int(m_sym.group(1)), int(m_sym.group(3)), int(m_sym.group(4))
            return "", datetime(y, m, d).date(), "Direct EXP", None
        except ValueError: pass

    # 1B: Direct Expiration Date (MM.YYYY or MM/YY)
    exp_my_pattern = r'(?:EXPIRY\s*DATE|EXPIRY|EXP\s*DATE|EXP|有效期至)[\s:：.]*(1[0-2]|0?[1-9])([-/.])(\d{2}|\d{4})(?!\d)'
    exp_my_match = re.search(exp_my_pattern, text, re.IGNORECASE)
    if exp_my_match:
        try:
            month, year = int(exp_my_match.group(1)), int(exp_my_match.group(3))
            if year < 100: year += 2000
            return "", datetime(year, month, 1).date(), "Direct EXP", None
        except ValueError: pass

    # 1C: Direct Expiration Date (YYYY.MM)
    exp_ym_pattern = r'(?:EXPIRY\s*DATE|EXPIRY|EXP\s*DATE|EXP|有效期至)[\s:：]*(20\d{2})([-/.]?)(1[0-2]|0?[1-9])(?!\d)'
    exp_ym_match = re.search(exp_ym_pattern, text, re.IGNORECASE)
    if exp_ym_match:
        try:
            year, month = int(exp_ym_match.group(1)), int(exp_ym_match.group(3))
            return "", datetime(year, month, 1).date(), "Direct EXP", None
        except ValueError: pass

    # 2: Western "Best By" Dates (Fuzzy)
    eng_month_pattern = r'(JAN|JRN|JHN|1AN|FEB|FE8|FES|PEB|MAR|MHR|NAR|APR|HPR|RPR|4PR|MAY|MRY|M4Y|JUN|JUM|JVN|JUL|JUI|JU1|JVL|AUG|HUG|AU6|AUO|RUG|SEP|5EP|SFP|5FP|OCT|0CT|QCT|OGT|NOV|N0V|NDV|MOV|DEC|DFC|0EC|D3C|OEC)\s*(\d{1,2})[\s,]*(\d{2}|\d{4})'
    eng_match = re.search(eng_month_pattern, text, re.IGNORECASE)
    if eng_match:
        month_str, day_str, year_str = eng_match.groups()
        month_map = { 'JAN': 1, 'JRN': 1, 'JHN': 1, '1AN': 1, 'FEB': 2, 'FE8': 2, 'FES': 2, 'PEB': 2, 'MAR': 3, 'MHR': 3, 'NAR': 3, 'APR': 4, 'HPR': 4, 'RPR': 4, '4PR': 4, 'MAY': 5, 'MRY': 5, 'M4Y': 5, 'JUN': 6, 'JUM': 6, 'JVN': 6, 'JUL': 7, 'JUI': 7, 'JU1': 7, 'JVL': 7, 'AUG': 8, 'HUG': 8, 'AU6': 8, 'AUO': 8, 'RUG': 8, 'SEP': 9, '5EP': 9, 'SFP': 9, '5FP': 9, 'OCT': 10, '0CT': 10, 'QCT': 10, 'OGT': 10, 'NOV': 11, 'N0V': 11, 'NDV': 11, 'MOV': 11, 'DEC': 12, 'DFC': 12, '0EC': 12, 'D3C': 12, 'OEC': 12 }
        month, day, year = month_map[month_str.upper()], int(day_str), int(year_str)
        if year < 100: year += 2000
        try: return "", datetime(year, month, day).date(), "Direct EXP", None
        except ValueError: pass

    # 3: Production Date + Shelf Life
    prod_match, is_6_digit = None, False
    prod_pattern_sep = r'(20\d{2})[-/年.](1[0-2]|0?[1-9])[-/月.](3[01]|[12]\d|0?[1-9])日?'
    match_sep = re.search(prod_pattern_sep, text)
    if match_sep: prod_match = match_sep
    else:
        prod_pattern_8 = r'(20\d{2})(1[0-2]|0[1-9])(3[01]|[12]\d|0[1-9])'
        match_8 = re.search(prod_pattern_8, text)
        if match_8: prod_match = match_8
        else:
            prod_pattern_6 = r'(20\d{2})[-/年.]?(1[0-2]|0[1-9])月?'
            match_6 = re.search(prod_pattern_6, text)
            if match_6:
                prod_match, is_6_digit = match_6, True

    shelf_pattern = r'(\d+)\s*(个月|天|日|年)'
    shelf_match = re.search(shelf_pattern, text)

    if prod_match and shelf_match:
        try:
            if is_6_digit:
                year, month = map(int, prod_match.groups())
                day = 1 
            else:
                year, month, day = map(int, prod_match.groups())
            prod_date = datetime(year, month, day).date()
            
            duration_val, duration_unit = int(shelf_match.group(1)), shelf_match.group(2)
            shelf_life_str = f"{duration_val}{duration_unit}"

            if duration_unit == '个月': exp_date = prod_date + relativedelta(months=duration_val)
            elif duration_unit in ['天', '日']: exp_date = prod_date + timedelta(days=duration_val)
            elif duration_unit == '年': exp_date = prod_date + relativedelta(years=duration_val)
            else: return None, None, None, f"Unknown shelf life unit. The AI read: {text}"

            exp_date -= timedelta(days=1)
            return prod_date, exp_date, shelf_life_str, None
        except ValueError: pass

    # 4: Universal Date Sorter
    found_dates = set()
    fallback_8 = r'(20\d{2})[-/年. ]?(1[0-2]|0?[1-9])[-/月. ]?(3[01]|[12]\d|0?[1-9])日?'
    for m in re.finditer(fallback_8, text):
        try:
            y, mo, d = map(int, m.groups())
            found_dates.add(datetime(y, mo, d).date())
        except ValueError: pass

    fallback_6 = r'(20\d{2})[-/年. ](1[0-2]|0?[1-9])(?!\d)'
    for m in re.finditer(fallback_6, text):
        try:
            y, mo = map(int, m.groups())
            found_dates.add(datetime(y, mo, 1).date())
        except ValueError: pass

    sorted_dates = sorted(list(found_dates))
    if len(sorted_dates) >= 2:
        return sorted_dates[-2], sorted_dates[-1], "Auto-Extracted", None
    elif len(sorted_dates) == 1 and re.search(r'(EXP|有效期|保质期至|限期)', text, re.IGNORECASE):
        return "", sorted_dates[0], "Auto-Extracted", None

    return None, None, None, f"Failed. The AI read: {text}"

# --- ROUTES ---

@app.get("/")
async def serve_frontend():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f: return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>index.html not found!</h1>", status_code=404)

@app.get("/inventory")
async def serve_inventory_page():
    if os.path.exists("inventory.html"):
        with open("inventory.html", "r", encoding="utf-8") as f: return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>inventory.html not found!</h1>", status_code=404)

@app.get("/failed")
async def serve_failed_page():
    if os.path.exists("failed_images.html"):
        with open("failed_images.html", "r", encoding="utf-8") as f: return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>failed_images.html not found!</h1>", status_code=404)

@app.post("/api/scan")
async def scan_labels(files: List[UploadFile] = File(...)):
    combined_text_list, file_bytes_list = [], []
    
    for file in files:
        contents = await file.read()
        file_bytes_list.append(contents)
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None: continue
        
        result, _ = ocr(img)
        if result:
            for line in result: combined_text_list.append(line[1])

    if not combined_text_list:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for i, contents in enumerate(file_bytes_list):
            with open(os.path.join(FAILED_DIR, f"{timestamp}_fail_{i}.jpg"), "wb") as f: f.write(contents)
        return JSONResponse(status_code=400, content={"error": "Could not read text. Image saved to failed queue."})

    prod_date, exp_date, shelf_life, error = extract_dates_and_calculate(combined_text_list)
    
    if error:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for i, contents in enumerate(file_bytes_list):
            with open(os.path.join(FAILED_DIR, f"{timestamp}_fail_{i}.jpg"), "wb") as f: f.write(contents)
        return JSONResponse(status_code=400, content={"error": error})

    suggested_name = ""
    for text in combined_text_list:
        if len(text) > 2 and not re.search(r'(EXP|PROD|MFG|日期|批号|20\d{2}|[0-9]{4}|[0-9]{2}\.[0-9]{2})', text, re.IGNORECASE):
            suggested_name = text
            break

    return {
        "suggested_name": suggested_name,
        "production_date": str(prod_date) if prod_date else "",
        "shelf_life": shelf_life,
        "calculated_expiration": str(exp_date) if exp_date else ""
    }

@app.post("/api/add")
async def add_inventory_item(
    product_name: str = Query(...), prod_date: str = Query(...), shelf_life: str = Query(...),
    exp_date: str = Query(...), quantity: int = Query(1), location: str = Query("Unassigned")
):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO inventory (product_name, production_date, shelf_life_duration, expiration_date, quantity, location)
            VALUES (?, ?, ?, ?, ?, ?)''', (product_name, prod_date, shelf_life, exp_date, quantity, location))
        conn.commit()
    return {"status": "success"}

@app.get("/api/inventory")
async def get_inventory():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row 
        cursor = conn.cursor()
        cursor.execute('SELECT id, product_name, production_date, shelf_life_duration, expiration_date, quantity, location FROM inventory WHERE is_consumed = 0 ORDER BY expiration_date ASC')
        items = [dict(row) for row in cursor.fetchall()]
    return {"status": "success", "items": items}

@app.get("/api/product_names")
async def get_product_names():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT product_name FROM inventory WHERE product_name != "Unknown Item"')
        return {"names": [row[0] for row in cursor.fetchall()]}

@app.get("/api/locations")
async def get_locations():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT location FROM inventory WHERE location != "Unassigned" AND location IS NOT NULL')
        return {"locations": [row[0] for row in cursor.fetchall()]}

@app.get("/api/failed_images")
async def get_failed_images():
    if not os.path.exists(FAILED_DIR): return {"images": []}
    files = sorted(os.listdir(FAILED_DIR), reverse=True)
    return {"images": [f for f in files if f.lower().endswith(('.jpg', '.jpeg', '.png'))]}

@app.post("/api/consume/{item_id}")
async def consume_item(item_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE inventory SET is_consumed = 1, quantity = 0 WHERE id = ?', (item_id,))
        conn.commit()
    return {"status": "success"}

@app.post("/api/decrement/{item_id}")
async def decrement_item(item_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT quantity FROM inventory WHERE id = ?', (item_id,))
        row = cursor.fetchone()
        if row and row[0] > 1: cursor.execute('UPDATE inventory SET quantity = quantity - 1 WHERE id = ?', (item_id,))
        else: cursor.execute('UPDATE inventory SET is_consumed = 1, quantity = 0 WHERE id = ?', (item_id,))
        conn.commit()
    return {"status": "success"}

@app.post("/api/update_quantity/{item_id}")
async def update_quantity(item_id: int, quantity: int = Query(...)):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        if quantity <= 0: cursor.execute('UPDATE inventory SET is_consumed = 1, quantity = 0 WHERE id = ?', (item_id,))
        else: cursor.execute('UPDATE inventory SET quantity = ? WHERE id = ?', (quantity, item_id))
        conn.commit()
    return {"status": "success"}

@app.post("/api/consume_batch")
async def consume_batch(req: BatchRequest):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.executemany('UPDATE inventory SET is_consumed = 1, quantity = 0 WHERE id = ?', [(i,) for i in req.item_ids])
        conn.commit()
    return {"status": "success"}

@app.delete("/api/failed_images/{filename}")
async def delete_failed_image(filename: str):
    """Deletes a specific failed image from the server."""
    # Prevent directory traversal attacks
    if ".." in filename or "/" in filename:
        return JSONResponse(status_code=400, content={"error": "Invalid filename."})
    
    file_path = os.path.join(FAILED_DIR, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
        return {"status": "success"}
    return JSONResponse(status_code=404, content={"error": "File not found."})