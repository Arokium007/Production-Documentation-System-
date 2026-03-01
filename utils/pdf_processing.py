"""
PDF processing utilities for PIS System
Handles PDF image extraction using high-quality page screenshots
and AI-powered product detection.
"""

import os
import io
import json
import time
import fitz  # PyMuPDF
from PIL import Image, ImageFilter, ImageStat
from werkzeug.utils import secure_filename
import google.generativeai as genai


def extract_specific_image(pdf_path, target_model, upload_folder):
    """
    Extracts a product image from a PDF using a multi-pass approach:
    
    Pass 1: Try to extract embedded images directly (high quality, no AI needed)
    Pass 2: AI-powered screenshot scanning with high-res page renders
    
    Returns the path to the saved image, or None if not found.
    """
    if not pdf_path or not os.path.exists(pdf_path):
        return None
    
    print(f"🔍 PDF Image Extraction starting for: '{target_model}'")
    
    # ============ PASS 1: Extract Embedded Images ============
    # Try to get actual embedded images from the PDF first — they're higher quality
    result = _extract_embedded_images(pdf_path, target_model, upload_folder)
    if result:
        print(f"✅ Pass 1 SUCCESS: Found embedded image for '{target_model}'")
        return result
    
    print(f"--- Pass 1 found no suitable embedded images, trying screenshot scan ---")
    
    # ============ PASS 2: AI Screenshot Scan ============
    result = _extract_via_screenshot(pdf_path, target_model, upload_folder)
    if result:
        print(f"✅ Pass 2 SUCCESS: Found product via screenshot scan for '{target_model}'")
        return result
    
    print(f"🚫 No product image found in PDF for '{target_model}'")
    return None


def _extract_embedded_images(pdf_path, target_model, upload_folder):
    """
    Pass 1: Extract actual embedded images from the PDF.
    Filters by minimum size and uses AI to pick the best product image.
    """
    try:
        doc = fitz.open(pdf_path)
        candidate_images = []
        
        # Scan up to 10 pages for embedded images
        for page_num in range(min(10, len(doc))):
            page = doc[page_num]
            image_list = page.get_images(full=True)
            
            for img_index, img_info in enumerate(image_list):
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                    if not base_image:
                        continue
                    
                    image_bytes = base_image["image"]
                    img_ext = base_image.get("ext", "png")
                    
                    # Skip tiny images (logos, icons, decorations)
                    pil_img = Image.open(io.BytesIO(image_bytes))
                    w, h = pil_img.size
                    
                    if w < 150 or h < 150:
                        continue
                    
                    # Skip images that are mostly one color (solid backgrounds, separators)
                    if _is_mostly_solid(pil_img):
                        continue
                    
                    print(f"  📎 Embedded image found: {w}x{h} ({len(image_bytes)} bytes) on page {page_num+1}")
                    candidate_images.append({
                        'bytes': image_bytes,
                        'width': w,
                        'height': h,
                        'page': page_num,
                        'ext': img_ext
                    })
                    
                    # Cap at 8 candidates to avoid overwhelming AI
                    if len(candidate_images) >= 8:
                        break
                        
                except Exception as e:
                    print(f"  ⚠ Could not extract image xref {xref}: {e}")
                    continue
            
            if len(candidate_images) >= 8:
                break
        
        doc.close()
        
        if not candidate_images:
            return None
        
        print(f"  📦 Found {len(candidate_images)} embedded image candidates, sending to AI...")
        
        # If only one candidate and it's large enough, use it directly
        if len(candidate_images) == 1 and candidate_images[0]['width'] >= 200:
            return _save_candidate_image(candidate_images[0], target_model, upload_folder)
        
        # Use AI to pick the best product image
        return _ai_pick_best_from_candidates(candidate_images, target_model, upload_folder)
        
    except Exception as e:
        print(f"  ⚠ Embedded extraction error: {e}")
        return None


