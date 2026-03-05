# Moodle Student-Teacher Agent System

Autonomous agents for Moodle using AutoGen + Playwright + LLM-guided UI understanding.

## File Structure

```
.
├── README.md
├── docker-compose.yml
├── .env.example
├── requirements.txt
├── main.py          # CLI entry point
├── agents.py        # Student/Teacher agent flows
├── browser.py       # Playwright wrapper + semantic actions
├── llm.py           # Gemini/Ollama client
└── utils.py         # Helpers (fuzzy match, logging)
```

## Quick Start

### 1. Start Moodle (Docker)

```bash
docker compose up -d
```

Wait ~2-3 minutes for Moodle to initialize. Check status:

```bash
docker compose ps
```

Access Moodle at: **http://127.0.0.1:8080**

Default admin: `user` / `bitnami`

### 2. Setup Moodle (Manual, One-Time)

1. Login as admin
2. Create a course (e.g., "Test Course")
3. Add assignments (use "Online text" submission type)
4. Create student user (e.g., `student1`)
5. Create teacher user (e.g., `teacher1`) and enroll as teacher
6. Enroll student in the course

### 3. Python Setup

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/Mac
source .venv/bin/activate

pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### 4. Configure Environment

```bash
copy .env.example .env
```

Edit `.env` with your credentials and LLM choice.

### 5. Run Agents

**Student Agent** (submits assignments):

```bash
python main.py --agent student
```

**Teacher Agent** (grades submissions):

```bash
python main.py --agent teacher
```

Optional flags:

```bash
python main.py --agent student --headless    # Run without browser UI
python main.py --agent student --debug       # Verbose logging
```

## LLM Configuration

### Option 1: Gemini (Free Tier)

1. Get API key from https://makersuite.google.com/app/apikey
2. Set in `.env`:
   ```
   LLM_PROVIDER=gemini
   GEMINI_API_KEY=your_key_here
   ```

### Option 2: Ollama (Local)

1. Install Ollama: https://ollama.ai
2. Pull a model:
   ```bash
   ollama pull qwen2.5:3b
   ```
3. Set in `.env`:
   ```
   LLM_PROVIDER=ollama
   OLLAMA_MODEL=qwen2.5:3b
   OLLAMA_URL=http://localhost:11434
   ```

## How It Works

1. Agent reads page content (headings, buttons, links, form fields)
2. Sends page summary to LLM
3. LLM returns JSON action plan (click/type targets)
4. Browser executor uses semantic Playwright queries (role/label/text)
5. No hardcoded CSS selectors - LLM decides what to interact with

## Troubleshooting

### Playwright browser not found

```bash
playwright install chromium
```

### Moodle not accessible

```bash
docker compose logs moodle
```

Wait for "moodle is ready" message.

### LLM connection failed

- Gemini: Check API key is valid
- Ollama: Ensure `ollama serve` is running

### Login fails

- Verify credentials in `.env`
- Check user exists in Moodle

### Agent stuck on page

- Run with `--debug` flag to see LLM responses
- Page structure may differ - LLM will adapt

## Notes

- Only handles "Online text" submission type
- Assumes single course enrollment
- Teacher assigns full marks by default
- Agents run independently (no coordination)
