"""
AI content generation utilities for PIS System
Handles all Gemini AI-powered content generation
"""

import json
import time
import re
import google.generativeai as genai
from .category_classifier import classify_product_category
from .json_utils import safe_json_loads


def generate_pis_data(file_paths, model_name, url_data):
    """Generate single PIS data from uploaded file(s) and/or website data.
    
    Args:
        file_paths: A single file path string, a list of file paths, or empty list/None.
        model_name: The product model name.
        url_data: Scraped website data dict.
    """
    # Normalize file_paths
    if file_paths is None:
        file_paths = []
    elif isinstance(file_paths, str):
        file_paths = [file_paths]
    
    # 1. Upload files to Gemini (if any)
    uploaded_files = []
    for fp in file_paths:
        if fp:
            uf = genai.upload_file(fp)
            while uf.state.name == "PROCESSING":
                time.sleep(1)
                uf = genai.get_file(uf.name)
            uploaded_files.append(uf)
    
    # Context Construction
    web_context = ""
    image_candidates_str = ""
    if url_data.get('text'):
        web_context = f"WEBSITE TEXT CONTENT: {url_data['text']}\n\nWEBSITE HTML (Partial): {url_data['html']}"
        candidates = url_data.get('image_candidates', [])
        image_candidates_str = "IMAGE CANDIDATES (Ranked by crawler):\n" + "\n".join([f"- {url}" for url in candidates])

    model = genai.GenerativeModel('models/gemini-flash-latest')

    # Build source description based on what's available
    if uploaded_files and web_context:
        source_instruction = f"Analyze ALL {len(uploaded_files)} uploaded document(s) (Proforma Invoices/Spec Sheets) AND the provided Website Context. Cross-reference information across all sources."
    elif uploaded_files:
        source_instruction = f"Analyze ALL {len(uploaded_files)} uploaded document(s) (Proforma Invoices/Spec Sheets) thoroughly."
    else:
        source_instruction = "Analyze the provided Website Context thoroughly. Extract all product details from the website data."

    prompt = f"""
    You are an expert Product Data Specialist and Technical Researcher.
    
    Product to research: {model_name}
    
    TASK:
    1. EXTENSIVE RESEARCH: {source_instruction}
    2. FACTUAL INTEGRITY: Identify specific technical features, performance metrics, and unique selling points.
    3. **STRICT RULES**: 
       - DO NOT invent, assume, or hallucinate any details.
       - If a detail is not in the documents or website context, omit it or state it's unavailable.
       - **INDEPENDENT CONTENT**: This description must be standalone. NEVER refer to other products, model variations, or colors in your text. Each overview must be unique and fully populated.
    4. HERO IMAGE SELECTION:
       - Review the 'IMAGE CANDIDATES' list below.
       - **CRITICAL**: Select the single URL that represents the **HERO SHOT** (main product image).
       - AVOID diagrams, technical drawings, internal components, icons, or secondary gallery thumbnails.
       - If no clear hero shot exists in the list, fallback to searching the 'WEBSITE HTML' for a high-quality img tag.
    
    {image_candidates_str}
    
    {web_context}
    
    Output strictly valid JSON:
    {{
        "header_info": {{
            "product_name": "String",
            "model_number": "String",
            "brand": "String",
            "price_estimate": "String"
        }},
        "found_image_url": "String (Selected Hero Shot URL, or null)",
        "seo_data": {{
            "generated_keywords": "Comma-separated string",
            "meta_title": "Max 60 chars",
            "meta_description": "Max 160 chars",
            "seo_long_description": "2 paragraphs"
        }},
        "range_overview": "A comprehensive 2-4 paragraph technical and marketing overview. Deep-dive into technology, build quality, and use cases as found in the research data.",
        "sales_arguments": ["Point 1", "Point 2", "Point 3", "Point 4", "Point 5"],
        "technical_specifications": {{ "Spec Name": "Value" }},
        "warranty_service": {{ "period": "String", "coverage": "String" }}
    }}
    """
    
    # Build content list: prompt + any uploaded files
    content_parts = [prompt] + uploaded_files
    
    response = model.generate_content(
        content_parts, 
        generation_config={"response_mime_type": "application/json"}
    )
    return safe_json_loads(response.text, fallback={})


