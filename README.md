# LinkedIn feed engagement (Playwright)

## Level

**Level 2 — completed**  
**Time spent:** ~1h

Playwright logs into LinkedIn, reads the home feed, scores posts, likes the top interesting ones, then drafts (**does not post**) 2–3 comments via a local LLM.

### How posts are chosen

1. Parse feed posts (author + text).
2. Score each post in `linkedin/score.py`:
   - longer / more substantive text scores higher;
   - bonus for interest keywords (`engineering`, `architecture`, `product`, `leadership`, `ai`, `career`);
   - bonus for signal words (`trade-off`, `postmortem`, `lesson`, …);
   - penalty for engagement bait (`comment YES`, `repost if`, …).
3. Like the top-N by score (Level 1).
4. From liked posts, take the top 2–3 by the same score for comment drafts (Level 2).

Posts were ranked based on relevance, technical/business substance, and potential to contribute a meaningful comment rather than generic engagement.

## How to run

```bash
git clone <your-repo-url>
cd playwright

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# fill LINKEDIN_EMAIL and LINKEDIN_PASSWORD
```

### Ollama (required for Level 2 drafts)

If Ollama is not installed yet:

**macOS**

```bash
brew install ollama
# or download the app: https://ollama.com/download
```

**Linux**

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Windows:** install from https://ollama.com/download

Then start the server (skip if the Ollama app is already running), pull the model, and run the agent:

```bash
ollama serve          # leave this running in a separate terminal
ollama pull llama3.2

python main.py --level 2
```

Check that the API is up: `curl http://localhost:11434/api/tags`

Optional overrides in `.env`: `OLLAMA_CHAT_URL`, `OLLAMA_MODEL`.
If Ollama is down, the agent falls back to a simple local draft (still never posted).

Or via env:

```bash
export LINKEDIN_EMAIL="..."
export LINKEDIN_PASSWORD="..."
export LINKEDIN_LEVEL=2

python main.py
```

First run may need interactive 2FA (headless is off by default). Session is saved to `.linkedin_storage.json` (gitignored).

`sample_output.txt` is stdout from one real `--level 2` run against a live feed.

## Design decisions

- **Interesting** = deterministic score, not vibes: substance length + interest keywords + signal words − engagement bait (`linkedin/score.py`).
- **AI:** local Ollama (`llama3.2`). Prompt includes the post text and asks for a short senior-engineer comment (1–3 sentences, no “Great post!”, no emojis/hashtags). Local fallback if Ollama is down.
- **Anti-generic:** drafts are grounded in the post body; scoring prefers posts with enough substance to comment on meaningfully.
- **Automated:** login (with storage state), feed scroll/parse, scoring, likes, draft generation, readable stdout.
- **Not posted:** comments are printed only — never submitted on LinkedIn.
- **Limitations:** LinkedIn DOM/selectors drift; 2FA needs a human once; feed content depends on the account; Ollama must be running for Level 2; some like clicks can time out on promoted/A-B layouts. Level 3 (profile peek) exists in code but is flaky and intentionally not part of this submission.

## Layout

```
main.py
config/
  parsing.yaml          # selectors, parser strategies, pauses
  scoring.yaml          # interestingness rules / weights
  runtime.yaml          # retries, browser, draft providers
linkedin/
  client.py             # facade (browser/auth/feed/like)
  settings.py           # .env + YAML merge
  enums.py / models.py
  resilience.py         # logging, pause, retry
  parsers/              # config-driven strategies + factory
  data/                 # FeedSource / ProfileSource abstraction
  services/             # browser, auth, engagement, draft
  scoring.py            # scoring strategies
  levels.py
sample_output.txt
requirements.txt
.env.example
```

## Architecture notes

Implemented from the earlier “further improvements” list:

- **Config-driven parsing** — `parsers/` builds a chain from `config/parsing.yaml` and returns structured `ParsedCard` / `Post` objects.
- **Externalized rules** — DOM selectors, pauses, scoring patterns, and runtime knobs live in YAML (not hardcoded).
- **Runtime configuration** — `config/runtime.yaml` + `.env` for secrets and overrides (`LINKEDIN_LIKE_TARGET`, `LINKEDIN_COMMENT_PICK`, …).
- **Clearer module boundaries** — Enums, models, services, parsers, data layer; `LinkedIn` is a thin facade.
- **Factory** — `create_feed_parser`, `create_feed_source`, draft/scoring strategy registries.
- **Data-access abstraction** — `FeedSource` / `ProfileSource` isolate business logic from Playwright DOM details.
- **Resilience** — centralized logging + `retry` helper; like attempts and draft provider fallbacks are config-driven.
- **Strategy** — plug in alternate parsers / scoring / draft providers without changing core orchestration.
