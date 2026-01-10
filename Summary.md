# J. Kalachand PIS System - Project Summary

This document provides a comprehensive overview of the J. Kalachand Product Information System (PIS), chronicling its development, architectural components, and technical specifications.

## 📅 Chronological Development Summary

1.  **Core Foundation**: Established the Flask application and SQLAlchemy database models (`Product`, `ProductHistory`) to track the lifecycle of products from creation to finalization.
2.  **AI PIS Generation**: Integrated Google Gemini AI to automatically generate comprehensive product descriptions, sales arguments, and technical specifications based on raw product titles or URLs.
3.  **Visual Intelligence**: Implemented a robust image search and validation pipeline using Google Custom Search and AI validation to ensure high-quality product imagery.
4.  **Multi-Stage Workflow**: Developed a structured workflow:
    *   **Marketing**: Drafts PIS.
    *   **Director (PIS Review)**: Approves or requests changes with AI-assisted revisions.
    *   **Web Production**: Optimizes content for SEO and generates specsheets.
    *   **Director (Final Review)**: Validates specsheets before finalizing.
5.  **Code Refactoring**: Migrated business logic from `app.py` into a modular `utils/` package for better maintainability (Image Processing, Scraping, AI Generation, History tracking).
6.  **AI Category Classification**: Implemented a sophisticated 3-level product classification system (Main Category, Sub-Category, Sub-Sub-Category) using a predefined list of 134 combinations matched via AI.
7.  **UX & Reliability Polish**: 
    *   Resolved data persistence issues across JSONB-style fields.
    *   Added visual feedback (Loading Modals) for background AI processes.
    *   Finalized a premium, role-based login and logout system.

---

## 🏗️ Module Overview

| Module | Description |
| :--- | :--- |
| **`app.py`** | Main entry point; handles Flask routing, session management, and access control. |
| **`model.py`** | Defines the database schema for Products, Workflow Stages, and History logs. |
| **`utils/ai_generation.py`** | Interfaces with Gemini AI for PIS, Specsheet, and AI revision logic. |
| **`utils/category_classifier.py`** | Manages hierarchical product classification and matching. |
| **`utils/image_processing.py`** | Handles search, download, and validation of product images. |
| **`utils/history.py`** | Standardized event logging for the workflow audit trail. |
| **`utils/web_scraping.py`** | Extracts raw product metadata from external retailer URLs. |
| **`templates/`** | Jinja2 templates using a modern, responsive design system. |

---

## 🛠️ Technical Stack

-   **Backend**: Python 3.x, Flask (Web Framework).
-   **Database**: SQLite (SQLAlchemy ORM).
-   **Frontend**: Tailwind CSS (Styling), AlpineJS (Interactivity), Vanilla JS.
-   **Deployment**: Compatible with Docker/Easypanel (requires environment variables for API keys).

---

## 📚 Libraries & Dependencies

-   `Flask`: Core web framework.
-   `Flask-SQLAlchemy`: Database ORM.
-   `google-generativeai`: Google Gemini API client.
-   `requests` & `beautifulsoup4`: Web scraping and HTTP requests.
-   `xhtml2pdf` & `PyMuPDF (fitz)`: PDF generation and manipulation.
-   `Pillow (PIL)`: Image processing.
-   `duckduckgo-search` & `playwright`: Alternative search and headless browsing.
-   `python-dotenv`: Environment variable management.

---

## 🔗 APIs Used

1.  **Google Gemini API**: Powering all text generation, SEO optimization, and classification tasks.
2.  **Google Custom Search API**: primary source for product image retrieval.
3.  **DuckDuckGo Search**: Fallback search service for scraping and image sourcing.

---

## 🐳 Docker Structure

*Note: While there is no local Dockerfile in the project root, the system is designed for containerization with the following expected structure:*

-   **Base Image**: `python:3.11-slim`
-   **Dependencies**: Installed via `pip install -r requirements.txt`.
-   **Environment**: Requires `GOOGLE_API_KEY` and `FLASK_SECRET_KEY`.
-   **Persistent Storage**: `/instance` folder for the SQLite database.
-   **Static Assets**: `/static/uploads` for stored product images.
