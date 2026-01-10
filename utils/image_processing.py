"""
Image processing utilities for PIS System
Handles image search, validation, and downloading
"""

import os
import re
import json
import time
import requests
import shutil
from urllib.parse import urlparse
from werkzeug.utils import secure_filename
import google.generativeai as genai


def extract_domain(url):
    """Extracts the base domain (e.g., mi.com) from a full URL."""
    try:
        parsed = urlparse(url)
        return parsed.netloc.replace("www.", "")
    except:
        return None


def search_google_api(query: str, domain: str | None = None) -> str | None:
    api_key = os.getenv("GOOGLE_API_KEY")
    cx = os.getenv("GOOGLE_SEARCH_CX")

    if not api_key or not cx:
        return None

    params = {
        "q": query,
        "cx": cx,
        "key": api_key,
        "searchType": "image",
        "num": 1,
        "imgSize": "large",
        "safe": "active",
    }

    if domain:
        params["siteSearch"] = domain
        params["siteSearchFilter"] = "i"

    try:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params=params,
            timeout=10
        )
        data = resp.json()

        if "items" not in data:
            print("Google returned NO image results")
            return None

        return data["items"][0]["link"]

    except Exception as e:
        return None
 


def clean_search_query(query: str) -> str:
    """
    Removes internal SKUs, bracketed numbers, and ERP codes
    before sending query to Google.
    """
    query = re.sub(r"\([^)]*\)", "", query)
    query = re.sub(r"\b[A-Z0-9]{8,}\b", "", query)

    return " ".join(query.split())




def ai_validate_image(image_bytes: bytes, product_name: str) -> bool:
    """
    Lightweight AI check:
    - Is the main product visible?
    - Is the image appropriate and relevant?
    """

    model = genai.GenerativeModel("models/gemini-flash-latest")

    prompt = f"""
You are checking a product image.

Product name:
"{product_name}"

Approve if:
- The main product is clearly visible.
- The image reasonably matches the product.
- The image is appropriate for a product listing.

Reject if:
- The product is not visible.
- The image shows a different product.
- The image is unclear or misleading.

Respond ONLY with JSON:
{{ "approve": true }} or {{ "approve": false }}
"""

    try:
        response = model.generate_content(
            [
                prompt,
                {"mime_type": "image/jpeg", "data": image_bytes}
            ],
            generation_config={"response_mime_type": "application/json"}
        )

        result = json.loads(response.text)
        return bool(result.get("approve", False))

    except Exception as e:
        print("AI image validation failed:", e)
        return False




def download_image_bytes(image_url: str) -> bytes | None:
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(image_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.content
    except Exception as e:
        print("Image byte download failed:", e)
    return None






def find_best_image(model_name: str, supplier_url: str | None = None) -> str | None:
    """
    Image selection strategy:
    1. Try supplier-domain image search (strict).
    2. Fallback to open-web search using cleaned product name.
    """

    # --- 1️ Supplier-domain search (STRICT) ---
    if supplier_url:
        domain = extract_domain(supplier_url)
        if domain:
            supplier_query = f"{model_name} product image"
            print(f"--- Searching Supplier Domain: {domain} ---")
            img = search_google_api(supplier_query, domain=domain)
            if img:
                print(f"✔ Image found via supplier domain: {domain}")
                return img

    # --- 2️ Open-web fallback (CLEAN & LOOSE) ---
    clean_name = clean_search_query(model_name)

    fallback_query = (
        f"{clean_name} official product image "
    )
    print("--- Falling back to Open Search ---")

    return search_google_api(fallback_query)



def find_and_validate_image(model_name: str, supplier_url: str | None = None) -> str | None:
    MAX_ATTEMPTS = 3

    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"🔄 Image attempt {attempt}/{MAX_ATTEMPTS}")

        image_url = find_best_image(model_name, supplier_url)
        if not image_url:
            continue

        image_bytes = download_image_bytes(image_url)
        if not image_bytes:
            continue

        if ai_validate_image(image_bytes, model_name):
            print("✔ AI approved image")
            return image_url

        print("❌ AI rejected image, retrying")

    print("🚫 No acceptable image found")
    return None




def download_web_image(image_url, model_name, upload_folder):
    """
    Downloads an image from a URL provided by the AI/Scraper.
    """
    try:
        if not image_url or not image_url.startswith('http'):
            return None 
            
        headers = {'User-Agent': 'Mozilla/5.0'}
        print(f"--- Attempting Web Download for {model_name}: {image_url} ---")
        response = requests.get(image_url, headers=headers, stream=True, timeout=10)
        
        if response.status_code == 200:
            safe_name = secure_filename(model_name)
            # Add random timestamp to avoid caching/overwriting issues
            filename = f"web_{safe_name}_{int(time.time())}.jpg"
            save_path = os.path.join(upload_folder, filename)
            
            with open(save_path, 'wb') as out_file:
                shutil.copyfileobj(response.raw, out_file)
            
            print(f"--- Web Download Success: {filename} ---")
            return f"uploads/{filename}"
    except Exception as e:
        print(f"Failed to download web image {image_url}: {e}")
        return None
    return None
