# B2 SiteFox

A smart and efficient website content archiving tool, created in the Fox Cities.

## Features

- **Text Content Extraction**
  - Downloads and processes webpage content
  - Removes headers, footers, and navigation elements
  - Creates clean HTML and Markdown versions
  - Generates a table of contents

- **Smart Image Downloading**
  - Optimized for WordPress sites
  - Automatically finds and downloads full-size images
  - Organizes images by page
  - Handles scaled image variants

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/sitefox.git
cd sitefox
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Unix/Mac
# or
venv\Scripts\activate     # On Windows
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

Run the main script:
```bash
python sitefox.py
```

Choose your desired operation:
1. Download page text and create HTML/Markdown versions
2. Download images (optimized for WordPress sites)
3. Download both text and images

Enter the website domain when prompted (e.g., example.com).

## Project Structure

```
sitefox/
├── sitefox.py           # Main entry point
├── sitefox_text/        # Text scraper package
│   ├── __init__.py
│   └── scraper.py
├── sitefox_images/      # Image scraper package
│   ├── __init__.py
│   └── scraper.py
├── downloads/           # All downloaded content is stored here
│   └── domain.com/      # Separate folder for each domain
├── venv/                # Virtual environment (not in repo)
├── requirements.txt     # Dependencies
├── README.md            # Documentation
└── LICENSE              # MIT License
```

## Output Structure

```
sitefox/downloads/domain.com/
├── html/                 # Text content
│   ├── index.html
│   ├── page1.html
│   └── toc.html
├── page1/               # Images by page
│   ├── image1.jpg
│   └── image2.png
├── page2/
│   └── image3.jpg
├── domain.com_content.md
└── sitefox_report.txt
```

## License

MIT License - See LICENSE file for details.

## Author

Created by Brett Belau in the Fox Cities.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. 