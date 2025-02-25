import os
import asyncio
import aiohttp
from typing import Optional
import sys
from datetime import datetime

# Import our scrapers
from sitefox_text.scraper import WebsiteScraper
from sitefox_images.scraper import WordPressImageScraper

WELCOME_MESSAGE = """
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║                    Welcome to B2 SiteFox!                    ║
║                                                              ║
║           The smart way to archive website content           ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝

Version 1.0.0
Created by Brett Belau in the Fox Cities
"""

MENU = """
Please choose what you'd like to do:

1. Download page text and create HTML/Markdown versions
2. Download images (optimized for WordPress sites)
3. Download both text and images

Enter your choice (1-3): """

async def process_domain(domain: str, choice: int) -> None:
    """Process the domain according to user's choice."""
    # Clean up domain input - handle https:// properly
    if domain.startswith("https://https://"):
        domain = domain.replace("https://https://", "https://")
    elif not domain.startswith("https://") and not domain.startswith("http://"):
        domain = f"https://{domain}"
    
    # Remove trailing slash
    domain = domain.rstrip("/")
    
    # Extract just the domain name for directory creation
    domain_name = domain.replace("https://", "").replace("http://", "")
    
    # Ensure downloads directory exists
    script_dir = os.path.dirname(os.path.abspath(__file__))
    downloads_dir = os.path.join(script_dir, "downloads")
    os.makedirs(downloads_dir, exist_ok=True)
    
    # Set base directory for this domain
    base_dir = os.path.join(downloads_dir, domain_name)
    os.makedirs(base_dir, exist_ok=True)

    print(f"\nProcessing {domain}...")
    
    text_scraper: Optional[WebsiteScraper] = None
    image_scraper: Optional[WordPressImageScraper] = None

    if choice in [1, 3]:
        print("\n[Text Scraper]")
        text_scraper = WebsiteScraper(domain)
        
    if choice in [2, 3]:
        print("\n[Image Scraper]")
        image_scraper = WordPressImageScraper(domain)

    # Create shared session for all operations
    async with aiohttp.ClientSession() as session:
        # Process text content if selected
        if text_scraper:
            print("Scanning for pages...")
            pages = await text_scraper.get_linked_pages(session, text_scraper.base_url)
            pages.add(text_scraper.base_url)
            print(f"Found {len(pages)} pages to process.")

            tasks = []
            for page_url in pages:
                tasks.append(text_scraper.scrape_page_content(session, page_url))

            for i in range(0, len(tasks), text_scraper.max_concurrent):
                chunk = tasks[i:i + text_scraper.max_concurrent]
                results = await asyncio.gather(*chunk)
                
                for page_url, (title, elements) in zip(list(pages)[i:i + text_scraper.max_concurrent], results):
                    if elements:
                        text_scraper.pages_data[page_url] = {
                            "title": title,
                            "elements": elements
                        }
                        print(f"Scraped text: {page_url}")

            print("\nGenerating text files...")
            await text_scraper.save_files()

        # Process images if selected
        if image_scraper:
            print("\nScanning for images...")
            pages = await image_scraper.get_linked_pages(session, image_scraper.base_url)
            pages.add(image_scraper.base_url)
            print(f"Found {len(pages)} pages to check for images.")

            tasks = []
            for page_url in pages:
                tasks.append(image_scraper.find_images_on_page(session, page_url))

            for i in range(0, len(tasks), image_scraper.max_concurrent):
                chunk = tasks[i:i + image_scraper.max_concurrent]
                await asyncio.gather(*chunk)

            # Download found images
            print("\nDownloading images...")
            for page_name, image_urls in image_scraper.images.items():
                if not image_urls:
                    continue
                    
                tasks = []
                for img_url in image_urls:
                    tasks.append(image_scraper.download_image(session, img_url, page_name))

                for i in range(0, len(tasks), image_scraper.max_concurrent):
                    chunk = tasks[i:i + image_scraper.max_concurrent]
                    await asyncio.gather(*chunk)

    # Generate final report
    report = "Combined Scraping Report\n=====================\n\n"
    report += f"Domain: {domain}\n"
    report += f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    if text_scraper:
        report += "Text Content Summary:\n------------------\n"
        report += f"Pages processed: {len(text_scraper.pages_data)}\n"
        report += f"Output directory: {os.path.abspath(text_scraper.html_dir)}\n\n"

    if image_scraper:
        report += "Image Summary:\n-------------\n"
        total_images = sum(len(images) for images in image_scraper.images.values())
        report += f"Total images found: {total_images}\n"
        report += f"Output directory: {os.path.abspath(image_scraper.base_dir)}\n\n"

    # Save combined report
    report_path = os.path.join(base_dir, "sitefox_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nReport saved to: {report_path}")

async def main():
    # Clear screen
    os.system('cls' if os.name == 'nt' else 'clear')
    
    # Show welcome message
    print(WELCOME_MESSAGE)
    
    # Get user choice
    while True:
        try:
            choice = int(input(MENU))
            if choice not in [1, 2, 3]:
                print("Please enter 1, 2, or 3")
                continue
            break
        except ValueError:
            print("Please enter a valid number")
    
    # Get domain
    domain = input("\nEnter the website domain (e.g., example.com): ")
    
    try:
        await process_domain(domain, choice)
        print("\nProcessing complete! Check the report file for details.")
    except Exception as e:
        print(f"\nError: {e}")
        print("Please check your domain name and internet connection.")
    
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    asyncio.run(main()) 