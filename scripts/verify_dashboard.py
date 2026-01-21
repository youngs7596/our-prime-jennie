import asyncio
from playwright.async_api import async_playwright
import sys
import os

async def run():
    print("Starting Authenticated Dashboard Audit...")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()
        
        # 1. Login
        try:
            print("🔐 Logging in...")
            await page.goto("http://localhost/login", timeout=10000)
            
            await page.fill("input[type='text'], input[placeholder='Username']", "admin")
            await page.fill("input[type='password']", "q1w2e3R$")
            await page.click("button[type='submit']")
            
            # Wait for navigation to home/overview
            await page.wait_for_url("http://localhost/", timeout=10000)
            print("✅ Login Successful")
            
        except Exception as e:
            print(f"❌ Login Failed: {e}")
            await page.screenshot(path="audit_login_fail.png")
            await browser.close()
            return

        # Helper to audit a page
        async def audit_page(url, name):
            print(f"\n--- Auditing {name} ({url}) ---")
            try:
                await page.goto(url, timeout=10000)
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(2) # Wait for animations/fetches
                
                # Capture Screenshot
                filename = f"audit_{name.lower()}.png"
                await page.screenshot(path=filename)
                print(f"📸 Captured {filename}")
                
                # Dump Text Content
                title = await page.title()
                print(f"   Title: {title}")
                
                # Check specifics based on page
                if name == "Overview":
                    # Check Regimes, Summary Cards
                    cards = page.locator(".rounded-xl") # Assuming card class
                    count = await cards.count()
                    print(f"   Found {count} UI Cards")
                    headers = await page.locator("h1, h2, h3").all_text_contents()
                    print(f"   Headers: {headers}")
                    
                elif name == "Portfolio":
                    # Check Table Headers and Rows
                    await page.wait_for_selector("text=보유 종목", timeout=5000)
                    positions = await page.locator(".group").count() # Assuming position items have 'group' class
                    print(f"   Active Positions visible: {positions}")
                    
                elif name == "Performance":
                    # Check Charts or headers
                    headers = await page.locator("h1, h2").all_text_contents()
                    print(f"   Headers: {headers}")

                # General check for "Not Implemented" or empty states
                body_text = await page.inner_text("body")
                if "No data" in body_text or "Loading" in body_text:
                    print("   ⚠️ Potential Empty/Loading state detected")

            except Exception as e:
                print(f"❌ Error auditing {name}: {e}")

        # 2. Audit Main Pages
        await audit_page("http://localhost/", "Overview")
        await audit_page("http://localhost/portfolio", "Portfolio")
        await audit_page("http://localhost/performance", "Performance") 
        await audit_page("http://localhost/settings", "Settings")
        await audit_page("http://localhost/logs", "Logs") # Guessing URL
        await audit_page("http://localhost/trading", "Trading") # Guessing URL

        await browser.close()
        print("\nAudit Complete.")

if __name__ == "__main__":
    asyncio.run(run())
