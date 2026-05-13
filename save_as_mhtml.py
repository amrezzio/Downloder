import asyncio
import zipfile
import os
import re
import argparse
import shutil
from urllib.parse import urlparse
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

def sanitize_filename(name: str) -> str:
    """Remove invalid characters for filenames."""
    return re.sub(r'[\\/*?:"<>|]', "_", name)

async def save_mhtml(url: str, output_file: str, max_retries: int = 3):
    """
    Save webpage as MHTML using Playwright CDP session.
    Implements retry logic and ignores SSL/HTTP2 errors.
    """
    for attempt in range(1, max_retries + 1):
        try:
            async with async_playwright() as p:
                # Launch browser with special flags to avoid HTTP/2 issues
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-web-security',
                        '--disable-features=IsolateOrigins,site-per-process',
                        '--disable-dev-shm-usage',  # for limited disk space
                        '--disable-gpu'
                    ]
                )
                # Create context with realistic user agent and ignore HTTPS errors
                context = await browser.new_context(
                    ignore_https_errors=True,
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                page = await context.new_page()

                # Navigate with 'load' instead of 'networkidle' (more reliable)
                await page.goto(url, wait_until='load', timeout=60000)

                # Extra wait for dynamic content (adjust if needed)
                await page.wait_for_timeout(3000)

                # Capture MHTML via CDP session
                cdp_session = await page.context.new_cdp_session(page)
                mhtml_data = await cdp_session.send('Page.captureSnapshot')

                # Save to file
                with open(output_file, 'wb') as f:
                    f.write(mhtml_data['data'].encode())

                await browser.close()
                print(f"✅ Successfully saved {url} (attempt {attempt})")
                return  # success

        except (PlaywrightTimeoutError, Exception) as e:
            print(f"⚠️ Attempt {attempt} failed for {url}: {str(e)[:200]}")
            if attempt == max_retries:
                raise  # re-raise the last error
            await asyncio.sleep(5)  # wait before retry

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

    # Create directories
    download_dir = "download"
    os.makedirs(download_dir, exist_ok=True)
    os.makedirs("temp", exist_ok=True)

    mhtml_path = os.path.join("temp", mhtml_filename)
    zip_path = os.path.join(download_dir, zip_filename)

    print(f"Downloading {args.url} → {mhtml_filename}")
    asyncio.run(save_mhtml(args.url, mhtml_path))

    # Create ZIP archive
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.write(mhtml_path, arcname=mhtml_filename)

    # Clean up temporary folder
    shutil.rmtree("temp", ignore_errors=True)

    print(f"✅ Created {zip_path} (contains {mhtml_filename})")

if __name__ == "__main__":
    main()
