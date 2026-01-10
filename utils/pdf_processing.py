"""
PDF processing utilities for PIS System
Handles PDF image extraction and manipulation
"""

import os
import io
import json
import time
import fitz  # PyMuPDF
from PIL import Image
from werkzeug.utils import secure_filename
import google.generativeai as genai


def extract_specific_image(pdf_path, target_model, upload_folder):
    """
    Attempts to extract an image from the PDF itself.
    Returns None if not found.
    """
    doc = fitz.open(pdf_path)
    model = genai.GenerativeModel('models/gemini-flash-latest')
    
    print(f"--- (Fallback) Searching PDF for visual: {target_model} ---")

    for page_num in range(min(5, len(doc))):
        if page_num > 0: time.sleep(1)

        try:
            page = doc[page_num]
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            page_img_bytes = pix.tobytes("png")
            pil_image = Image.open(io.BytesIO(page_img_bytes))
            
            prompt = f"""
            Find the product image for: "{target_model}".
            Return bounding box: [ymin, xmin, ymax, xmax] (0-1000 scale).
            Output JSON: {{ "found": true, "box_2d": [...] }} or {{ "found": false }}
            """

            response = None
            for attempt in range(2): # Reduced retries for speed
                try:
                    response = model.generate_content(
                        [prompt, {"mime_type": "image/png", "data": page_img_bytes}],
                        generation_config={"response_mime_type": "application/json"}
                    )
                    break 
                except: break

            if not response: continue

            result = json.loads(response.text)
            
            if result.get('found') and result.get('box_2d'):
                ymin, xmin, ymax, xmax = result['box_2d']
                width, height = pil_image.size
                
                left = (xmin / 1000) * width
                top = (ymin / 1000) * height
                right = (xmax / 1000) * width
                bottom = (ymax / 1000) * height
                
                # Smart Padding
                pad_x, pad_y = (right - left) * 0.10, (bottom - top) * 0.10
                left, top = max(0, left - pad_x), max(0, top - pad_y)
                right, bottom = min(width, right + pad_x), min(height, bottom + pad_y)

                if (right - left) > 50:
                    crop = pil_image.crop((left, top, right, bottom))
                    if crop.mode != 'RGB': crop = crop.convert('RGB')
                    
                    safe_name = secure_filename(target_model)
                    filename = f"visual_{safe_name}_{int(time.time())}.jpg"
                    save_path = os.path.join(upload_folder, filename)
                    crop.save(save_path, quality=95)
                    return f"uploads/{filename}"

        except Exception as e:
            print(f"Error on page {page_num}: {e}")
            continue
    
    return None
