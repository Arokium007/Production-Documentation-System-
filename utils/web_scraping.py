"""
Web scraping utilities for PIS System
Handles URL scraping and data extraction
"""

import requests
from bs4 import BeautifulSoup


def scrape_url_data(url):
    """
    Scrapes a URL and returns a dictionary with 'text', 'html', and 'image_candidates'.
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 1. Extract Image Candidates
        image_candidates = []
        # Common noise patterns to exclude
        exclude_patterns = [
            'logo', 'icon', 'facebook', 'instagram', 'twitter', 'linkedin', 'youtube',
            'visa', 'mastercard', 'amex', 'paypal', 'cart', 'search', 'menu', 'arrow',
            'pixel', 'banner', 'ads', 'loading', 'placeholder', '.svg', '.gif'
        ]
        
        for img in soup.find_all('img'):
            # Check multiple potential sources
            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
            if not src:
                continue
                
            # Convert partial URLs to absolute
            if src.startswith('//'):
                src = 'https:' + src
            elif src.startswith('/'):
                from urllib.parse import urljoin
                src = urljoin(url, src)
            elif not src.startswith('http'):
                continue
                
            # Filter by patterns
            src_lower = src.lower()
            if any(p in src_lower for p in exclude_patterns):
                continue
                
            # Filter by alt text/class/id if they contain noise
            alt = (img.get('alt') or '').lower()
            if any(p in alt for p in exclude_patterns):
                continue
                
            if src not in image_candidates:
                image_candidates.append(src)
        
        # Limit to top 20 candidates
        image_candidates = image_candidates[:20]

        # 2. Cleanup Soup for Text
        # Remove scripts/styles for cleaner text
        for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
            script.extract()
            
        text_content = " ".join(soup.get_text(separator=' ').split())[:20000]
        
        # Get raw body for context (limit length)
        html_content = str(soup.body)[:40000] if soup.body else ""
        
        return {
            "text": text_content,
            "html": html_content,
            "image_candidates": image_candidates
        }
    except Exception as e:
        print(f"Scrape Error: {e}")
        return {"text": "", "html": "", "image_candidates": []}
