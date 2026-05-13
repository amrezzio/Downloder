import asyncio
import zipfile
import os
import re
import argparse
from urllib.parse import urlparse
from playwright.async_api import async_playwright

def sanitize_filename(name: str) -> str:
    """Remove invalid characters for filenames."""
    return re.sub(r'[\\/*?:"<>|]', "_", name)

async def save_mhtml(url: str, output_file: str):
    """Save webpage as MHTML using Playwright CDP session."""
    async with async_playwright() as p:
        # Launch Chromium (headless)
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox']  
        )
        page = await browser.new_page()
        

        await page.goto(url, wait_until='networkidle')
        
        cdp_session = await page.context.new_cdp_session(page)
        mhtml_data = await cdp_session.send('Page.captureSnapshot')
        
        with open(output_file, 'wb') as f:
            f.write(mhtml_data['data'].encode())
        
        await browser.close()

def main():
    parser = argparse.ArgumentParser(description="Download a webpage as MHTML using Playwright.")
    parser.add_argument("--url", required=True, help="URL of the page to download")
    parser.add_argument("--title", help="Optional title for the output file (without extension)")
    args = parser.parse_args()

    # Determine output filename
    if args.title:
        base_name = sanitize_filename(args.title)
    else:
        parsed = urlparse(args.url)
        path = parsed.path.strip('/').replace('/', '_')
        if path:
            base_name = sanitize_filename(path)
        else:
            base_name = sanitize_filename(parsed.netloc)
        if not base_name:
            base_name = "webpage"

    mhtml_filename = f"{base_name}.mhtml"
    zip_filename = f"{base_name}.zip"

    # Create download directory
    download_dir = "download"
    os.makedirs(download_dir, exist_ok=True)

    # Temporary folder for MHTML
    os.makedirs("temp", exist_ok=True)
    mhtml_path = os.path.join("temp", mhtml_filename)

    print(f"Downloading {args.url} → {mhtml_filename}")
    asyncio.run(save_mhtml(args.url, mhtml_path))

    # Create ZIP inside download folder
    zip_path = os.path.join(download_dir, zip_filename)
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.write(mhtml_path, arcname=mhtml_filename)

    # Cleanup temp
    import shutil
    shutil.rmtree("temp", ignore_errors=True)

    print(f"✅ Created {zip_path} (contains {mhtml_filename})")

if __name__ == "__main__":
    main()
