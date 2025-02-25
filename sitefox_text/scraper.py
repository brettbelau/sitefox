import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re
import os
from datetime import datetime
from typing import Dict, List, Set, Tuple
import asyncio
import aiohttp
import time
from aiohttp import ClientTimeout
from pathlib import Path

class RateLimiter:
    """Rate limiter to control requests per second"""
    def __init__(self, requests_per_second: float):
        self.rate = 1.0 / requests_per_second
        self.last_request = 0
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        """Wait for rate limit if necessary"""
        async with self._lock:
            now = time.time()
            if now - self.last_request < self.rate:
                await asyncio.sleep(self.rate - (now - self.last_request))
            self.last_request = time.time()

class WebsiteScraper:
    def __init__(self, domain: str, max_concurrent: int = 5, requests_per_second: float = 2.0):
        # Clean up domain input - handle https:// properly
        if domain.startswith("https://") or domain.startswith("http://"):
            self.base_url = domain
            # Extract domain name for directory creation
            self.domain = urlparse(domain).netloc
        else:
            self.domain = domain
            self.base_url = f"https://{domain}"
        
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        self.pages_data: Dict[str, Dict] = {}
        self.pdf_urls: Set[str] = set()
        self.errors: List[str] = []
        self.max_concurrent = max_concurrent
        self.rate_limiter = RateLimiter(requests_per_second)
        
        # Create directory structure
        # Get the script directory
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Create downloads directory if it doesn't exist
        self.downloads_dir = os.path.join(script_dir, "downloads")
        os.makedirs(self.downloads_dir, exist_ok=True)
        
        # Create domain-specific directories
        self.base_dir = os.path.join(self.downloads_dir, self.domain)
        self.html_dir = os.path.join(self.base_dir, "html")
        self.pdf_dir = os.path.join(self.base_dir, "pdfs")
        os.makedirs(self.html_dir, exist_ok=True)
        os.makedirs(self.pdf_dir, exist_ok=True)

    def is_valid_url(self, url: str) -> bool:
        """Check if the URL belongs to the base domain."""
        parsed_base = urlparse(self.base_url)
        parsed_url = urlparse(url)
        return parsed_url.netloc == parsed_base.netloc

    def is_pdf_url(self, url: str) -> bool:
        """Check if the URL points to a PDF file."""
        return url.lower().endswith('.pdf')

    async def get_linked_pages(self, session: aiohttp.ClientSession, url: str) -> Set[str]:
        """Scan the website and return a set of internal linked pages."""
        try:
            await self.rate_limiter.acquire()
            timeout = ClientTimeout(total=30)
            async with session.get(url, headers=self.headers, timeout=timeout) as response:
                response.raise_for_status()
                content = await response.text()
                soup = BeautifulSoup(content, "html.parser")
                
                pages = set()
                for link in soup.find_all("a", href=True):
                    href = link["href"]
                    full_url = urljoin(self.base_url, href)
                    if self.is_valid_url(full_url):
                        if self.is_pdf_url(full_url):
                            self.pdf_urls.add(full_url)
                        elif not re.search(r"\.(png|jpg|jpeg|gif|css|js)$", full_url, re.IGNORECASE):
                            pages.add(full_url)
                return pages
        except Exception as e:
            self.errors.append(f"Error fetching {url}: {e}")
            return set()

    async def download_pdf(self, session: aiohttp.ClientSession, url: str):
        """Download a PDF file from the given URL."""
        try:
            await self.rate_limiter.acquire()
            timeout = ClientTimeout(total=60)  # Longer timeout for PDF downloads
            async with session.get(url, headers=self.headers, timeout=timeout) as response:
                response.raise_for_status()
                content = await response.read()
                
                # Generate filename from URL
                filename = os.path.basename(urlparse(url).path)
                if not filename.lower().endswith('.pdf'):
                    filename += '.pdf'
                
                filepath = os.path.join(self.pdf_dir, filename)
                
                # Save PDF file
                with open(filepath, 'wb') as f:
                    f.write(content)
                print(f"Downloaded PDF: {filename}")
                return filename
        except Exception as e:
            self.errors.append(f"Error downloading PDF {url}: {e}")
            return None

    async def scrape_page_content(self, session: aiohttp.ClientSession, url: str) -> Tuple[str, List[Dict]]:
        """Scrape text content from a page, excluding header/footer."""
        try:
            await self.rate_limiter.acquire()
            timeout = ClientTimeout(total=30)
            async with session.get(url, headers=self.headers, timeout=timeout) as response:
                response.raise_for_status()
                content = await response.text()
                soup = BeautifulSoup(content, "html.parser")

                # Try to find the page title
                title = soup.title.string if soup.title else urlparse(url).path.strip("/").replace("/", "-") or "home"

                # Remove header, footer, nav, and other non-content elements
                for tag in soup.find_all(["header", "footer", "nav", "script", "style"]):
                    tag.decompose()

                # Extract content
                elements = []
                for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "ol"]):
                    if tag.name.startswith('h'):
                        elements.append({
                            "type": "heading",
                            "level": int(tag.name[1]),
                            "content": tag.get_text(strip=True)
                        })
                    elif tag.name == "p":
                        text = tag.get_text(strip=True)
                        if text:  # Only add non-empty paragraphs
                            elements.append({
                                "type": "text",
                                "content": text
                            })
                    elif tag.name in ["ul", "ol"]:
                        items = [li.get_text(strip=True) for li in tag.find_all("li")]
                        if items:  # Only add non-empty lists
                            elements.append({
                                "type": "list",
                                "style": tag.name,
                                "items": items
                            })
                
                return title, elements
        except Exception as e:
            self.errors.append(f"Error scraping {url}: {e}")
            return "", []

    def generate_html_page(self, title: str, elements: List[Dict]) -> str:
        """Generate HTML content for a page."""
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1, h2, h3, h4, h5, h6 {{ color: #333; }}
        p {{ margin-bottom: 1em; }}
        ul, ol {{ margin-bottom: 1em; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
"""
        for element in elements:
            if element["type"] == "heading":
                html += f"<h{element['level']}>{element['content']}</h{element['level']}>\n"
            elif element["type"] == "text":
                html += f"<p>{element['content']}</p>\n"
            elif element["type"] == "list":
                html += f"<{element['style']}>\n"
                for item in element['items']:
                    html += f"    <li>{item}</li>\n"
                html += f"</{element['style']}>\n"
        
        html += "</body>\n</html>"
        return html

    def generate_markdown(self) -> str:
        """Generate a single markdown document containing all pages."""
        markdown = f"# {self.domain} Content\n\n"
        markdown += "## Table of Contents\n\n"
        
        # Add TOC
        for url, data in self.pages_data.items():
            page_name = data['title']
            markdown += f"- [{page_name}](#{page_name.lower().replace(' ', '-')})\n"
        
        markdown += "\n---\n\n"
        
        # Add content
        for url, data in self.pages_data.items():
            markdown += f"# {data['title']}\n\n"
            for element in data['elements']:
                if element["type"] == "heading":
                    markdown += f"{'#' * element['level']} {element['content']}\n\n"
                elif element["type"] == "text":
                    markdown += f"{element['content']}\n\n"
                elif element["type"] == "list":
                    for item in element['items']:
                        markdown += f"- {item}\n"
                    markdown += "\n"
            markdown += "---\n\n"
        
        return markdown

    def generate_toc_html(self) -> str:
        """Generate table of contents HTML file."""
        html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Table of Contents</title>
</head>
<body>
    <h1>Table of Contents</h1>
    <ul>
"""
        for url, data in self.pages_data.items():
            page_filename = self.get_page_filename(url)
            html += f'    <li><a href="{page_filename}">{data["title"]}</a></li>\n'
        
        html += """    </ul>
</body>
</html>"""
        return html

    def get_page_filename(self, url: str) -> str:
        """Generate filename for a page based on its URL."""
        path = urlparse(url).path.strip("/")
        return f"{path or 'index'}.html"

    async def save_files(self):
        """Save all generated files."""
        # Save individual HTML files
        for url, data in self.pages_data.items():
            filename = self.get_page_filename(url)
            filepath = os.path.join(self.html_dir, filename)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            html_content = self.generate_html_page(data["title"], data["elements"])
            
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_content)

        # Save TOC
        toc_path = os.path.join(self.html_dir, "toc.html")
        with open(toc_path, "w", encoding="utf-8") as f:
            f.write(self.generate_toc_html())

        # Save markdown
        markdown_path = os.path.join(self.base_dir, f"{self.domain}_content.md")
        with open(markdown_path, "w", encoding="utf-8") as f:
            f.write(self.generate_markdown())

    def generate_report(self) -> str:
        """Generate a summary report of the scraping process."""
        report = f"""
Scraping Report for {self.domain}
================================
Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Summary:
--------
- Total pages scraped: {len(self.pages_data)}
- Total PDFs found: {len(self.pdf_urls)}
- Output directory: {os.path.abspath(self.base_dir)}
- Files generated:
  - HTML files: {len(self.pages_data)} pages in {self.html_dir}
  - PDFs downloaded: {len(self.pdf_urls)} files in {self.pdf_dir}
  - Table of Contents: {os.path.join(self.html_dir, 'toc.html')}
  - Markdown summary: {self.domain}_content.md

Configuration:
-------------
- Max concurrent requests: {self.max_concurrent}
- Requests per second: {1.0 / self.rate_limiter.rate:.1f}

Pages processed:
--------------
"""
        for url in self.pages_data.keys():
            report += f"✓ {url}\n"

        if self.pdf_urls:
            report += "\nPDFs downloaded:\n---------------\n"
            for url in self.pdf_urls:
                report += f"✓ {url}\n"

        if self.errors:
            report += "\nErrors encountered:\n------------------\n"
            for error in self.errors:
                report += f"! {error}\n"
        else:
            report += "\nNo errors encountered during scraping.\n"

        return report 