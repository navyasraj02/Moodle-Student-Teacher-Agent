"""
LLM client: Gemini and Ollama support with verbose I/O logging
"""
import os
import json
import httpx
from typing import Any
from utils import logger, print_llm_io

# --------------- LLM Clients ---------------

class GeminiClient:
    def __init__(self, api_key: str):
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-2.0-flash")

    async def generate(self, prompt: str) -> str:
        response = self.model.generate_content(prompt)
        return response.text


class OllamaClient:
    def __init__(self, model: str, base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    async def generate(self, prompt: str) -> str:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            return resp.json()["response"]


def create_llm_client():
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    if provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set")
        return GeminiClient(api_key)
    elif provider == "ollama":
        model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
        url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        return OllamaClient(model, url)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}")

# --------------- JSON Parsing ---------------

def parse_llm_json(text: str) -> dict[str, Any] | None:
    """Extract JSON object from LLM response (handles code fences)."""
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end > start:
            text = text[start:end]
    elif "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        if end > start:
            text = text[start:end]

    text = text.strip()
    brace_start = text.find("{")
    brace_end = text.rfind("}") + 1
    if brace_start >= 0 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start:brace_end])
        except json.JSONDecodeError:
            pass
    return None

# --------------- Core prompt template ---------------

ANALYZE_PROMPT = """You are a browser automation assistant. You are given the content of a web page and a TASK to perform.

Analyze the page and return a JSON action plan telling the browser what to do NEXT.

PAGE CONTENT:
{page_summary}

TASK: {task}

Return ONLY a JSON object in this format:
{{
  "actions": [
    {{"type": "type", "target": "<label or placeholder text of the field>", "value": "<ACTUAL TEXT TO TYPE>"}},
    {{"type": "click", "target": "<visible text of button or link>"}},
    {{"type": "select", "target": "<label of dropdown>", "value": "<option text>"}},
    {{"type": "navigate", "target": "<url>"}}
  ],
  "done": false,
  "notes": "brief explanation of what you decided"
}}

CRITICAL RULES:
- For "type" actions, you MUST include "value" with the EXACT text to type (get it from the TASK description).
- For "click" actions, "target" is the button/link text visible on the page. No "value" needed.
- "target" must be visible label text, placeholder text, or link text you see on the page. NEVER use CSS selectors or XPath.
- If the task requires typing but no editor is currently visible, first click relevant intermediary controls (for example: Add/Edit/Enable/Toggle/Expand) to reveal the editor, then type.
- Prefer specific controls that directly advance the task (for example: "Edit submission" before "Save changes").
- Set "done": true ONLY when the TASK is fully achieved on the current page.
- Keep actions minimal - only the immediate next step(s).
- Use EXACT text from the page for targets.

EXAMPLE: If TASK says "Fill username with 'john' and password with 'pass123'", return:
{{
  "actions": [
    {{"type": "type", "target": "Username", "value": "john"}},
    {{"type": "type", "target": "Password", "value": "pass123"}},
    {{"type": "click", "target": "Log in"}}
  ],
  "done": false,
  "notes": "Entering credentials and clicking login"
}}
"""


async def analyze_page(llm_client, page_summary: str, task: str, step_name: str = "") -> dict[str, Any]:
    """Send page content to LLM, get back action plan. Logs full I/O."""
    prompt = ANALYZE_PROMPT.format(page_summary=page_summary, task=task)

    print_llm_io(step_name, "INPUT", f"TASK: {task}\n\nPAGE SUMMARY (truncated):\n{page_summary[:1500]}")

    raw = await llm_client.generate(prompt)
    result = parse_llm_json(raw)

    # Retry once on parse failure
    if result is None:
        logger.warning("LLM returned invalid JSON, retrying...")
        raw = await llm_client.generate(prompt + "\n\nIMPORTANT: Return ONLY valid JSON.")
        result = parse_llm_json(raw)

    if result is None:
        result = {"actions": [], "done": False, "notes": "Failed to parse LLM JSON"}

    # Validate: type actions must have "value" field
    actions = result.get("actions", [])
    for action in actions:
        if action.get("type") == "type" and not action.get("value"):
            logger.error(f"LLM returned 'type' action without 'value' field: {action}")
            logger.error("Retrying with explicit value requirement...")
            retry_prompt = (
                prompt
                + f"\n\nERROR: You returned a 'type' action without the 'value' field.\n"
                f"Action was: {action}\n"
                f"You MUST include the 'value' field with the exact text to type (from the TASK).\n"
                f"Please return the corrected JSON."
            )
            raw = await llm_client.generate(retry_prompt)
            result = parse_llm_json(raw) or result
            break

    print_llm_io(step_name, "OUTPUT", json.dumps(result, indent=2))
    return result


async def generate_assignment_response(llm_client, instructions: str) -> str:
    """Ask LLM to draft a short answer for an assignment."""
    prompt = (
        "You are a student completing an assignment. Write a short, appropriate response.\n\n"
        f"ASSIGNMENT INSTRUCTIONS:\n{instructions}\n\n"
        "Write a brief but complete response (2-4 sentences) that addresses the assignment.\n"
        "Respond with ONLY the assignment text, no explanations or markdown."
    )
    print_llm_io("DRAFT ANSWER", "INPUT", f"Instructions:\n{instructions[:600]}")
    raw = await llm_client.generate(prompt)
    answer = raw.strip().strip("`").strip()
    print_llm_io("DRAFT ANSWER", "OUTPUT", answer)
    return answer


async def generate_feedback(llm_client, submission: str) -> str:
    """Ask LLM to write brief grading feedback."""
    prompt = (
        "You are a teacher grading a student's work. Write brief positive feedback.\n\n"
        f"STUDENT SUBMISSION:\n{submission}\n\n"
        "Write 1-2 sentences of encouraging, constructive feedback.\n"
        "Respond with ONLY the feedback text."
    )
    print_llm_io("GRADE FEEDBACK", "INPUT", f"Submission:\n{submission[:600]}")
    raw = await llm_client.generate(prompt)
    feedback = raw.strip()
    print_llm_io("GRADE FEEDBACK", "OUTPUT", feedback)
    return feedback
