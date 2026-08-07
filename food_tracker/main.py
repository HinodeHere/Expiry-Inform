import os
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Optional
from dateutil.relativedelta import relativedelta
from fastapi import FastAPI, UploadFile, File, Query
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
from rapidocr_onnxruntime import RapidOCR

app = FastAPI(title="Local Food Tracker API")

# Initialize CPU-optimized ONNX model locally
ocr = RapidOCR()

DB_PATH = "/app/data/inventory.db"


def init_db():
    """Create the SQLite database and inventory table if they don't exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
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
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_expiration ON inventory(expiration_date)')
        conn.commit()


# Run DB initialization on application startup
init_db()


class ItemCreate(BaseModel):
    product_name: str
    production_date: str
    shelf_life_duration: str
    expiration_date: str


def extract_dates_and_calculate(ocr_text_list):
    """
    Parses OCR text blocks for dates. Supports:
    1A/B/C. Direct EXP in strict formats (handles full-width Chinese colons)
    2. Western Best By (Fuzzy Dot-Matrix)
    3. Production Date + Shelf Life math
    4. Universal Date Sorter (Safely extracts Max/Min dates from jumbled OCR text)
    """
    text = " ".join(ocr_text_list)

    # --- STRATEGY 1A: Direct Expiration Date (Strict Full Date) ---
    # We added '：' to support Chinese full-width colons
    exp_prefix = r'(?:EXPIRY\s*DATE|EXPIRY|EXP\s*DATE|EXP|有效期至|限期使用日期)[\s:：]*'
    
    # 1. Chinese format: 2024年12月01日
    m_cn = re.search(exp_prefix + r'(20\d{2})年(1[0-2]|0?[1-9])月(3[01]|[12]\d|0?[1-9])日?', text, re.IGNORECASE)
    # 2. Symbol format: Requires the exact same symbol (e.g. '-') between year/month and month/day
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

    # --- STRATEGY 1B: Direct Expiration Date (MM.YYYY) ---
    exp_my_pattern = r'(?:EXPIRY\s*DATE|EXPIRY|EXP\s*DATE|EXP|有效期至)[\s:：]*(1[0-2]|0?[1-9])([-/.]?)(20\d{2})'
    exp_my_match = re.search(exp_my_pattern, text, re.IGNORECASE)
    if exp_my_match:
        try:
            month, year = int(exp_my_match.group(1)), int(exp_my_match.group(3))
            return "", datetime(year, month, 1).date(), "Direct EXP", None
        except ValueError: pass

    # --- STRATEGY 1C: Direct Expiration Date (YYYY.MM) ---
    exp_ym_pattern = r'(?:EXPIRY\s*DATE|EXPIRY|EXP\s*DATE|EXP|有效期至)[\s:：]*(20\d{2})([-/.]?)(1[0-2]|0?[1-9])(?!\d)'
    exp_ym_match = re.search(exp_ym_pattern, text, re.IGNORECASE)
    if exp_ym_match:
        try:
            year, month = int(exp_ym_match.group(1)), int(exp_ym_match.group(3))
            return "", datetime(year, month, 1).date(), "Direct EXP", None
        except ValueError: pass

    # --- STRATEGY 2: Western "Best By" Dates (Fuzzy Dot-Matrix) ---
    eng_month_pattern = r'(JAN|JRN|JHN|1AN|FEB|FE8|FES|PEB|MAR|MHR|NAR|APR|HPR|RPR|4PR|MAY|MRY|M4Y|JUN|JUM|JVN|JUL|JUI|JU1|JVL|AUG|HUG|AU6|AUO|RUG|SEP|5EP|SFP|5FP|OCT|0CT|QCT|OGT|NOV|N0V|NDV|MOV|DEC|DFC|0EC|D3C|OEC)\s*(\d{1,2})[\s,]*(\d{2}|\d{4})'
    eng_match = re.search(eng_month_pattern, text, re.IGNORECASE)
    if eng_match:
        month_str, day_str, year_str = eng_match.groups()
        month_str = month_str.upper()
        month_map = { 'JAN': 1, 'JRN': 1, 'JHN': 1, '1AN': 1, 'FEB': 2, 'FE8': 2, 'FES': 2, 'PEB': 2, 'MAR': 3, 'MHR': 3, 'NAR': 3, 'APR': 4, 'HPR': 4, 'RPR': 4, '4PR': 4, 'MAY': 5, 'MRY': 5, 'M4Y': 5, 'JUN': 6, 'JUM': 6, 'JVN': 6, 'JUL': 7, 'JUI': 7, 'JU1': 7, 'JVL': 7, 'AUG': 8, 'HUG': 8, 'AU6': 8, 'AUO': 8, 'RUG': 8, 'SEP': 9, '5EP': 9, 'SFP': 9, '5FP': 9, 'OCT': 10, '0CT': 10, 'QCT': 10, 'OGT': 10, 'NOV': 11, 'N0V': 11, 'NDV': 11, 'MOV': 11, 'DEC': 12, 'DFC': 12, '0EC': 12, 'D3C': 12, 'OEC': 12 }
        month = month_map[month_str]
        day, year = int(day_str), int(year_str)
        if year < 100: year += 2000
        try: return "", datetime(year, month, day).date(), "Direct EXP", None
        except ValueError: pass

    # --- STRATEGY 3: Production Date + Shelf Life (Standard Chinese Food) ---
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
                prod_match = match_6
                is_6_digit = True

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
            
            duration_val = int(shelf_match.group(1))
            duration_unit = shelf_match.group(2)
            shelf_life_str = f"{duration_val}{duration_unit}"

            if duration_unit == '个月': exp_date = prod_date + relativedelta(months=duration_val)
            elif duration_unit in ['天', '日']: exp_date = prod_date + timedelta(days=duration_val)
            elif duration_unit == '年': exp_date = prod_date + relativedelta(years=duration_val)
            else: return None, None, None, f"Unknown shelf life unit. The AI read: {text}"

            exp_date -= timedelta(days=1)
            return prod_date, exp_date, shelf_life_str, None
        except ValueError: pass

    # --- STRATEGY 4: Universal Date Sorter (Fallback for Jumbled OCR) ---
    found_dates = set()

    # Broadly search for any 8-digit date string, even with OCR typos
    fallback_8 = r'(20\d{2})[-/年. ]?(1[0-2]|0?[1-9])[-/月. ]?(3[01]|[12]\d|0?[1-9])日?'
    for m in re.finditer(fallback_8, text):
        try:
            y, mo, d = map(int, m.groups())
            found_dates.add(datetime(y, mo, d).date())
        except ValueError: pass

    # Broadly search for any 6-digit (YYYY.MM) string
    fallback_6 = r'(20\d{2})[-/年. ](1[0-2]|0?[1-9])(?!\d)'
    for m in re.finditer(fallback_6, text):
        try:
            y, mo = map(int, m.groups())
            found_dates.add(datetime(y, mo, 1).date())
        except ValueError: pass

    sorted_dates = sorted(list(found_dates))

    # If we found at least 2 dates anywhere in the messy text, sort them!
    if len(sorted_dates) >= 2:
        exp_date = sorted_dates[-1]   # The absolute maximum date is the Expiry
        prod_date = sorted_dates[-2]  # The second maximum date is the Production
        return prod_date, exp_date, "Auto-Extracted", None
    elif len(sorted_dates) == 1:
        if re.search(r'(EXP|有效期|保质期至|限期)', text, re.IGNORECASE):
            return "", sorted_dates[0], "Auto-Extracted", None

    return None, None, None, f"Failed. The AI read: {text}"

@app.get("/")
async def serve_frontend():
    """Serves index.html at root route."""
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>index.html not found!</h1>", status_code=404)


@app.post("/api/scan")
async def scan_food_label(file: UploadFile = File(...)):
    """Receives image upload, runs OCR, and extracts calculated dates."""
    image_bytes = await file.read()

    # Run RapidOCR
    result, _ = ocr(image_bytes)

    if not result:
        return JSONResponse(
            status_code=400,
            content={"error": "No text detected in image. Please use manual override."}
        )

    # Safely extract text lines
    text_blocks = [line[1] for line in result if len(line) > 1]

    prod_date, exp_date, shelf_life_str, error = extract_dates_and_calculate(text_blocks)

    if error:
        return JSONResponse(
            status_code=422,
            content={"error": f"{error} Please use manual override.", "raw_ocr": text_blocks}
        )

    return {
        "status": "success",
        "production_date": str(prod_date),
        "shelf_life": shelf_life_str,
        "calculated_expiration": str(exp_date)
    }


@app.post("/api/add")
async def add_inventory_item(
    item: Optional[ItemCreate] = None,
    product_name: Optional[str] = Query(None),
    prod_date: Optional[str] = Query(None),
    shelf_life: Optional[str] = Query(None),
    exp_date: Optional[str] = Query(None)
):
    """Saves confirmed item to SQLite. Supports both JSON payload and query params."""
    name = item.product_name if item else product_name
    p_date = item.production_date if item else prod_date
    s_life = item.shelf_life_duration if item else shelf_life
    e_date = item.expiration_date if item else exp_date

    if not all([name, p_date, s_life, e_date]):
        return JSONResponse(status_code=400, content={"error": "Missing required fields."})

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO inventory (product_name, production_date, shelf_life_duration, expiration_date)
            VALUES (?, ?, ?, ?)
        ''', (name, p_date, s_life, e_date))
        conn.commit()

    return {"status": "success", "message": f"Successfully added {name} to inventory."}

@app.get("/inventory")
async def serve_inventory_page():
    """Serves the inventory.html dashboard."""
    if os.path.exists("inventory.html"):
        with open("inventory.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>inventory.html not found!</h1>", status_code=404)


@app.get("/api/inventory")
async def get_inventory():
    """Fetches all active items from the database."""
    with sqlite3.connect(DB_PATH) as conn:
        # This row_factory makes SQLite return dictionaries instead of raw tuples
        conn.row_factory = sqlite3.Row 
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, product_name, production_date, shelf_life_duration, expiration_date 
            FROM inventory 
            WHERE is_consumed = 0 
            ORDER BY expiration_date ASC
        ''')
        items = [dict(row) for row in cursor.fetchall()]
        
    return {"status": "success", "items": items}


@app.post("/api/consume/{item_id}")
async def consume_item(item_id: int):
    """Marks an item as consumed so it no longer triggers alerts."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE inventory SET is_consumed = 1 WHERE id = ?', (item_id,))
        conn.commit()
        
    return {"status": "success", "message": "Item marked as consumed."}