"""
Playwright browser wrapper with semantic element location (no hardcoded selectors)
"""
import asyncio
from playwright.async_api import async_playwright, Page, Browser, Playwright
from utils import fuzzy_match, find_best_match, logger

class BrowserController:
    def __init__(self, headless: bool = False):
        self.headless = headless
        self.playwright: Playwright = None
        self.browser: Browser = None
        self.page: Page = None
    
    async def start(self):
        """Launch browser and create page."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self.page = await self.browser.new_page()
        self.page.set_default_timeout(15000)
        logger.info("Browser started")
    
    async def close(self):
        """Close browser."""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("Browser closed")
    
    async def navigate(self, url: str):
        """Navigate to URL."""
        logger.info(f"Navigating to: {url}")
        await self.page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(1)  # Brief wait for dynamic content
    
    async def get_page_summary(self) -> str:
        """Extract page content summary for LLM (no selectors exposed)."""
        url = self.page.url
        title = await self.page.title()
        
        # Get visible text content (headings, buttons, links)
        headings = await self._get_text_list("h1, h2, h3, h4")
        buttons = await self._get_text_list("button, input[type='submit'], input[type='button'], [role='button']")
        links = await self._get_text_list("a")
        
        # Get form fields with labels/placeholders
        fields = await self._get_form_fields()

        # Get richer interactive control descriptors (handles icon/toggle buttons)
        controls = await self._get_interactive_descriptions()
        
        # Get main content text (truncated)
        main_text = await self._get_main_text()
        
        summary = f"""URL: {url}
Title: {title}

HEADINGS:
{chr(10).join(f'- {h}' for h in headings[:10]) or '(none)'}

BUTTONS:
{chr(10).join(f'- {b}' for b in buttons[:10]) or '(none)'}

LINKS:
{chr(10).join(f'- {l}' for l in links[:20]) or '(none)'}

FORM FIELDS:
{chr(10).join(f'- {f}' for f in fields[:15]) or '(none)'}

INTERACTIVE CONTROLS:
{chr(10).join(f'- {c}' for c in controls[:25]) or '(none)'}

