"""
Utility functions: fuzzy matching, logging setup, step printer
"""
import logging
import re
from difflib import SequenceMatcher

# Configure logging
def setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("moodle_agent")

logger = setup_logging()

# --------------- Step / LLM I/O printer ---------------

_SEPARATOR = "=" * 70

def print_step(step_name: str, detail: str = ""):
    """Print a prominent step header."""
    print(f"\n{_SEPARATOR}")
    print(f"  STEP: {step_name}")
    if detail:
        print(f"  {detail}")
    print(_SEPARATOR)

def print_llm_io(step_name: str, direction: str, content: str):
    """Print LLM input or output with clear borders."""
    tag = f"[LLM {direction}]"
    border = "-" * 60
    print(f"\n{border}")
    print(f"  {tag}  ({step_name})")
    print(border)
    for line in content.splitlines():
        print(f"  {line}")
    print(border)

# Fuzzy string matching
def fuzzy_match(needle: str, haystack: str, threshold: float = 0.6) -> bool:
    """Check if needle approximately matches haystack."""
    needle = needle.lower().strip()
    haystack = haystack.lower().strip()
    
    # Exact substring match
    if needle in haystack or haystack in needle:
        return True
    
    # Sequence similarity
    ratio = SequenceMatcher(None, needle, haystack).ratio()
    return ratio >= threshold

def find_best_match(target: str, candidates: list[str]) -> str | None:
    """Find the best matching string from candidates."""
    target = target.lower().strip()
    best_match = None
    best_score = 0.0
    
    for candidate in candidates:
        candidate_lower = candidate.lower().strip()
        
        # Exact match
        if target == candidate_lower:
            return candidate
        
        # Substring match (prefer shorter matches)
        if target in candidate_lower:
            score = len(target) / len(candidate_lower)
            if score > best_score:
                best_score = score
                best_match = candidate
            continue
        
        # Fuzzy match
        ratio = SequenceMatcher(None, target, candidate_lower).ratio()
        if ratio > best_score and ratio >= 0.5:
            best_score = ratio
            best_match = candidate
    
    return best_match

def clean_text(text: str) -> str:
    """Clean and normalize text for comparison."""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_text_content(html: str) -> str:
    """Extract visible text content from HTML (simple version)."""
    # Remove script and style tags
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove all tags
    text = re.sub(r'<[^>]+>', ' ', html)
    return clean_text(text)
