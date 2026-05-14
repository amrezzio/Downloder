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

async def save_mhtml_and_extract_links(url: str, output_mhtml: str, output_links_txt: str, max_retries: int = 3):
    """
    Save webpage as MHTML and extract all <a> href links into a text file.
    """
    for attempt in range(1, max_retries + 1):
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-web-security',
                        '--disable-features=IsolateOrigins,site-per-process',
                        '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage',
                        '--disable-gpu'
                    ]
                )
                context = await browser.new_context(
                    ignore_https_errors=True,
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080}
                )
                page = await context.new_page()

                # Simple stealth
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    window.chrome = { runtime: {} };
                """)

                print(f"🌐 Navigating to {url}...")
                await page.goto(url, wait_until='domcontentloaded', timeout=60000)
                await asyncio.sleep(2)  # initial stabilization

                # Extract all <a> href links
                print("🔗 Extracting all links from the page...")
                links = await page.eval_on_selector_all('a', 'els => els.map(el => el.href)')
                # Filter out empty or non-http(s) links
                links = [link for link in links if link and link.startswith(('http://', 'https://'))]
                # Remove duplicates preserving order
                unique_links = list(dict.fromkeys(links))
                print(f"📌 Found {len(unique_links)} unique links.")

                # Save links to text file
                with open(output_links_txt, 'w', encoding='utf-8') as f:
                    for link in unique_links:
                        f.write(link + '\n')
                print(f"💾 Links saved to {output_links_txt}")

                # Capture MHTML
                print("📸 Taking MHTML snapshot...")
                cdp_session = await page.context.new_cdp_session(page)
                mhtml_data = await cdp_session.send('Page.captureSnapshot')
                with open(output_mhtml, 'wb') as f:
                    f.write(mhtml_data['data'].encode())

                await browser.close()
                print(f"✅ Successfully saved MHTML: {output_mhtml}")
                return True

        except (PlaywrightTimeoutError, Exception) as e:
            print(f"⚠️ Attempt {attempt} failed: {str(e)[:200]}")
            if attempt == max_retries:
                print(f"❌ Failed after {max_retries} attempts.")
                return False
            await asyncio.sleep(5)

def main():
    parser = argparse.ArgumentParser(description="Download webpage as MHTML and extract all links.")
    parser.add_argument("--url", required=True, help="URL of the page to download")
    parser.add_argument("--title", help="Optional title for output files (without extension)")
    args = parser.parse_args()

    # Determine base name
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
    links_filename = f"{base_name}_links.txt"
    zip_filename = f"{base_name}.zip"

    # Create directories
    download_dir = "download"
    os.makedirs(download_dir, exist_ok=True)
    os.makedirs("temp", exist_ok=True)

    mhtml_path = os.path.join("temp", mhtml_filename)
    links_path = os.path.join("temp", links_filename)
    zip_path = os.path.join(download_dir, zip_filename)

    print(f"🚀 Starting: {args.url}")
    success = asyncio.run(save_mhtml_and_extract_links(args.url, mhtml_path, links_path))

    if not success:
        print("❌ Download failed. Exiting.")
        shutil.rmtree("temp", ignore_errors=True)
        sys.exit(1)

    # Create ZIP with both files
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.write(mhtml_path, arcname=mhtml_filename)
        zf.write(links_path, arcname=links_filename)

    # Cleanup
    shutil.rmtree("temp", ignore_errors=True)

    print(f"✅ Completed! Created {zip_path}")
    print(f"   Contains: {mhtml_filename} and {links_filename}")

if __name__ == "__main__":
    import sys
    main()