def generate_comprehensive_spec_data(pis_data):
    """Generate comprehensive spec sheet data from PIS data."""
    model = genai.GenerativeModel('models/gemini-flash-latest')
    
    # Extract sales arguments for strict prompt
    sales_arguments = pis_data.get('sales_arguments', [])
    
    prompt = f"""
    You are a Senior Marketing Copywriter and SEO Specialist for J. Kalachand, Mauritius.

    SOURCE DATA (PIS sales arguments – factual, internal):
    {json.dumps(sales_arguments)}

    TASK:
    Rewrite EACH sales argument into a customer-friendly, benefit-driven feature.
    
    CRITICAL RULES:
    - Maintain one-to-one mapping (same number of items in, same number out)
    - Do NOT add or remove items
    - Do NOT merge multiple points into one
    - Keep each output item concise and persuasive
    - Focus on customer benefits, not technical specs
    - **FACTUAL INTEGRITY**: Use ONLY the provided source data. Do NOT invent or hallucinate any details.

    Also create:
    1. A detailed 3-4 paragraph customer-facing product description focused on lifestyle benefits and technical excellence.
    2. SEO metadata optimized for MAURITIUS market specific keywords.
    
    SEO REQUIREMENTS:
    - Keywords MUST focus on Mauritius-specific search terms
    - Include local buying intent keywords like "buy in Mauritius", "Mauritius price", "delivery in Mauritius"
    - Add product category + "Mauritius" combinations
    - Include brand name + location combinations
    - Target both English and common local search patterns
    
    OUTPUT JSON FORMAT:
    {{
        "customer_friendly_description": "A detailed 3-4 paragraph persuasive and factual description...",
        "key_features": ["Customer-friendly rewrite of argument 1", "Customer-friendly rewrite of argument 2", ...],
        "internal_web_keywords": "comma-separated list of short keywords for internal website search (e.g., 'fridge, samsung, refrigerator, silver')",
        "seo": {{
            "meta_title": "Product Name | Mauritius (60 chars max)",
            "meta_description": "Compelling description with Mauritius location (160 chars max)",
            "keywords": "product+mauritius, brand+mauritius, buy+mauritius, delivery+mauritius, mauritius price, island-wide, etc."
        }}
    }}
    """
    try:
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        spec_data = safe_json_loads(response.text, fallback={})
        
        # Ensure we have a dict if fallback was used
        if not isinstance(spec_data, dict): spec_data = {}
        
        # MANDATORY SAFETY NET: Enforce fallback if AI failed
        if (
            not spec_data.get("key_features")
            or not isinstance(spec_data["key_features"], list)
            or len(spec_data["key_features"]) == 0
        ):
            print("⚠️ AI returned empty/invalid key_features, falling back to PIS sales_arguments")
            spec_data["key_features"] = sales_arguments
        
        # ADD CATEGORY CLASSIFICATION
        print("\n" + "="*80)
        print("🔄 Starting Category Classification Process...")
        print("="*80)
        
        try:
            categories = classify_product_category(pis_data)
            spec_data["categories"] = categories
            print(f"✅ Categories successfully added to spec_data: {categories}")
        except Exception as e:
            print(f"❌ ERROR in category classification: {e}")
            import traceback
            traceback.print_exc()
            # Add fallback categories even on error
            spec_data["categories"] = {
                "category_1": "Home & Garden",
                "category_2": "Home Deco",
                "category_3": "Lighting"
            }
            print(f"⚠️ Using fallback categories")
        
        print("="*80 + "\n")
        
        return spec_data
        
    except Exception as e:
        print(f"Spec Generation Error: {e}")
        import traceback
        traceback.print_exc()
        
        # HARD GUARANTEE: Always return valid structure with PIS data
        fallback_data = {
            "customer_friendly_description": pis_data.get('seo_data', {}).get('seo_long_description', ''),
            "key_features": sales_arguments,  # Direct 1-to-1 fallback
            "internal_web_keywords": pis_data.get('seo_data', {}).get('generated_keywords', ''),
            "seo": {
                "meta_title": pis_data.get('seo_data', {}).get('meta_title', ''),
                "meta_description": pis_data.get('seo_data', {}).get('meta_description', ''),
                "keywords": pis_data.get('seo_data', {}).get('generated_keywords', '')
            }
        }
        
        # Try to add categories even in fallback
        print("\n🏷️ Attempting category classification in fallback mode...")
        try:
            categories = classify_product_category(pis_data)
            fallback_data["categories"] = categories
            print(f"✅ Categories added successfully in fallback: {categories}")
        except Exception as cat_error:
            print(f"❌ Category classification failed in fallback: {cat_error}")
            # Ultimate fallback categories
            fallback_data["categories"] = {
                "category_1": "Home & Garden",
                "category_2": "Home Deco",
                "category_3": "Lighting"
            }
            print(f"⚠️ Using ultimate fallback categories")
        
        return fallback_data


