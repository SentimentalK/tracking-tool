# Tracking

Internal repository for syncing Notion databases and Slack reminders.

## Run with Infisical

All secrets are managed via Infisical. Do not write credentials into code or `.env`.

```bash
# Run daily sync with prod secrets (CronJob)
infisical run --env=prod -- .venv/bin/python main.py

# Run FastAPI webhook server (24x7 Deployment)
infisical run --env=prod -- .venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000

# Run unit tests (offline, fully mocked)
.venv/bin/pytest -v tests/
```

### Injected Secrets (Infisical)
* `NOTION_TOKEN`: Notion API integration token
* `SLACK_TOKEN`: Slack Bot OAuth token
* `SLACK_SIGNING_SECRET`: Slack signing secret (for validating incoming webhooks)
* `SLACK_ADMIN`: Slack Admin User ID (`U034H72T319`)
* `SLACK_USER`: Target user ID for reminder mentions (`U034EB7UKEZ`)

---

## Architecture & Entrypoints (Quick Reference)

```text
main.py                  # CLI entrypoint for daily sync routine (CronJob)
server.py                # FastAPI webhook server (Deployment): /slack/interactions, /healthz
tracker/
  notion.py              # Table ↔ pandas DataFrame diff sync (lazy-load, writes())
  slack.py               # SlackClient (chat_postMessage, delete, parse_interactive_payload)
  config.py              # Validates NOTION_TOKEN and SLACK_TOKEN in os.environ
apps/insurance/
  workflow.py            # run_daily(), handle_action(payload)
  renderer.py            # Block Kit card builder ('paid', 'destory' actions)
  config.py              # Insurance DB IDs (Company, Product, People, Order)
tests/
  test_insurance.py      # Unit tests (reminders, monday overdue, paid, destory, expiration)
  test_server.py         # Unit tests for FastAPI server (healthz, signing verifier, 200 ACK)
```

### Core Business Rules
1. **Sync Scope**: `状态 == 有效保单`
2. **Standard Reminders**: `缴费倒计时 in [0, 1, 8, 15]`
3. **Overdue Reminders**: `-90 <= 缴费倒计时 < 0` (Sent only on Monday in `Asia/Shanghai`)
4. **Auto-Expire**: `缴费倒计时 < -90` -> `状态 = 失效`
5. **Interactive Action `paid`**:
   * `下次续费时间` += 1 year
   * `已缴次数` += 1
   * If `缴费期间` is integer and `已缴次数 >= 缴费期间` -> `状态 = 已缴满`
   * `slack时间戳` = None
6. **Interactive Action `destory`**:
   * `状态 = 失效`
   * `slack时间戳` = None

### Python APIs
```python
# 1. Daily Sync
from apps.insurance.workflow import run_daily
run_daily()

# 2. Interactive Webhook Callback (when server is ready)
from apps.insurance.workflow import handle_action
handle_action(raw_payload)  # supports dict, json string, form data 'payload=...', or base64
```
