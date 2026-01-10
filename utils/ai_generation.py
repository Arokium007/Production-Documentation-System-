"""
AI content generation utilities for PIS System
Handles all Gemini AI-powered content generation
"""

import json
import time
import re
import google.generativeai as genai


def generate_pis_data(file_path, model_name, url_data):
    """Generate single PIS data from uploaded file."""
    # 1. Upload File
    uploaded_file = genai.upload_file(file_path)
    while uploaded_file.state.name == "PROCESSING":
        time.sleep(1)
        uploaded_file = genai.get_file(uploaded_file.name)
    
    # Context Construction
    web_context = ""
    if url_data.get('text'):
        web_context = f"WEBSITE TEXT CONTENT: {url_data['text']}\n\nWEBSITE HTML (For Image URLs): {url_data['html']}"

    model = genai.GenerativeModel('models/gemini-flash-latest')

    prompt = f"""
    You are an expert Product Data Specialist. 
    1. Analyze the uploaded document (Proforma Invoice/Spec Sheet).
    2. Analyze the provided Website Context.
    3. Research details for "{model_name}".
    4. **CRITICAL**: Search the 'WEBSITE HTML' to find the most accurate **Product Image URL** (jpg/png).
    
    {web_context}
    
    Output strictly valid JSON:
    {{
        "header_info": {{
            "product_name": "String",
            "model_number": "String",
            "brand": "String",
            "price_estimate": "String"
        }},
        "found_image_url": "String (URL of the product image found in HTML, or null)",
        "seo_data": {{
            "generated_keywords": "Comma-separated string",
            "meta_title": "Max 60 chars",
            "meta_description": "Max 160 chars",
            "seo_long_description": "2 paragraphs"
        }},
        "range_overview": "2-sentence summary",
        "sales_arguments": ["Point 1", "Point 2", "Point 3", "Point 4", "Point 5"],
        "technical_specifications": {{ "Spec Name": "Value" }},
        "warranty_service": {{ "period": "String", "coverage": "String" }}
    }}
    """
    
    response = model.generate_content(
        [prompt, uploaded_file], 
        generation_config={"response_mime_type": "application/json"}
    )
    return json.loads(response.text)


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

    Also create:
    1. A compelling 1-2 paragraph customer-facing product description
    2. SEO metadata optimized for MAURITIUS market specific keywords
    
    SEO REQUIREMENTS:
    - Keywords MUST focus on Mauritius-specific search terms
    - Include local buying intent keywords like "buy in Mauritius", "Mauritius price", "delivery in Mauritius"
    - Add product category + "Mauritius" combinations
    - Include brand name + location combinations
    - Target both English and common local search patterns
    
    OUTPUT JSON FORMAT:
    {{
        "customer_friendly_description": "Compelling 1-2 paragraph description...",
        "key_features": ["Customer-friendly rewrite of argument 1", "Customer-friendly rewrite of argument 2", ...],
        "seo": {{
            "meta_title": "Product Name | Mauritius (60 chars max)",
            "meta_description": "Compelling description with Mauritius location (160 chars max)",
            "keywords": "product+mauritius, brand+mauritius, buy+mauritius, delivery+mauritius, mauritius price, island-wide, etc."
        }}
    }}
    """
    try:
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        spec_data = json.loads(response.text)
        
        # MANDATORY SAFETY NET: Enforce fallback if AI failed
        if (
            not spec_data.get("key_features")
            or not isinstance(spec_data["key_features"], list)
            or len(spec_data["key_features"]) == 0
        ):
            print("⚠️ AI returned empty/invalid key_features, falling back to PIS sales_arguments")
            spec_data["key_features"] = sales_arguments
        
        return spec_data
        
    except Exception as e:
        print(f"Spec Generation Error: {e}")
        # HARD GUARANTEE: Always return valid structure with PIS data
        return {
            "customer_friendly_description": pis_data.get('seo_data', {}).get('seo_long_description', ''),
            "key_features": sales_arguments,  # Direct 1-to-1 fallback
            "seo": {
                "meta_title": pis_data.get('seo_data', {}).get('meta_title', ''),
                "meta_description": pis_data.get('seo_data', {}).get('meta_description', ''),
                "keywords": pis_data.get('seo_data', {}).get('generated_keywords', '')
            }
        }


def generate_bulk_pis_data(file_path, url_data):
    """Generate bulk PIS data for multiple products."""
    uploaded_file = genai.upload_file(file_path)
    while uploaded_file.state.name == "PROCESSING":
        time.sleep(1)
        uploaded_file = genai.get_file(uploaded_file.name)
    
    web_context = ""
    if url_data.get('text'):
        web_context = f"WEBSITE TEXT CONTENT: {url_data['text']}\n\nWEBSITE HTML (For Image URLs): {url_data['html']}"

    model = genai.GenerativeModel('models/gemini-flash-latest')
    
    prompt = f"""
    You are an expert Product Data Specialist. 
    The uploaded document is a list of products (Invoice/Catalog).
    
    Task:
    1. Identify EVERY unique product model listed.
    2. Use the Website Context to enrich data (Specs, Description).
    3. **CRITICAL**: For each product, search the 'WEBSITE HTML' to find the matching **Image URL**.
    
    {web_context}
    
    Output strictly a JSON LIST of objects:
    [
        {{
            "header_info": {{ "product_name": "...", "model_number": "...", "brand": "...", "price_estimate": "..." }},
            "found_image_url": "String (URL found in HTML, or null)",
            "seo_data": {{ "generated_keywords": "...", "meta_title": "...", "meta_description": "...", "seo_long_description": "..." }},
            "range_overview": "...",
            "sales_arguments": ["..."],
            "technical_specifications": {{ "Spec": "Value" }},
            "warranty_service": {{ "period": "...", "coverage": "..." }}
        }}
    ]
    """
    
    response = model.generate_content(
        [prompt, uploaded_file], 
        generation_config={"response_mime_type": "application/json"}
    )
    return json.loads(response.text)


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
        return json.loads(response.text)
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