def _extract_via_screenshot(pdf_path, target_model, upload_folder):
    """
    Pass 2: High-resolution page screenshots + AI bounding box detection.
    Enhanced with:
    - 3x resolution matrix for sharp renders
    - Improved AI prompt with explicit visual examples
    - Multi-page scanning with early exit
    - Quality validation on cropped result
    """
    try:
        doc = fitz.open(pdf_path)
        model = genai.GenerativeModel('models/gemini-flash-latest')
        
        print(f"  📸 Screenshot scan: {min(8, len(doc))} pages at 3x resolution")
        
        # Scan up to 8 pages (increased from 5)
        for page_num in range(min(8, len(doc))):
            if page_num > 0:
                time.sleep(0.5)  # Rate limiting
            
            try:
                page = doc[page_num]
                
                # 3x resolution matrix for sharper rendering (was 2x)
                pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))
                page_img_bytes = pix.tobytes("png")
                pil_image = Image.open(io.BytesIO(page_img_bytes))
                
                prompt = f"""
You are an expert at finding specific product images in PDF documents.

TASK: Find the image/photo for THIS SPECIFIC product: "{target_model}"

⚠️ CRITICAL — MULTIPLE PRODUCTS WARNING:
This page may contain MULTIPLE different products (e.g., a table/catalog with several items side by side).
You MUST identify the CORRECT image that belongs to "{target_model}" specifically.

HOW TO IDENTIFY THE CORRECT PRODUCT:
1. Look for TEXT LABELS near each image — model numbers, product names, descriptions
2. Match those text labels to "{target_model}"
3. The correct image is the one DIRECTLY ADJACENT to or IN THE SAME COLUMN/ROW as the matching text
4. In TABLE LAYOUTS: products are usually in columns. Find the column whose header/label matches "{target_model}", then select the image in that same column
5. Do NOT just pick the largest or most prominent image — pick the one that MATCHES the product name

WHAT A VALID PRODUCT IMAGE LOOKS LIKE:
- A photograph or rendering of the physical product
- Can be a studio shot, lifestyle image, or product in packaging

WHAT TO SKIP:
- Company logos, brand badges, certification marks
- Charts, tables (the data part), text-only sections
- QR codes, barcodes
- Images that belong to a DIFFERENT product on the same page

BOUNDING BOX FORMAT:
Return the bounding box as [ymin, xmin, ymax, xmax] on a 0-1000 scale.
The box should be TIGHT around just the product image, with minimal extra space.

Output JSON:
{{ "found": true, "box_2d": [ymin, xmin, ymax, xmax], "confidence": "high" or "medium" or "low", "matched_label": "the text near the image that helped you identify it" }}
or
{{ "found": false }}
"""

                response = None
                for attempt in range(3):  # Up to 3 attempts
                    try:
                        response = model.generate_content(
                            [prompt, {"mime_type": "image/png", "data": page_img_bytes}],
                            generation_config={"response_mime_type": "application/json"}
                        )
                        break
                    except Exception as e:
                        print(f"    Attempt {attempt+1} failed: {e}")
                        if attempt < 2:
                            time.sleep(1)

                if not response:
                    continue

                result = json.loads(response.text)
                
                if result.get('found') and result.get('box_2d'):
                    confidence = result.get('confidence', 'medium')
                    print(f"  🎯 Product found on page {page_num+1} (confidence: {confidence})")
                    
                    ymin, xmin, ymax, xmax = result['box_2d']
                    width, height = pil_image.size
                    
                    # Convert 0-1000 scale to pixel coordinates
                    left = (xmin / 1000) * width
                    top = (ymin / 1000) * height
                    right = (xmax / 1000) * width
                    bottom = (ymax / 1000) * height
                    
                    # Smart padding (5% of crop dimensions)
                    crop_w = right - left
                    crop_h = bottom - top
                    pad_x = crop_w * 0.05
                    pad_y = crop_h * 0.05
                    left = max(0, left - pad_x)
                    top = max(0, top - pad_y)
                    right = min(width, right + pad_x)
                    bottom = min(height, bottom + pad_y)
                    
                    # Validate crop dimensions
                    final_w = right - left
                    final_h = bottom - top
                    
                    if final_w < 80 or final_h < 80:
                        print(f"    ⚠ Crop too small ({final_w:.0f}x{final_h:.0f}), skipping")
                        continue
                    
                    # Don't accept a crop that's essentially the entire page
                    # (likely means AI couldn't find a specific product)
                    page_area = width * height
                    crop_area = final_w * final_h
                    if crop_area > page_area * 0.85:
                        print(f"    ⚠ Crop covers {crop_area/page_area*100:.0f}% of page — too large, likely no distinct product")
                        continue
                    
                    crop = pil_image.crop((left, top, right, bottom))
                    if crop.mode != 'RGB':
                        crop = crop.convert('RGB')
                    
                    # Validate the crop isn't mostly blank/white
                    if _is_mostly_solid(crop):
                        print(f"    ⚠ Crop is mostly solid/blank, skipping")
                        continue
                    
                    # Save high-quality crop
                    safe_name = secure_filename(target_model)
                    filename = f"visual_{safe_name}_{int(time.time())}.jpg"
                    save_path = os.path.join(upload_folder, filename)
                    crop.save(save_path, quality=95)
                    
                    doc.close()
                    return f"uploads/{filename}"

            except Exception as e:
                print(f"  ⚠ Error on page {page_num}: {e}")
                continue
        
        doc.close()
        return None
        
    except Exception as e:
        print(f"  ⚠ Screenshot scan error: {e}")
        return None


