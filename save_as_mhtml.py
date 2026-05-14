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

async def simulate_hover_on_elements(page, selectors=None):
    """
    Simulate mouse hover over interactive elements to trigger dynamic content.
    If selectors not provided, will try common interactive elements.
    """
    if selectors is None:
        # Common interactive elements that may reveal content on hover
        selectors = [
            'button', 'a', '[role="button"]', '[data-hover]', 
            '.dropdown-trigger', '.menu-trigger', '.hover-trigger',
            '.has-dropdown', '.nav-item', '.menu-item',
            '[onmouseenter]', '[onmouseover]'
        ]
    
    print("🖱️ Simulating hover on interactive elements...")
    hovered_count = 0
    for selector in selectors:
        try:
            elements = await page.locator(selector).all()
            for elem in elements:
                try:
                    if await elem.is_visible() and await elem.is_enabled():
                        await elem.hover()
                        hovered_count += 1
                        await asyncio.sleep(0.1)  # small delay for content to appear
                except:
                    pass
        except:
            pass
    print(f"🖱️ Hovered over {hovered_count} elements.")

async def scroll_page(page):
    """Scroll the page gradually to trigger lazy loading."""
    print("📜 Scrolling page to load lazy content...")
    await page.evaluate("""
        async () => {
            const scrollStep = 500;
            const delay = 100;
            let currentScroll = 0;
            const maxScroll = document.body.scrollHeight - window.innerHeight;
            while (currentScroll < maxScroll) {
                window.scrollBy(0, scrollStep);
                currentScroll += scrollStep;
                await new Promise(resolve => setTimeout(resolve, delay));
            }
            // Scroll back to top
            window.scrollTo(0, 0);
        }
    """)
    await asyncio.sleep(1)

async def save_mhtml(url: str, output_file: str, max_retries: int = 3):
    """
    Save webpage as MHTML after simulating user interactions (hover, scroll).
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
                    viewport={'width': 1920, 'height': 1080},
                    locale='en-US',
                    timezone_id='America/New_York'
                )
                page = await context.new_page()

                # Stealth script to hide automation
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    window.chrome = { runtime: {} };
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                """)

                print(f"🌐 Navigating to {url}...")
                await page.goto(url, wait_until='domcontentloaded', timeout=60000)
                await asyncio.sleep(3)  # initial stabilization

                # Scroll to trigger lazy loading
                await scroll_page(page)
                await asyncio.sleep(2)

                # Simulate hover on interactive elements
                await simulate_hover_on_elements(page)
                await asyncio.sleep(2)  # let dynamic content settle

                # One more small scroll to capture any revealed content
                await page.evaluate("window.scrollBy(0, 100);")
                await asyncio.sleep(1)

                print("📸 Taking MHTML snapshot...")
                cdp_session = await page.context.new_cdp_session(page)
                mhtml_data = await cdp_session.send('Page.captureSnapshot')

                with open(output_file, 'wb') as f:
                    f.write(mhtml_data['data'].encode())

                await browser.close()
                print(f"✅ Successfully saved {url} (attempt {attempt})")
                return

        except (PlaywrightTimeoutError, Exception) as e:
            print(f"⚠️ Attempt {attempt} failed for {url}: {str(e)[:200]}")
            if attempt == max_retries:
                raise
            await asyncio.sleep(5)

def main():
    parser = argparse.ArgumentParser(description="Download webpage as MHTML with full dynamic content (hover + scroll).")
    parser.add_argument("--url", required=True, help="URL of the page to download")
    parser.add_argument("--title", help="Optional title for the output file")
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

    download_dir = "download"
    os.makedirs(download_dir, exist_ok=True)
    os.makedirs("temp", exist_ok=True)

    mhtml_path = os.path.join("temp", mhtml_filename)
    zip_path = os.path.join(download_dir, zip_filename)

    print(f"🚀 Starting enhanced download: {args.url}")
    asyncio.run(save_mhtml(args.url, mhtml_path))

    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.write(mhtml_path, arcname=mhtml_filename)

    shutil.rmtree("temp", ignore_errors=True)

    print(f"✅ Completed! File saved at: {zip_path}")

if __name__ == "__main__":
    main()
