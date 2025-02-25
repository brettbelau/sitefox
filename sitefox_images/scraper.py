import asyncio
import aiohttp
import os
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import re
from typing import Set, List, Dict
import time
from aiohttp import ClientTimeout
from pathlib import Path
import mimetypes

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

class WordPressImageScraper:
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
        self.pages: Dict[str, str] = {}  # URL to page name mapping
        self.images: Dict[str, Set[str]] = {}  # Page name to image URLs mapping
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
        os.makedirs(self.base_dir, exist_ok=True)

    def is_valid_url(self, url: str) -> bool:
        """Check if the URL belongs to the base domain."""
        parsed_base = urlparse(self.base_url)
        parsed_url = urlparse(url)
        return parsed_url.netloc == parsed_base.netloc

    def get_page_name(self, url: str) -> str:
        """Generate a clean page name from URL."""
        path = urlparse(url).path.strip("/")
        return path if path else "home"

    def get_full_size_url(self, url: str) -> str:
        """Convert WordPress scaled image URL to full size URL."""
        # Pattern to match WordPress scaled image dimensions
        pattern = r'-\d+x\d+\.(jpg|jpeg|png|gif)$'
        
        # Try to remove dimensions from filename
        base_url = re.sub(pattern, r'.\1', url)
        return base_url

    async def check_image_exists(self, session: aiohttp.ClientSession, url: str) -> bool:
        """Check if an image URL is accessible."""
        try:
            async with session.head(url, headers=self.headers, timeout=ClientTimeout(total=10)) as response:
                return response.status == 200
        except:
            return False

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
                    if self.is_valid_url(full_url) and not re.search(r"\.(jpg|jpeg|png|gif|pdf|css|js)$", full_url, re.IGNORECASE):
                        pages.add(full_url)
                return pages
        except Exception as e:
            self.errors.append(f"Error fetching {url}: {e}")
            return set()

    async def find_images_on_page(self, session: aiohttp.ClientSession, url: str):
        """Find and process images on a page."""
        try:
            await self.rate_limiter.acquire()
            timeout = ClientTimeout(total=30)
            async with session.get(url, headers=self.headers, timeout=timeout) as response:
                response.raise_for_status()
                content = await response.text()
                soup = BeautifulSoup(content, "html.parser")

                # Remove header, footer, nav, and other non-content elements
                for tag in soup.find_all(["header", "footer", "nav", "aside", ".sidebar"]):
                    tag.decompose()

                # Get page name for directory
                page_name = self.get_page_name(url)
                self.pages[url] = page_name
                self.images[page_name] = set()

                # Find all images in content
                for img in soup.find_all("img"):
                    src = img.get("src", "")
                    if not src:
                        continue

                    # Convert to absolute URL
                    img_url = urljoin(self.base_url, src)
                    if not self.is_valid_url(img_url):
                        continue

                    # Check if it's a WordPress scaled image
                    if re.search(r'-\d+x\d+\.(jpg|jpeg|png|gif)$', img_url, re.IGNORECASE):
                        full_size_url = self.get_full_size_url(img_url)
                        # Check if full-size image exists
                        if await self.check_image_exists(session, full_size_url):
                            self.images[page_name].add(full_size_url)
                        else:
                            self.images[page_name].add(img_url)
                    else:
                        self.images[page_name].add(img_url)

                print(f"Found {len(self.images[page_name])} images on {url}")

        except Exception as e:
            self.errors.append(f"Error processing images on {url}: {e}")

    async def download_image(self, session: aiohttp.ClientSession, url: str, page_name: str):
        """Download an image and save it to the appropriate directory."""
        try:
            await self.rate_limiter.acquire()
            timeout = ClientTimeout(total=60)
            async with session.get(url, headers=self.headers, timeout=timeout) as response:
                response.raise_for_status()
                content = await response.read()

                # Create directory for page if it doesn't exist
                page_dir = os.path.join(self.base_dir, page_name)
                os.makedirs(page_dir, exist_ok=True)

                # Generate filename from URL
                filename = os.path.basename(urlparse(url).path)
                if not filename:
                    # Generate filename from URL hash if no filename in URL
                    ext = mimetypes.guess_extension(response.headers.get("content-type", ""))
                    filename = f"image_{hash(url)}{ext if ext else '.jpg'}"

                filepath = os.path.join(page_dir, filename)
                
                # Save image
                with open(filepath, 'wb') as f:
                    f.write(content)
                print(f"Downloaded: {filename}")
                return filename
        except Exception as e:
            self.errors.append(f"Error downloading image {url}: {e}")
            return None

    def generate_report(self) -> str:
        """Generate a summary report of the image scraping process."""
        total_images = sum(len(images) for images in self.images.values())
        
        report = f"""
Image Scraping Report for {self.domain}
=====================================
Summary:
--------
- Total pages processed: {len(self.pages)}
- Total images found: {total_images}
- Output directory: {os.path.abspath(self.base_dir)}

Images by page:
-------------
"""
        for page_name, images in self.images.items():
            report += f"\n{page_name} ({len(images)} images):\n"
            for img_url in images:
                report += f"  ✓ {img_url}\n"

        if self.errors:
            report += "\nErrors encountered:\n------------------\n"
            for error in self.errors:
                report += f"! {error}\n"
        else:
            report += "\nNo errors encountered during scraping.\n"

        return report 