def generate_bulk_pis_data(file_paths, url_data, product_filter=""):
    """Generate bulk PIS data for multiple products from one or more documents.
    
    Args:
        file_paths: A single file path string, a list of file paths, or empty list/None.
        url_data: Scraped website data dict.
        product_filter: Optional newline-separated string of specific product names/models to extract.
    """
    # Normalize file_paths
    if file_paths is None:
        file_paths = []
    elif isinstance(file_paths, str):
        file_paths = [file_paths]
    
    # Upload all files to Gemini
    uploaded_files = []
    for fp in file_paths:
        if fp:
            uploaded_file = genai.upload_file(fp)
            while uploaded_file.state.name == "PROCESSING":
                time.sleep(1)
                uploaded_file = genai.get_file(uploaded_file.name)
            uploaded_files.append(uploaded_file)
    
    web_context = ""
    image_candidates_str = ""
    if url_data.get('text'):
        web_context = f"WEBSITE TEXT CONTENT: {url_data['text']}\n\nWEBSITE HTML (Partial): {url_data['html']}"
        candidates = url_data.get('image_candidates', [])
        image_candidates_str = "IMAGE CANDIDATES (Ranked by crawler):\n" + "\n".join([f"- {url}" for url in candidates])

    # Build product filter instruction
    product_filter_instruction = ""
    if product_filter:
        filter_lines = [line.strip() for line in product_filter.split('\n') if line.strip()]
        if filter_lines:
            product_list_str = "\n".join([f"- {p}" for p in filter_lines])
            product_filter_instruction = f"""
    **PRODUCT FILTER — CRITICAL**:
    Extract ONLY the following specific products. Ignore all other products in the document/URL:
{product_list_str}
    Match by product name, model number, or any close variation. If a listed product is not found, skip it.
    """

    model = genai.GenerativeModel('models/gemini-flash-latest')
    
    prompt = f"""
    You are an expert Product Data Specialist and Technical Researcher. 
    The uploaded document(s) contain a list of products (Invoice/Catalog).
    Analyze ALL uploaded documents together.
    
    Task:
    1. {"Identify ONLY the specific products listed in the PRODUCT FILTER below." if product_filter_instruction else "Identify EVERY unique product model listed."}
    2. FACTUAL ENRICHMENT: Use the Website Context to identify deep specs and detailed descriptions.
    3. **STRICT ACCURACY**: Do NOT hallucinate or invent features. 
    4. **INDEPENDENT DESCRIPTIONS**: 
       - Each product must have its own standalone, unique, and comprehensive description. 
       - **CRITICAL**: NEVER refer to other products in the list (e.g., AVOID "See Model X for more info" or "Refer to the overview of the cream version"). 
       - Every 'range_overview' must be fully populated with its own unique text, even for simple color variations.
    5. HERO IMAGE SELECTION:
       - For each product, review the 'IMAGE CANDIDATES' list below.
       - **CRITICAL**: Select the single URL that represents the **HERO SHOT** (main product image).
       - AVOID diagrams, technical drawings, internal components, icons, or secondary thumbnails.
    
    {product_filter_instruction}
    
    {image_candidates_str}
    
    {web_context}
    
    Output strictly a JSON LIST of objects:
    [
        {{
            "header_info": {{ "product_name": "...", "model_number": "...", "brand": "...", "price_estimate": "..." }},
            "found_image_url": "String (Selected Hero Shot URL, or null)",
            "seo_data": {{ "generated_keywords": "...", "meta_title": "...", "meta_description": "...", "seo_long_description": "2 paragraphs" }},
            "range_overview": "A comprehensive 2-4 paragraph technical and marketing overview. Deep-dive into technology, build quality, and use cases as found in the research data.",
            "sales_arguments": ["..."],
            "technical_specifications": {{ "Spec": "Value" }},
            "warranty_service": {{ "period": "...", "coverage": "..." }}
        }}
    ]
    """
    
    content_parts = [prompt] + uploaded_files
    
    response = model.generate_content(
        content_parts, 
        generation_config={"response_mime_type": "application/json"}
    )
    return safe_json_loads(response.text, fallback=[])