PAGE CONTENT (excerpt):
{main_text[:1500]}
"""
        return summary

    async def _get_interactive_descriptions(self) -> list[str]:
        """Describe clickable controls using text + aria/title/value cues."""
        elements = await self.page.query_selector_all(
            "button, [role='button'], a, input[type='button'], input[type='submit']"
        )
        results = []
        for el in elements:
            try:
                text = (await el.inner_text() or "").strip()
                aria_label = (await el.get_attribute("aria-label") or "").strip()
                title = (await el.get_attribute("title") or "").strip()
                value = (await el.get_attribute("value") or "").strip()
                role = (await el.get_attribute("role") or "").strip()

                parts = [p for p in [text, aria_label, title, value] if p]
                if parts:
                    desc = " | ".join(dict.fromkeys(parts))
                    if role:
                        desc = f"{desc} ({role})"
                    if len(desc) < 140:
                        results.append(desc)
            except:
                pass
        return list(dict.fromkeys(results))
    
    async def _get_text_list(self, selector: str) -> list[str]:
        """Get visible text from elements (internal helper)."""
        elements = await self.page.query_selector_all(selector)
        texts = []
        for el in elements:
            try:
                text = await el.inner_text()
                text = text.strip()
                if text and len(text) < 100:
                    texts.append(text)
            except:
                pass
        return list(dict.fromkeys(texts))  # Remove duplicates while preserving order
    
    async def _get_form_fields(self) -> list[str]:
        """Get form field descriptions (label, placeholder, name)."""
        fields = []
        
        # Input and textarea elements
        inputs = await self.page.query_selector_all("input:not([type='hidden']):not([type='submit']):not([type='button']), textarea, select")
        for inp in inputs:
            try:
                # Try to get identifying info
                placeholder = await inp.get_attribute("placeholder") or ""
                name = await inp.get_attribute("name") or ""
                input_type = await inp.get_attribute("type") or "text"
                aria_label = await inp.get_attribute("aria-label") or ""
                
                # Try to find associated label
                input_id = await inp.get_attribute("id")
                label_text = ""
                if input_id:
                    label = await self.page.query_selector(f"label[for='{input_id}']")
                    if label:
                        label_text = await label.inner_text()
                
                desc = label_text or aria_label or placeholder or name
                if desc:
                    desc = desc.strip()
                    if input_type not in ["text", "textarea"]:
                        desc = f"{desc} ({input_type})"
                    fields.append(desc)
            except:
                pass
        
        return fields
    
    async def _get_main_text(self) -> str:
        """Get main page text content."""
        try:
            # Try main content area first
            main = await self.page.query_selector("main, [role='main'], #content, .content, #region-main")
            if main:
                return (await main.inner_text())[:2000]
            # Fallback to body
            return (await self.page.inner_text("body"))[:2000]
        except:
            return ""
    
    # Semantic action methods (no hardcoded selectors)
    
    async def click(self, target: str) -> bool:
        """Click element by visible text/label using semantic queries."""
        logger.info(f"Clicking: {target}")
        
        # Try multiple semantic strategies
        strategies = [
            lambda: self.page.get_by_role("button", name=target).click(),
            lambda: self.page.get_by_role("link", name=target).click(),
            lambda: self.page.get_by_text(target, exact=False).first.click(),
            lambda: self.page.get_by_role("menuitem", name=target).click(),
            lambda: self.page.get_by_label(target).click(),
            lambda: self.page.locator(f"[aria-label*='{target}']").first.click(),
            lambda: self.page.locator(f"[title*='{target}']").first.click(),
            lambda: self._fuzzy_click(target),
        ]
        
        for strategy in strategies:
            try:
                await strategy()
                await asyncio.sleep(0.5)
                return True
            except:
                continue
        
        logger.warning(f"Could not click: {target}")
        return False
    
    async def _fuzzy_click(self, target: str):
        """Fuzzy text matching click as fallback."""
        # Get all clickable elements
        elements = await self.page.query_selector_all("a, button, [role='button'], input[type='submit']")
        
        texts = []
        for el in elements:
            try:
                text = (await el.inner_text()).strip()
                if text:
                    texts.append((text, el))
            except:
                pass
        
        # Find best match
        target_lower = target.lower()
        for text, el in texts:
            if fuzzy_match(target_lower, text.lower()):
                await el.click()
                return
        
        raise Exception(f"No fuzzy match found for: {target}")
    
    async def type_text(self, target: str, value: str) -> bool:
        """Type text into field identified by label/placeholder."""
        logger.info(f"Typing into '{target}': {value[:30]}...")
        
        # Try multiple semantic strategies
        strategies = [
            lambda: self.page.get_by_label(target).fill(value),
            lambda: self.page.get_by_placeholder(target).fill(value),
            lambda: self.page.get_by_role("textbox", name=target).fill(value),
            lambda: self._fuzzy_type(target, value),
        ]
        
        for strategy in strategies:
            try:
                await strategy()
                return True
            except:
                continue
        
        logger.warning(f"Could not type into: {target}")
        return False
    
    async def _fuzzy_type(self, target: str, value: str):
        """Fuzzy field matching as fallback."""
        inputs = await self.page.query_selector_all("input:not([type='hidden']):not([type='submit']), textarea")
        
        for inp in inputs:
            try:
                placeholder = await inp.get_attribute("placeholder") or ""
                name = await inp.get_attribute("name") or ""
                aria_label = await inp.get_attribute("aria-label") or ""
                
                # Get label text
                input_id = await inp.get_attribute("id")
                label_text = ""
                if input_id:
                    label = await self.page.query_selector(f"label[for='{input_id}']")
                    if label:
                        label_text = await label.inner_text()
                
                # Check for match
                for candidate in [label_text, placeholder, name, aria_label]:
                    if candidate and fuzzy_match(target.lower(), candidate.lower()):
                        await inp.fill(value)
                        return
            except:
                pass
        
        raise Exception(f"No field match found for: {target}")
    
    async def select_option(self, target: str, value: str) -> bool:
        """Select a dropdown option by label/text."""
        logger.info(f"Selecting '{value}' in '{target}'")
        strategies = [
            lambda: self.page.get_by_label(target).select_option(label=value),
            lambda: self.page.get_by_role("combobox", name=target).select_option(label=value),
        ]
        for strategy in strategies:
            try:
                await strategy()
                return True
            except:
                continue
        logger.warning(f"Could not select '{value}' in '{target}'")
        return False

    async def extract_links(self, keyword: str = "") -> list[dict]:
        """Extract links, optionally filtered by keyword."""
        links = await self.page.query_selector_all("a")
        results = []
        
        for link in links:
            try:
                text = (await link.inner_text()).strip()
                href = await link.get_attribute("href") or ""
                
                if text and href:
                    # Filter by keyword if provided
                    if keyword:
                        if keyword.lower() in text.lower() or keyword.lower() in href.lower():
                            results.append({"text": text, "href": href})
                    else:
                        results.append({"text": text, "href": href})
            except:
                pass
        
        return results
    
    async def execute_actions(self, actions: list[dict]) -> bool:
        """Execute a list of actions from LLM."""
        for action in actions:
            action_type = action.get("type", "")
            target = action.get("target", "")
            value = action.get("value", "")
            
            success = False
            
            # Log the action with full details
            if action_type == "type":
                if not value:
                    logger.error(f"  -> {action_type}({target!r}, <MISSING VALUE>)")
                    logger.error(f"  Full action dict: {action}")
                    return False
                else:
                    logger.info(f"  -> {action_type}({target!r}, {value!r})")
            else:
                logger.info(f"  -> {action_type}({target!r}" + (f", {value!r})" if value else ")"))

            if action_type == "click":
                success = await self.click(target)
            elif action_type == "type":
                success = await self.type_text(target, value)
            elif action_type == "select":
                success = await self.select_option(target, value)
            elif action_type == "wait":
                wait_seconds = 2
                if value:
                    try:
                        wait_seconds = max(1, int(value))
                    except:
                        wait_seconds = 2
                await asyncio.sleep(wait_seconds)
                success = True
            elif action_type == "navigate":
                await self.navigate(target)
                success = True
            else:
                logger.warning(f"Unknown action type: {action_type}")
            
            if not success:
                return False
            
            await asyncio.sleep(0.5)  # Brief pause between actions
        
        return True

    async def is_editor_visible(self) -> bool:
        """Check if any text input editor is currently visible and usable."""
        try:
            contenteditable = self.page.locator("[contenteditable='true']:visible")
            if await contenteditable.count() > 0:
                return True
            textareas = self.page.locator("textarea:visible")
            if await textareas.count() > 0:
                return True
            textboxes = self.page.get_by_role("textbox")
            if await textboxes.count() > 0:
                return True
        except:
            pass
        return False
    
    async def wait_for_load(self):
        """Wait for page to finish loading."""
        try:
            await self.page.wait_for_load_state("networkidle", timeout=10000)
        except:
            pass  # Timeout is ok, page may have continuous activity
        await asyncio.sleep(1)
    
    async def get_current_url(self) -> str:
        """Get current page URL."""
        return self.page.url
    
    async def has_text(self, text: str) -> bool:
        """Check if page contains text."""
        content = await self.page.content()
        return text.lower() in content.lower()
