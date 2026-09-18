# Actual AI Agent Runner

This is **not** the static atlas from `web/`.

It is a browser UI + Python runtime that executes the real upstream agent implementations from:

`ashishpatel26/500-AI-Agents-Projects/agents/01-...` through `agents/20-...`

The upstream repository is pinned to commit:

`9beeb721c2af551bacaab827a76bddaecaa0ca5e`

The runner does not rewrite the upstream `agent.py` files. It copies the selected agent into an isolated run workspace, passes the same CLI flags documented by that project, executes `python agent.py`, captures stdout/stderr, and exposes any generated files.

## What is actually runnable

The upstream repository currently contains **20 runnable implementations**. The "500+" number refers mainly to the larger catalog of AI-agent use cases/projects in the README, not 500 local runnable `agent.py` folders.

The runner includes all 20 actual implementations:

1. Web Research
2. Code Review
3. PDF Q&A
4. SQL Query
5. Email Drafting
6. News Summarizer
7. GitHub Issue Triager
8. Data Analysis
9. Resume Parser
10. Meeting Notes
11. Stock Research
12. Travel Planner
13. Customer Support
14. Social Media Content
15. Unit Test Generator
16. Documentation Writer
17. Recipe Recommendation
18. Job Application
19. Competitive Analysis
20. Multi-Agent Debate

## API keys

Most agents need `OPENAI_API_KEY`.

Additional keys:

- Web Research: `TAVILY_API_KEY`
- News Summarizer: `NEWS_API_KEY`
- GitHub Issue Triager: `GITHUB_TOKEN` is useful when fetching issues and may be required by GitHub depending on the target/rate limits.

You can set these as server environment variables (recommended), or enter them in the UI for the current browser session.

Set `RUNNER_ACCESS_TOKEN` before exposing the service publicly. When present, the UI asks for that token and the API requires it.

## Deploy: Railway

1. Put this folder in a GitHub repository.
2. Create a Railway project from the repository.
3. Railway detects `railway.json` and the `Dockerfile`.
4. Add `OPENAI_API_KEY` and any optional service keys under Variables.
5. Add `RUNNER_ACCESS_TOKEN` with a strong random value.
6. Deploy.

The Docker image clones and verifies the exact upstream commit during build, then installs the dependency union required by the 20 real agents.

## Deploy: Render

Create a Blueprint from this repository. `render.yaml` defines a Docker web service. Add the API key values when Render prompts for them.

## Local Docker

```bash
docker build -t actual-agent-runner .
docker run --rm -p 8080:8080 \
  -e OPENAI_API_KEY="..." \
  -e TAVILY_API_KEY="..." \
  -e RUNNER_ACCESS_TOKEN="choose-a-password" \
  actual-agent-runner
```

Open `http://localhost:8080`.

## Local without Docker

Use Python 3.11. This installs all upstream dependencies into one environment.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-agents.txt
./scripts/bootstrap.sh upstream
export UPSTREAM_ROOT="$PWD/upstream"
export OPENAI_API_KEY="..."
uvicorn app.main:app --reload --port 8080
```

## Important upstream safety switches

The runner preserves the upstream safety behavior:

- SQL Query defaults to **read-only**. `Allow database writes` maps to upstream `--allow-write` and must be explicitly enabled.
- Data Analysis uses LangChain's pandas agent, which executes model-generated Python. The UI requires explicit opt-in before it passes upstream `--allow-dangerous-code`.
- Uploaded files are copied into a per-run workspace.
- The runner limits uploads and process runtime using `MAX_UPLOAD_MB` and `RUN_TIMEOUT_SECONDS`.

## Why this is not a Netlify-only deployment

Netlify is excellent for static/Vite frontends, but these projects are Python processes with heavier dependencies, file uploads, local SQLite/Pandas operations, and sometimes generated files. A persistent Docker-capable service (Railway, Render, Fly.io, Cloud Run, etc.) is the correct runtime for the actual agents.