def _ai_pick_best_from_candidates(candidates, target_model, upload_folder):
    """Use AI to select the image that matches a specific product from embedded PDF candidates."""
    try:
        model = genai.GenerativeModel('models/gemini-flash-latest')
        
        prompt = f"""
You are an expert Visual Quality Controller.
Product to match: "{target_model}"

TASK:
Review the attached images (labeled 1 to {len(candidates)}) extracted from a PDF document.
Select the SINGLE image that best represents THIS SPECIFIC product: "{target_model}"

⚠️ IMPORTANT: The PDF may contain images of MULTIPLE DIFFERENT products.
Do NOT just pick the "best looking" image — pick the one that matches "{target_model}".

If you can distinguish between products visually (e.g., a frypan vs a saucepan vs a casserole),
pick the one that matches the product name/description.

PREFER:
- Clear product photos that match the product type described in "{target_model}"
- Large, high-quality images of the actual product

AVOID:
- Images that clearly show a DIFFERENT product type
- Logos, certification marks, brand badges
- Technical diagrams, charts, text blocks

Output JSON:
{{ "best_index": 1 }} or {{ "best_index": "none" }}
"""
        
        content = [prompt]
        for i, candidate in enumerate(candidates):
            # Determine mime type
            ext = candidate.get('ext', 'png')
            mime_map = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg'}
            mime = mime_map.get(ext, 'image/png')
            
            content.append(f"IMAGE {i+1} ({candidate['width']}x{candidate['height']}):")
            content.append({"mime_type": mime, "data": candidate['bytes']})
        
        response = model.generate_content(
            content,
            generation_config={"response_mime_type": "application/json"}
        )
        result = json.loads(response.text)
        best = result.get("best_index")
        
        if best == "none" or best is None:
            print("  🚫 AI found no suitable product image among embedded candidates")
            return None
        
        idx = int(best) - 1  # 1-based to 0-based
        if 0 <= idx < len(candidates):
            return _save_candidate_image(candidates[idx], target_model, upload_folder)
        
    except Exception as e:
        print(f"  ⚠ AI selection from embedded images failed: {e}")
    
    return None


def _save_candidate_image(candidate, target_model, upload_folder):
    """Save an image candidate to disk."""
    try:
        pil_img = Image.open(io.BytesIO(candidate['bytes']))
        if pil_img.mode != 'RGB':
            pil_img = pil_img.convert('RGB')
        
        safe_name = secure_filename(target_model)
        filename = f"visual_{safe_name}_{int(time.time())}.jpg"
        save_path = os.path.join(upload_folder, filename)
        pil_img.save(save_path, quality=95)
        
        print(f"  💾 Saved: {filename} ({candidate['width']}x{candidate['height']})")
        return f"uploads/{filename}"
    except Exception as e:
        print(f"  ⚠ Failed to save candidate image: {e}")
        return None


def _is_mostly_solid(pil_image, threshold=15):
    """
    Check if an image is mostly a single solid color 
    (blank backgrounds, separators, etc.)
    """
    try:
        # Resize to small size for fast analysis
        small = pil_image.resize((50, 50))
        if small.mode != 'RGB':
            small = small.convert('RGB')
        
        stat = ImageStat.Stat(small)
        # Standard deviation across all channels — low = mostly solid
        avg_stddev = sum(stat.stddev) / len(stat.stddev)
        
        return avg_stddev < threshold
    except:
        return False
