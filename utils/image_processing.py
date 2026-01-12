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


def search_google_api(query: str, domain: str | None = None) -> list[str]:
    api_key = os.getenv("GOOGLE_API_KEY")
    cx = os.getenv("GOOGLE_SEARCH_CX")

    if not api_key or not cx:
        return []

    params = {
        "q": query,
        "cx": cx,
        "key": api_key,
        "searchType": "image",
        "num": 5,  # Fetch up to 5 results
        "imgSize": "large",
        "safe": "active",
    }

    if domain:
        params["siteSearch"] = domain
        params["siteSearchFilter"] = "i"

    try:
        print(f"--- Calling Google Image API with query: '{query}' ---")
        if domain:
            print(f"--- Domain filter: {domain} ---")

        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params=params,
            timeout=10
        )
        print(f"--- Google status code: {resp.status_code} ---")
        data = resp.json()

        if "items" not in data:
            print("Google returned NO image results")
            if resp.status_code != 200:
                print(f"--- Google Response Error: {json.dumps(data)} ---")
            return []

        urls = [item["link"] for item in data.get("items", [])]
        print(f"--- Google returned {len(urls)} image results ---")
        return urls

    except Exception as e:
        print(f"--- Google API Error: {str(e)} ---")
        return []
 


def clean_search_query(query: str) -> str:
    """
    Removes internal SKUs, bracketed numbers, and ERP codes
    before sending query to Google.
    """
    query = re.sub(r"\([^)]*\)", "", query)
    query = re.sub(r"\b[A-Z0-9]{8,}\b", "", query)

    cleaned = " ".join(query.split())
    print(f"--- Cleaned Search Query: '{cleaned}' ---")
    return cleaned




def ai_validate_image(image_bytes: bytes, product_name: str) -> bool:
    """
    Lightweight AI check:
    - Is the main product visible?
    - Is the image appropriate and relevant?
    """

    model = genai.GenerativeModel("models/gemini-flash-latest")

    prompt = f"""
You are evaluating a potential product image for: "{product_name}".

Your goal is to be helpful and lenient. Approve the image if it looks like a professional product photo and is reasonably relevant to the product name.

Approve if:
- The product (or a very similar model/variation) is clearly featured.
- It looks like a high-quality product photo, even if it's from a review site or social media.
- The image is clean and would look good in a catalog.

Reject ONLY if:
- It is completely unrelated (e.g., a photo of a person, a landscape, or a totally different category of item).
- The image is extremely low quality, blurry, or contains heavy watermarks.
- It is a screenshot of a website rather than a direct image.

Respond ONLY with JSON:
{{ "approve": true }} or {{ "approve": false }}
"""

    try:
        # Check image size/type before sending to AI
        if len(image_bytes) > 20 * 1024 * 1024: # 20MB limit
            print("❌ Image too large for validation")
            return False

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
        print(f"AI image validation failed for '{product_name}':", e)
        return False




def download_image_bytes(image_url: str) -> bytes | None:
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
        }
        resp = requests.get(image_url, headers=headers, timeout=10, stream=True)
        if resp.status_code == 200:
            content_type = resp.headers.get('Content-Type', '')
            content_length = resp.headers.get('Content-Length', 'unknown')
            
            if 'image' not in content_type:
                print(f"⚠ Skipping non-image content type: {content_type}")
                return None
            
            print(f"--- Downloaded {content_length} bytes (Type: {content_type}) ---")
            return resp.content
        else:
            print(f"--- Download failed with status {resp.status_code} ---")
    except Exception as e:
        print("Image byte download failed:", e)
    return None


def scrape_images_from_url(url: str) -> list[str]:
    """
    Scrapes a webpage for potential product images.
    """
    try:
        from bs4 import BeautifulSoup
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return []
            
        soup = BeautifulSoup(resp.content, 'html.parser')
        images = []
        
        # Look for images that are likely product images
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
            if not src:
                continue
            
            # Resolve relative URLs
            if src.startswith('/'):
                from urllib.parse import urljoin
                src = urljoin(url, src)
            elif not src.startswith('http'):
                continue
                
            # Filter out icons, logos, etc (naive check)
            if any(x in src.lower() for x in ['logo', 'icon', 'banner', 'pixel', 'sprite']):
                continue
                
            images.append(src)
            if len(images) >= 10:  # Cap at 10
                break
                
        return images
    except Exception as e:
        print(f"Scrape image error: {e}")
        return []






def find_best_images(model_name: str, supplier_url: str | None = None) -> list[str]:
    """
    Image selection strategy:
    Returns a list of candidate image URLs.
    """
    candidates = []

    # --- 1️ Supplier-domain search (STRICT) ---
    if supplier_url:
        domain = extract_domain(supplier_url)
        if domain:
            supplier_query = f"{model_name} product image"
            print(f"--- Searching Supplier Domain: {domain} ---")
            candidates.extend(search_google_api(supplier_query, domain=domain))

    # --- 2️ Web Scraping Fallback (If Google fails or returns nothing) ---
    if not candidates and supplier_url:
        print(f"--- Attempting Direct Scrape of Supplier URL: {supplier_url} ---")
        candidates.extend(scrape_images_from_url(supplier_url))

    # --- 3️ Open-web fallback (CLEAN & LOOSE) ---
    clean_name = clean_search_query(model_name)
    fallback_query = f"{clean_name} official product image "
    
    print(f"--- Fallback Query: '{fallback_query}' ---")
    print("--- Calling Open Search ---")
    
    candidates.extend(search_google_api(fallback_query))

    # Remove duplicates while preserving order
    seen = set()
    result = []
    for url in candidates:
        if url not in seen:
            result.append(url)
            seen.add(url)
    
    return result



def find_and_validate_image(model_name: str, supplier_url: str | None = None) -> str | None:
    image_candidates = find_best_images(model_name, supplier_url)
    
    if not image_candidates:
        print("🚫 No image candidates found")
        return None

    print(f"🔄 Evaluating {len(image_candidates)} candidate images")
    
    for i, image_url in enumerate(image_candidates):
        print(f"--- Testing candidate {i+1}/{len(image_candidates)}: {image_url} ---")
        
        image_bytes = download_image_bytes(image_url)
        if not image_bytes:
            continue

        if ai_validate_image(image_bytes, model_name):
            print(f"✔ AI approved image: {image_url}")
            return image_url

        print(f"❌ AI rejected image {i+1}")

    print("🚫 No acceptable image found after checking all candidates")
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
