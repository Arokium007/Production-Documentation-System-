"""
Web scraping utilities for PIS System
Handles URL scraping and data extraction
"""

import requests
from bs4 import BeautifulSoup


def scrape_url_data(url):
    """
    Scrapes a URL and returns a dictionary with 'text' and 'html_context'.
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove scripts/styles for cleaner text
        for script in soup(["script", "style", "nav", "footer"]):
            script.extract()
            
        text_content = " ".join(soup.get_text(separator=' ').split())[:20000]
        
        # Get raw body for image searching (limit length)
        html_content = str(soup.body)[:50000] if soup.body else ""
        
        return {
            "text": text_content,
            "html": html_content
        }
    except Exception as e:
        print(f"Scrape Error: {e}")
        return {"text": "", "html": ""}