def generate_specsheet_optimization(product_data):
    """Generate spec sheet optimization suggestions."""
    model = genai.GenerativeModel('models/gemini-flash-latest')
    prompt = f"""
    Review this PIS data: {json.dumps(product_data)}.
    1. Refine 'seo_long_description' for a PDF SpecSheet.
    2. Suggest 5 additional niche keywords.
    3. Verify 'meta_description' < 160 chars.
    Output JSON: {{ "refined_description": "", "long_tail_keywords": "", "final_meta_check": "" }}
    """
    try:
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return safe_json_loads(response.text, fallback={})
    except:
        return {}


def generate_ai_revision(section_name, original_content, director_comment):
    """
    Uses Gemini to rewrite content based on Director's feedback.
    Ensures correct data types:
    - sales_arguments -> List[str]
    - technical_specifications -> Dict[str, str]
    - header_info -> Dict with fixed keys
    - others -> str
    """

    model = genai.GenerativeModel('models/gemini-flash-latest')

    # ---------- FORMAT ENFORCEMENT ----------
    if section_name == "sales_arguments":
        format_instr = (
            "Output MUST be a valid JSON array of strings.\n"
            "Each sales argument MUST be its own list item.\n"
            "Do NOT combine points into sentences.\n"
            "Do NOT return a single string."
        )
    elif isinstance(original_content, list):
        format_instr = "Output a valid JSON array of strings."
    elif isinstance(original_content, dict):
        format_instr = "Output a valid JSON object with key-value pairs."
    else:
        format_instr = "Return plain rewritten text only."

    prompt = f"""
    You are a professional product copywriter.

    TASK:
    Rewrite the following "{section_name}" content based STRICTLY on the Director's feedback.

    ORIGINAL CONTENT:
    {json.dumps(original_content, ensure_ascii=False) if isinstance(original_content, (dict, list)) else original_content}

    DIRECTOR FEEDBACK:
    "{director_comment}"

    RULES:
    - {format_instr}
    - Do NOT include markdown formatting.
    - Do NOT explain anything.
    - Output ONLY the final result.

    IMPORTANT:
    - If section is "sales_arguments", output MUST be a JSON array.
    - If section is "technical_specifications", output MUST be a JSON object.
    - If section is "header_info", keep keys:
      product_name, model_number, brand, price_estimate
    - If section is "seo_optimization", output MUST be a JSON object with keys:
      meta_title, meta_description, keywords, refined_description
    """

    try:
        response = model.generate_content(prompt)
        result = response.text.strip()

        # ---------- CLEAN MARKDOWN ----------
        if result.startswith("```"):
            result = (
                result.replace("```json", "")
                      .replace("```python", "")
                      .replace("```", "")
                      .strip()
            )

        # ---------- PARSING ----------
        try:
            parsed = json.loads(result)

            # ---------- HARD TYPE ENFORCEMENT ----------
            if section_name == "sales_arguments":
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
                return [str(parsed)]

            if isinstance(original_content, dict) and isinstance(parsed, dict):
                return parsed

            if isinstance(original_content, list) and isinstance(parsed, list):
                return parsed

            return parsed

        except Exception:
            # ---------- FAILSAFE FALLBACKS ----------
            if section_name == "sales_arguments":
                # Split common AI separators safely
                return [
                    x.strip()
                    for x in re.split(r'[;\n•\-]', result)
                    if x.strip()
                ]

            if isinstance(original_content, list):
                return [x.strip() for x in result.split("\n") if x.strip()]

            return result

    except Exception as e:
        print(f"AI Revision Error [{section_name}]: {e}")
        return original_content
