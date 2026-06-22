# AI Incident Resolution Agent

A FastAPI and LangGraph service that turns a production incident into a documented, tested, locally committed
remediation in an existing Employee Portal repository. It searches Parcle memory, uses Groq for evidence-based
analysis and implementation planning, delegates the edit to Enter Pro, validates the result, records an audit trail,
and can push an incident branch plus open a pull request when GitHub settings are configured.

## Project Resources

- Employee Tracker repository: [bokadaman07-design/employee_portal.git](https://github.com/bokadaman07-design/employee_portal.git)
- Shared project artifacts: [Google Drive folder](https://drive.google.com/drive/folders/14Uk6PaZL537_fRwhSys6pTKqqoG3Xg2R?usp=drive_link)

## Workflow

```mermaid
flowchart TD
    A[Receive incident] --> B[Search Parcle memory]
    B --> C{Groq classifies request}
    C -->|information| L[Return Parcle-backed answer]
    C -->|code change| D[Analyze with Groq]
    D --> E[Generate Enter Pro prompt]
    E --> F[Create incident branch]
    F --> G[Execute Enter Pro]
    G --> H[Validate changed files and tests]
    H --> I[Repair validation once if needed]
    I --> J[Append decision log]
    J --> K[Sync decision to Parcle]
    K --> M[Commit locally]
    M --> N[Push branch]
    N --> O[Create pull request]
    O --> P[Return summary]
```

Each node is small and dependency-injected. External systems live under `app/integrations`, Pydantic boundary
models under `app/models`, prompt policy under `app/prompts`, and the extensible graph state under `app/graph`.

Parcle is the repository memory layer. The one-time seed command uploads Markdown files from `PARCLE_MEMORY_DIR`
inside the target repo with `client.ingest_file(...)`. If that folder does not exist yet, the script falls back to
root-level `README.md`, `API_DOCUMENTATION.md`, and `PARCLE_MEMORY.md`. Each successful incident report is saved back
under `PARCLE_MEMORY_DIR/incidents/` and ingested into Parcle. At runtime, every user request searches Parcle first; Groq then
decides from the request plus Parcle response whether this is an informational answer or a repo-level code change.
Enter is called only for repo-level code-change requests.

Produck can also act as an input source. The agent connects to Produck's MCP server, discovers available tools,
searches visible open feedback tickets with `search_feedback`, fetches full ticket contents with `get_feedback`,
writes `agent_payload.json` and `agent_brief.md` under `PRODUCK_OUTPUT_DIR`, stores the ticket context in Parcle,
asks Groq to normalize the feedback into an incident request, and then invokes the same LangGraph flow used by
Swagger. The scheduler dedupes feedback by fingerprint in `PRODUCK_STATE_PATH`, so unchanged tickets are not
reprocessed on every poll.

## Configuration

Copy `.env.example` to `.env` and provide the real Parcle, Groq, Enter Pro, and Employee Portal values. Important:

- `EMPLOYEE_PORTAL_PATH` must point to an existing local Git repository.
- `PARCLE_MEMORY_DIR` defaults to `docs/parcle_memory`; repo docs and incident reports stored there are committed and can sync through GitHub.
- `VALIDATION_COMMAND` is run inside that repository after Enter Pro edits it.
- `REQUIRE_CLEAN_TARGET_REPO` defaults to `false`, allowing the workflow to continue from prior incident edits that are still uncommitted.
- `ENABLE_GIT_PUSH=true` pushes the incident branch after commit.
- `GITHUB_TOKEN` or `GH_TOKEN` is required to create a pull request. Fine-grained GitHub tokens need repository
  access to the Employee Portal repo plus `Contents: Read and write` and `Pull requests: Read and write`.
- `GITHUB_BASE_BRANCH` defaults to `main`.
- `PRODUCK_MCP_TOKEN` is required for Produck MCP access.
- `PRODUCK_POLL_ENABLED=true` starts the background Produck poller.
- `PRODUCK_POLL_INTERVAL_SECONDS=120` is suitable for development; use a higher value for production.
- `PRODUCK_MAX_TICKETS_PER_POLL=1` keeps polling responsive by processing one full ticket per poll.
- `PRODUCK_SEARCH_DOMAIN` optionally filters Produck polling to one website domain.
- `PRODUCK_FEEDBACK_IDS` is only a dev fallback if Produck's open-ticket search tool is unavailable or returns no IDs.
- Relative `PRODUCK_OUTPUT_DIR` values are stored under `<EMPLOYEE_PORTAL_PATH>/<PARCLE_MEMORY_DIR>/` so ticket
  artifacts persist with the target repo.
- Relative `PRODUCK_STATE_PATH` values are stored under the runtime user's home directory, not the target repo. This
  dedupe file prevents repeated processing without leaving post-PR working-tree changes.
- `PRODUCK_CLOSE_ON_SUCCESS=false` by default. Leave it off if Produck status updates are slow or unsupported.
- `PARCLE_API_KEY` is used by the official `parcle` SDK.
- `PARCLE_USER_ID` defaults to `system_user`. Seed this user once with the Employee Portal documentation, then every incident search and decision sync uses the same memory user.
- `ENTERPRO_COMMAND` optionally overrides the Enter Code command. Leave it blank to use the built-in command:
  `enter -p <prompt> -permission-mode acceptEdits -output-format json`.
- `ENTERPRO_WORKSPACE_ID` is passed to the command template and exported as `ENTERPRO_WORKSPACE_ID`.
- `ENTERPRO_URL` is still supported as a fallback HTTP mode if no CLI command is configured.

If your existing Parcle or Enter Pro contract differs, only its adapter needs to change.

### Enter Pro repo access

The graph creates a local incident branch in `EMPLOYEE_PORTAL_PATH`, then calls Enter Pro with that same path. In CLI
mode, Enter gets code access in one of two ways:

- Local repo access: run this service on the same machine/container where the Employee Tracker repository is mounted.
  Set `EMPLOYEE_PORTAL_PATH` to that checkout. Docker does this by mounting `EMPLOYEE_PORTAL_PATH_HOST` to
  `/workspace/employee-portal`.
- Enter workspace/GitHub access: if Enter should operate through a workspace, connect GitHub in Enter Pro, authorize
  the Employee Tracker repository, and set `ENTERPRO_WORKSPACE_ID`. The code agent binary is `enter`; `enter-cli` is
  for platform management, and `enter` with no `-p` opens the interactive terminal UI. Numeric workspace IDs are sent
  to Enter with `-workspace-id`; workspace names are sent with `-workspace`.

Optional command override if you want to force npx:

```dotenv
ENTERPRO_COMMAND=npx --no-install enter -p "{prompt}" -permission-mode acceptEdits -output-format json -workspace-id "{workspace_id}"
```

When `ENTERPRO_API_KEY` is set, the built-in command passes it to Enter with `-api-key` and also exports
`ENTER_API_KEY`.

Verify the command from the same shell/container that will run LangGraph:

```bash
python -m scripts.check_enter
```

For automatic PR creation in Docker, set `ENABLE_GIT_PUSH=true` in `.env`. The compose file now respects that value
instead of forcing it off. The service pushes with the configured `GITHUB_TOKEN` using non-interactive HTTPS auth, then
calls the GitHub API to create or reuse an open pull request.

When running with Docker, the Enter CLI must be installed inside the image/container. A CLI installed only on the host
machine is not visible to the `incident-agent` container. While wiring up Enter for the first time, running locally with
`uvicorn app.main:app --reload --port 8001` is usually simpler than Docker because it uses your host PATH.

## Seed Parcle Memory

The target repo should keep Parcle-facing docs in `PARCLE_MEMORY_DIR`, which defaults to:

```text
docs/parcle_memory
```

Put Markdown files there, for example:

- `README.md`
- `API_DOCUMENTATION.md`
- `PARCLE_MEMORY.md`
- `incidents/*.md`

If this folder does not exist yet, the ingestion script falls back to the old root-level files:
`API_DOCUMENTATION.md`, `PARCLE_MEMORY.md`, and `README.md`.

Validate them without writing anything:

```bash
python -m scripts.ingest_parcle --dry-run
```

Then perform the one-time SDK ingestion into `PARCLE_USER_ID`:

```bash
python -m scripts.ingest_parcle
```

Use `--project-path C:/path/to/employee-portal` to override `EMPLOYEE_PORTAL_PATH`.
The script submits each Markdown file with `client.ingest_file(user_id=PARCLE_USER_ID, file=...)`.
Parcle may apply its own internal chunking/indexing. Treat this as a one-time seed step for the shared system memory;
rerun only when you intentionally want Parcle to ingest refreshed source documentation.

### Where memory is updated

The searchable memory is not stored in this agent repository. It is stored in the remote Parcle service under:

```text
PARCLE_USER_ID=system_user
```

Separately, the human-readable incident trail is stored in
`<EMPLOYEE_PORTAL_PATH>/<PARCLE_MEMORY_DIR>/agent_decisions.md`, and each run writes a separate incident file under
`<EMPLOYEE_PORTAL_PATH>/<PARCLE_MEMORY_DIR>/incidents/`. These files are committed to the target repo and can persist
through GitHub. The incident file is ingested with `client.ingest_file(...)`, and the decision is also written into
Parcle as dialog memory with `client.ingest_dialog(...)`.

## Run locally

```bash
python -m venv .venv
# Activate the virtual environment, then:
pip install -r requirements.txt
npm install
python -m scripts.check_enter
uvicorn app.main:app --reload --port 8001
```

Resolve an incident:

```bash
curl -X POST http://localhost:8001/api/v1/incidents/resolve \
  -H "Content-Type: application/json" \
  -d '{"incident":"Users cannot update their profile after the validation rollout"}'
```

Produck operations:

```bash
curl http://localhost:8001/api/v1/produck/tools

curl -X POST http://localhost:8001/api/v1/produck/tickets/<feedback-id>/trigger

curl -X POST http://localhost:8001/api/v1/produck/poll

curl http://localhost:8001/api/v1/produck/state
```

`/produck/tickets/{feedback_id}/trigger` is the direct path for a known Produck feedback ID. `/produck/poll` searches
open Produck feedback tickets, asks for `status=open` when Produck's MCP schema supports it, skips spam/non-open
summaries when status metadata exists, then processes up to `PRODUCK_MAX_TICKETS_PER_POLL` full tickets per poll.
If Produck exposes an update/status MCP tool and `PRODUCK_CLOSE_ON_SUCCESS=true`, the scheduler attempts status
updates.
`PRODUCK_FEEDBACK_IDS` is used only as a fallback when open-ticket search is unavailable.

The response contains `branch_name`, `files_modified`, `documentation_updated`, `incident_record_path`,
`commit_hash`, `pull_request_url`, validation details, and a summary. Failures from external integrations or
validation return an error before PR creation.

## Quackfix Portal

This repository also includes a full-stack incident portal around the LangGraph service. The portal does not
reimplement the graph; it calls the existing LangGraph endpoint at `POST /api/v1/incidents/resolve`.

Services:

- `incident-agent`: existing LangGraph backend on `http://localhost:8001`.
- `portal-backend`: FastAPI, SQLAlchemy, Alembic, and PostgreSQL integration on `http://localhost:8002`.
- `portal-frontend`: Next.js 15, TypeScript, Tailwind, ShadCN-style components, and React Query on
  `http://localhost:3000`.
- `postgres`: persistent Quackfix conversation/execution storage on port `5432`.

Portal features:

- Chat-style incident submission with permanent conversation history.
- Live agent thinking/status timeline over WebSockets.
- Dashboard metrics and charts for total incidents, successful/failed resolutions, open PRs, and duration.
- Incident detail pages with branch, commit, files changed, validation, docs update status, and PR links.
- Audit export as JSON.
- Global search across incident titles, user prompts, and resolution summaries.
- Diagnostics page with a Produck auto-fetch switch and manual poll trigger.
- In the full-stack Compose setup, the LangGraph service's own Produck scheduler is disabled so this switch is the
  single control point for automatic Produck polling.

Portal backend APIs:

```text
POST /api/conversations
GET  /api/conversations
GET  /api/conversations/{id}
POST /api/incidents/submit
GET  /api/executions/{id}
WS   /ws/executions/{id}
GET  /api/dashboard
GET  /api/search?q=...
GET  /api/conversations/{id}/export
GET  /api/settings/produck-fetch
PUT  /api/settings/produck-fetch
POST /api/produck/poll
```

Useful portal environment variables:

```dotenv
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/quackfix
LANGGRAPH_URL=http://localhost:8001
CORS_ORIGINS=http://localhost:3000
NEXT_PUBLIC_API_BASE_URL=http://localhost:8002
```

Run the full stack with Docker:

```bash
docker compose up --build
```

Open:

- Quackfix UI: `http://localhost:3000`
- Portal API docs: `http://localhost:8002/docs`
- LangGraph API docs: `http://localhost:8001/docs`

The repository that Enter Pro edits still comes from `EMPLOYEE_PORTAL_PATH`/`EMPLOYEE_PORTAL_PATH_HOST`. The portal
backend only stores Quackfix conversations and calls the LangGraph service, which performs Parcle search, Enter Pro
execution, validation, commits, and PR creation.

## Testing and visualization

```bash
pytest -q
python -m scripts.generate_graph
```

The visualization script writes `docs/incident_workflow.mmd`. Every successful target-repository run appends its
evidence and decisions to `<PARCLE_MEMORY_DIR>/agent_decisions.md`, writes a separate incident report under
`<PARCLE_MEMORY_DIR>/incidents/`, syncs the report to Parcle, and then commits locally.

## Docker

Set `EMPLOYEE_PORTAL_PATH_HOST` to the host Employee Portal directory, then run `docker compose up --build`.
The target repository is mounted into the container at `/workspace/employee-portal`.
