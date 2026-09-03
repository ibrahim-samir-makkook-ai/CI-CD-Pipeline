# CD Setup Steps — Staging Auto-Deploy + Production Approval + GitHub Email Notifications

This guide wires up `.github/workflows/cd.yml:1` (6 jobs) and `.github/workflows/ci.yml:1` (4 jobs) so that **every push to `main` auto-builds & deploys to staging**, **publishes production image without approval**, **waits for manual approval before production deploy**, and **sends exactly 2 GitHub Issue emails** (`staging deployment` + `production deployment` subjects, no `flowchart LR`). Same-server supported via distinct `STAGING_PORT`/`PROD_PORT` (secrets or variables) + `STAGING_PATH`/`PROD_PATH`. `concurrency: production/cancel:true` auto-cancels stale approvals.

> Current `cd.yml` implements full flow: `publish-staging` `.github/workflows/cd.yml:34` builds `ghcr.io/...:staging` + `sha-*` and smoke-tests `.github/workflows/cd.yml:99`, `deploy-staging` `.github/workflows/cd.yml:120` deploys to staging via SSH (`STAGING_HOST` **required** — fails if empty `cd.yml:133`, port from `STAGING_PORT` `cd.yml:176`), `publish-production` `.github/workflows/cd.yml:207` **no `production` env** — promotes same digest to `:latest`/`:stable` via `imagetools` `cd.yml:303` after `needs: [publish-staging, deploy-staging]` `cd.yml:219`, `deploy-production` `.github/workflows/cd.yml:321` waits on `environment: production` `cd.yml:331` before SSH deploy to prod (`PROD_HOST` required `cd.yml:337`, port from `PROD_PORT` `cd.yml:383`), `notify-preproduction` `.github/workflows/cd.yml:409` **Email 1 — `staging deployment`** `cd.yml:519` (CI `lint/test/docker` via API + staging + prod publish + `waiting for approval`), `notify-production` `.github/workflows/cd.yml:555` **Email 2 — `production deployment`** `cd.yml:614` (after approval, success/failure). `ci.yml` has `lint` `.github/workflows/ci.yml:11` → `test` `.github/workflows/ci.yml:37` → `docker` `.github/workflows/ci.yml:58` → `notify` `.github/workflows/ci.yml:89` **PR-only** (push to `main` covered by CD preproduction to avoid duplicate). Subjects fixed: `staging deployment` / `production deployment`, no `flowchart LR`.

---

## 0. Prerequisites

- Repo: `ibrahim-samir-makkook-ai/CI-CD-Pipeline` on branch `main`
- 1 or 2 Linux hosts (Ubuntu 22.04+): **staging + production** — can be **same server** (`46.62.229.172`) with different `PORT`/`PATH`, or 2 separate VPS — reachable via SSH (port 22 or custom)
- Each host/path: `docker` + `docker compose` installed, SSH access
- GitHub repo **admin** to create `Environments` + `Secrets`/`Variables` + `Variables`
- GitHub account for each production reviewer (email enabled: `Settings → Notifications → Email` + repo `Watch → Custom → Issues`)
- `gh` CLI optional

---

## 1. Prepare Staging & Production Hosts

Run on **each** host/path (for same-server, run twice with different `PATH`/`PORT`):

```bash
# 1.1 Install Docker (Ubuntu)
sudo apt-get update && sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER  # re-login after

# 1.2 Verify
docker --version && docker compose version

# 1.3 Prepare app directories — SAME-SERVER needs distinct paths/ports
# Staging:
sudo mkdir -p /opt/ci-cd-pipeline && sudo chown $USER:$USER /opt/ci-cd-pipeline
# Production (same host): separate dir to avoid collision
sudo mkdir -p /opt/ci-cd-pipeline-prod && sudo chown $USER:$USER /opt/ci-cd-pipeline-prod

# 1.4 Compose file — templated via TAG + PORT (cd.yml:187,394)
# Staging compose: ports ["5000:5000"] (STAGING_PORT default 5000)
# Production compose: ports ["5001:5000"] (PROD_PORT default 5001)
# Example staging:
cat > /opt/ci-cd-pipeline/docker-compose.yml <<'YAML'
services:
  app:
    image: ghcr.io/isamir0/ci-cd-pipeline-test:${TAG:-staging}
    ports: ["5000:5000"]
    container_name: ci-cd-pipeline-test
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 5s
YAML
# Production (same host, different dir/port):
cat > /opt/ci-cd-pipeline-prod/docker-compose.yml <<'YAML'
services:
  app:
    image: ghcr.io/isamir0/ci-cd-pipeline-test:${TAG:-stable}
    ports: ["5001:5000"]
    container_name: ci-cd-pipeline-prod
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 5s
YAML
# Staging: TAG=staging docker compose -f /opt/ci-cd-pipeline/docker-compose.yml up -d
# Prod:    TAG=stable  docker compose -f /opt/ci-cd-pipeline-prod/docker-compose.yml up -d

# 1.5 Firewall — open both ports when same-server
sudo ufw allow 22/tcp
sudo ufw allow 5000/tcp
sudo ufw allow 5001/tcp

# 1.6 Test manual pull (needs GHCR_PAT from Step 2)
echo "$GHCR_PAT" | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
TAG=staging docker compose -f /opt/ci-cd-pipeline/docker-compose.yml pull && TAG=staging docker compose -f /opt/ci-cd-pipeline/docker-compose.yml up -d
curl --fail http://localhost:5000/health && curl --fail http://localhost:5000/
TAG=stable docker compose -f /opt/ci-cd-pipeline-prod/docker-compose.yml pull && TAG=stable docker compose -f /opt/ci-cd-pipeline-prod/docker-compose.yml up -d
curl --fail http://localhost:5001/health && curl --fail http://localhost:5001/
```

> `Dockerfile:1` uses `gunicorn --bind 0.0.0.0:5000 app:app` and `HEALTHCHECK` — no extra config needed. `cd.yml:176,383` now reads `STAGING_PORT`/`PROD_PORT` from `secrets` or `vars` (`${{ secrets.STAGING_PORT || vars.STAGING_PORT || 5000 }}`).

---

## 2. Create GHCR PAT (for hosts to pull private images)

`GITHUB_TOKEN` `.github/workflows/cd.yml:58` is short-lived and **not reusable** from remote hosts. Create persistent PAT:

1. GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Generate new token → Scopes: `read:packages`, `repo` (if private)
3. Expiry: 90d → Copy as `GHCR_PAT`
4. Fine-grained alternative: Resource owner = org, Repository access = this repo, Permissions → Packages: Read

Test:
```bash
echo "$GHCR_PAT" | docker login ghcr.io -u ibrahim-samir-makkook-ai --password-stdin
docker pull ghcr.io/isamir0/ci-cd-pipeline-test:staging
```

---

## 3. SSH Key Setup

Use **dedicated deploy key** (don't reuse personal).

```bash
# On laptop (not server)
ssh-keygen -t ed25519 -C "ci-cd-staging-deploy" -f ~/.ssh/ci_cd_staging -N ""
ssh-keygen -t ed25519 -C "ci-cd-prod-deploy" -f ~/.ssh/ci_cd_prod -N ""
ssh-copy-id -i ~/.ssh/ci_cd_staging.pub USER@STAGING_HOST
ssh-copy-id -i ~/.ssh/ci_cd_prod.pub USER@PROD_HOST
ssh -i ~/.ssh/ci_cd_staging USER@STAGING_HOST "docker ps"
```

Private keys → `STAGING_SSH_KEY`/`PROD_SSH_KEY` in Step 4. **Never commit keys.**

> **Password auth (`ibrahem@46.62.229.172`):** If server uses password, add secret **`STAGING_PASSWORD`** / **`PROD_PASSWORD`** (`cd.yml:150,354` supports `password: ${{ secrets.STAGING_PASSWORD || secrets.STAGING_SSH_PASSWORD }}`) — leave `*_SSH_KEY` empty. Key is more secure long-term.

---

## 4. Configure GitHub Environments & Secrets/Variables

### 4.1 Create Environments

GitHub repo → **Settings → Environments → New environment**:

- **staging**:
  - No protection (auto-deploy)
  - URL: `http://STAGING_HOST:5000` (or `http://46.62.229.172:5000`)
  - Deployment branches → `Selected branches: main`
- **production**:
  - Check **Required reviewers** → add 1+ user/team (approval gate `.github/workflows/cd.yml:331`)
  - URL: `http://PROD_HOST:5001` (same-server prod) or `http://46.62.229.172:5001`
  - Deployment branches → `main`

### 4.2 Add Repository Secrets / Variables

Settings → Secrets and variables → Actions → **New repository secret** **or** **New repository variable** (ports/paths are not sensitive → `Variables` recommended):

| Name | Type | Value | Used by |
|---|---|---|---|
| `GHCR_PAT` | Secret | PAT from Step 2 | SSH `docker login` `cd.yml:170` |
| `STAGING_HOST` | Secret | `46.62.229.172` | `deploy-staging` `cd.yml:133` **fails if empty** `cd.yml:134` |
| `STAGING_USER` | Secret | `ibrahem` | `cd.yml:142` |
| `STAGING_SSH_KEY` | Secret | `~/.ssh/ci_cd_staging` private | `cd.yml:143` — empty if using password |
| `STAGING_PASSWORD` | Secret | `Makkook@123` | `cd.yml:150` fallback `STAGING_SSH_PASSWORD` |
| `STAGING_SSH_PORT` | Secret/Var | `22` | `cd.yml:145` |
| `STAGING_PORT` | **Secret or Variable** | `5000` | `cd.yml:176` `${{ secrets.STAGING_PORT \|\| vars.STAGING_PORT \|\| 5000 }}` — host port for staging |
| `STAGING_PATH` | Secret/Var | `/opt/ci-cd-pipeline` | `cd.yml:177` remote `cd` |
| `PROD_HOST` | Secret | `46.62.229.172` | `deploy-production` `cd.yml:337` **fails if empty** `cd.yml:338` |
| `PROD_USER` | Secret | `ibrahem` | `cd.yml:345` |
| `PROD_SSH_KEY` | Secret | `~/.ssh/ci_cd_prod` | `cd.yml:347` |
| `PROD_PASSWORD` | Secret | `Makkook@123` | `cd.yml:354` |
| `PROD_SSH_PORT` | Secret/Var | `22` | `cd.yml:349` |
| `PROD_PORT` | **Secret or Variable** | `5001` | `cd.yml:383` `${{ secrets.PROD_PORT \|\| vars.PROD_PORT \|\| 5001 }}` — host port for prod (different from staging for same-server) |
| `PROD_PATH` | Secret/Var | `/opt/ci-cd-pipeline-prod` | `cd.yml:383` separate dir for same-server |

> Same-server: keep `STAGING_PORT=5000` / `PROD_PORT=5001` and `STAGING_PATH=/opt/ci-cd-pipeline` vs `PROD_PATH=/opt/ci-cd-pipeline-prod` to avoid `Bind 0.0.0.0:5000 failed`. Two-host: can keep both `5000` but distinct `HOST`s.

Example `gh` CLI:
```bash
gh secret set STAGING_HOST --body "46.62.229.172"
gh secret set STAGING_USER --body "ibrahem"
gh secret set STAGING_PASSWORD --body "Makkook@123"
gh variable set STAGING_PORT --body "5000"
gh variable set STAGING_PATH --body "/opt/ci-cd-pipeline"

gh secret set PROD_HOST --body "46.62.229.172"
gh secret set PROD_USER --body "ibrahem"
gh secret set PROD_PASSWORD --body "Makkook@123"
gh variable set PROD_PORT --body "5001"
gh variable set PROD_PATH --body "/opt/ci-cd-pipeline-prod"

gh secret set GHCR_PAT --body "<PAT>"
```

### 4.3 GitHub Email Notifications — No Extra Secrets

**GitHub Email needs no SMTP.** `notify` jobs use `GITHUB_TOKEN` (auto) + `permissions: issues: write` to create Issues; GitHub emails reviewers.

<details><summary>Previously Gmail SMTP (now removed)</summary>

| Old Secret | Now |
|---|---|
| `GMAIL_USER` / `SMTP_*` | Not needed — GitHub login used |
| `MAIL_TO_FALLBACK` | Not needed — reviewers from `environment: production` |

</details>

### 4.4 Verify secrets not logged

Jobs mask secrets. Never `echo ${{ secrets.* }}`. Deploy pipes `GHCR_PAT` via stdin; Email uses `GITHUB_TOKEN` (masked).

---

## 5. How Workflows Work Today

### 5.1 `cd.yml` (6 jobs — 2 emails)

| Job | File | Trigger | What it does |
|---|---|---|---|
| `publish-staging` | `.github/workflows/cd.yml:34` | `push: main` `cd.yml:26` | `docker/build-push-action@v5` pushes `:staging`+`sha-short`, caches `type=gha`, smoke-tests locally `cd.yml:99` |
| `deploy-staging` | `.github/workflows/cd.yml:120` | `needs: publish-staging` + `environment: staging` | SSH to `STAGING_HOST` → `docker login` + `STAGING_PORT` `cd.yml:176` + `STAGING_PATH` `cd.yml:177` + `TAG=staging docker compose pull/up` + `curl :$STAGING_PORT/health` — **fails if `STAGING_HOST` empty** `cd.yml:134` |
| `publish-production` | `.github/workflows/cd.yml:207` | `needs: [publish-staging, deploy-staging]` `cd.yml:219` + `concurrency: production/cancel:true` `cd.yml:224` **NO `production` env** | Promotes same digest to `:latest`/`:stable` via `imagetools create --tag` `cd.yml:303` (no rebuild) after stale guard `cd.yml:256` |
| `deploy-production` | `.github/workflows/cd.yml:321` | `needs: publish-production` + `environment: production` `cd.yml:331` + `concurrency: production/cancel:true` | **Approval gate** — `Waiting for approval` → SSH to `PROD_HOST` → `PROD_PORT` `cd.yml:383` + `PROD_PATH` `cd.yml:383` + `TAG=stable docker compose pull/up` + `curl :$PROD_PORT/health` — fails if `PROD_HOST` empty `cd.yml:338` |
| `notify-preproduction` | `.github/workflows/cd.yml:409` | `needs: [publish-staging, deploy-staging, publish-production]` `cd.yml:419` `if: always()` `permissions: issues: write, actions: read` | **Email 1 — subject `staging deployment` `cd.yml:519`** — fetches CI `lint/test/docker` via API, table `CI lint/test/docker | Staging build/deploy | Production image (publish)` + `digest` + `waiting for approval` — no `flowchart LR` |
| `notify-production` | `.github/workflows/cd.yml:555` | `needs: [deploy-production]` `cd.yml:573` `if: always()` | **Email 2 — subject `production deployment` `cd.yml:614`** — after approval, table `Production deploy` — success/failure, no `flowchart LR` |

### 5.2 `ci.yml` (4 jobs — PR-only notify)

| Job | File | Trigger | What it does |
|---|---|---|---|
| `lint` | `.github/workflows/ci.yml:11` | `push/PR to main` `ci.yml:3` | `ruff check .` + `ruff check --select ANN` + `ruff format --check` |
| `test` | `.github/workflows/ci.yml:37` | same | `pytest -v` 5 tests |
| `docker` | `.github/workflows/ci.yml:58` | `needs: [lint, test]` | `docker build` + `curl /health` smoke |
| `notify` | `.github/workflows/ci.yml:89` | `needs: [lint, test, docker]` `if: always() && github.event_name == 'pull_request'` | **PR-only** minimal table (no `flowchart LR`) — push to `main` covered by `notify-preproduction` |

Key guarantees:
- **Build once**: `latest`/`stable` same digest as `staging` (`digest` `cd.yml:230`)
- **No stale prod**: `concurrency:production/cancel:true` `cd.yml:224,329` + stale guard
- **Same-server safe**: `STAGING_PORT` vs `PROD_PORT` (`5000` vs `5001` defaults) + `STAGING_PATH` vs `PROD_PATH` (`/opt/ci-cd-pipeline` vs `/opt/ci-cd-pipeline-prod`) — ports from `secrets` or `vars`, no hard-code
- **Fail-fast**: `STAGING_HOST`/`PROD_HOST` empty → `::error` + `exit 1` `cd.yml:134,338` (no GHCR-only silent skip)
- **Rollback**: `docker buildx imagetools create --tag ghcr.io/...:latest ghcr.io/...@sha256:<digest>` (summary `cd.yml:311`)
- **Email subjects**: fixed `staging deployment` / `production deployment` (`cd.yml:519,614`) — no `flowchart LR`, no status in subject (labels `preprod-failure`/`prod-success` via `IS_FAILURE` `cd.yml:544,632`)

---

## 6. `cd.yml` Deploy & Notify Jobs — Already Implemented (reference)

> **Status: Done** — `cd.yml` has `deploy-staging` `cd.yml:120`, `deploy-production` `cd.yml:321` (`appleboy/ssh-action@v1`, `concurrency: cancel stale`, **fails if `*_HOST` empty**), plus **2 emails**: `notify-preproduction` `cd.yml:409` (CI+CD staging + prod publish, `staging deployment`) and `notify-production` `cd.yml:555` (after approval, `production deployment`), both `issues: write` (+ `actions: read` for preproduction). `ci.yml:89` is **PR-only**.

Reference `notify-preproduction` (Email 1):
```yaml
  notify-preproduction:
    runs-on: ubuntu-latest
    needs: [publish-staging, deploy-staging, publish-production]  # Email 1
    if: always()
    permissions: { contents: read, issues: write, actions: read }
    steps:
      - id: reviewers  # GET /environments/production → logins
      - id: ci         # listWorkflowRuns(ci.yml, head_sha) → lint/test/docker
      - id: msg        # Python table: CI lint/test/docker + Staging build/deploy + Production image (publish) + digest + "waiting for approval"
      - subject: "staging deployment"
      - labels: ['preprod-failure','notify'] via IS_FAILURE
```

Reference `notify-production` (Email 2):
```yaml
  notify-production:
    runs-on: ubuntu-latest
    needs: [deploy-production]  # only after approval
    if: always()
    permissions: { contents: read, issues: write }
    steps:
      - id: reviewers
      - id: msg  # table: Production deploy + waiting/failed/success
      - subject: "production deployment"
      - labels: ['prod-failure','notify'] via IS_FAILURE
```

**Approval gate:** `publish-production` **no** `environment: production`; `deploy-production` **has** `environment: production` `cd.yml:331` with `Required reviewers`. No double approval.

---

## 7. Verify End-to-End (2 emails, no `flowchart LR`)

```bash
# 7.1 Push to main (triggers CI + CD)
git checkout main && git pull
echo "# test $(date)" >> README.md
git commit -am "chore: trigger staging" && git push origin main

# 7.2 Watch in GitHub
# Actions → CD Pipeline → run →
#   publish-staging ✅ (Staging pushed: ... + digest)
#   deploy-staging ✅ (port $STAGING_PORT, e.g., 5000)
#   publish-production ✅ (promote @digest → :latest/:stable, no approval)
#   notify-preproduction → Issue title "staging deployment" with table + "waiting for approval"
#   deploy-production ⏸  "Waiting for approval" (yellow, production env)
# 7.3 Approve
# Actions → latest run → Review deployments → production → Approve
#   deploy-production ✅ (pull :stable to $PROD_PORT, e.g., 5001, curl /health)
#   notify-production → Issue title "production deployment" with Production deploy table

# 7.4 Same-server check
ssh ibrahem@46.62.229.172 "docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'; echo staging; curl -s http://localhost:5000/health; echo prod; curl -s http://localhost:5001/health"
docker buildx imagetools inspect ghcr.io/ibrahim-samir-makkook-ai/ci-cd-pipeline:staging | grep digest

# 7.5 Cancel-stale: push again while prod waiting → previous waiting "Canceled" due to concurrency:production/cancel:true → no email for cancelled
```

Endpoints (same-server):
```bash
curl http://46.62.229.172:5000/health  # staging
curl http://46.62.229.172:5001/health  # production
```

---

## 8. Rollback

All images immutable via digest:

```bash
IMAGE=$(echo "ghcr.io/ibrahim-samir-makkook-ai/ci-cd-pipeline" | tr '[:upper:]' '[:lower:]')
OLD=sha256:<previous-digest-from-summary>

# GHCR-only rollback (no SSH):
docker buildx imagetools create --tag $IMAGE:latest $IMAGE@$OLD
docker buildx imagetools create --tag $IMAGE:stable $IMAGE@$OLD

# VPS rollback — staging
ssh ibrahem@46.62.229.172 <<EOS
  echo "\$GHCR_PAT" | docker login ghcr.io -u ibrahim-samir-makkook-ai --password-stdin
  docker pull $IMAGE@$OLD
  docker tag $IMAGE@$OLD $IMAGE:staging
  cd /opt/ci-cd-pipeline && TAG=staging docker compose up -d
  curl --fail http://localhost:5000/health
EOS
# VPS rollback — production (5001)
ssh ibrahem@46.62.229.172 <<EOS
  echo "\$GHCR_PAT" | docker login ghcr.io -u ibrahim-samir-makkook-ai --password-stdin
  docker pull $IMAGE@$OLD
  docker tag $IMAGE@$OLD $IMAGE:stable
  cd /opt/ci-cd-pipeline-prod && TAG=stable docker compose up -d
  curl --fail http://localhost:5001/health
EOS
```

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `publish-production` stuck yellow forever | No reviewer added | Settings → Environments → production → Required reviewers → add user |
| `deploy-staging` fails `STAGING_HOST not set` | Secret/variable missing | `gh secret set STAGING_HOST` or `gh variable set STAGING_HOST`; now fails fast `cd.yml:134` (not skipped) |
| `deploy-production` fails `PROD_HOST not set` | Same | `gh secret set PROD_HOST` `cd.yml:338` |
| `Bind 0.0.0.0:5000 failed: port already allocated` | Same-server collision | Set `STAGING_PORT=5000` `PROD_PORT=5001` via `secrets` or `vars` `cd.yml:176,383` + distinct `STAGING_PATH`/`PROD_PATH` |
| `docker pull ...:staging: not found` | Repo lowercasing missing | Ensure `tr '[:upper:]' '[:lower:]'` in scripts `cd.yml:148` |
| `docker login failed` on host | `GHCR_PAT` expired | Regenerate PAT `read:packages` |
| `curl /health` fails after deploy | Port/firewall | `ssh HOST "docker compose logs --tail 100; docker ps -a; curl -v http://localhost:5000/health"` / `5001` for prod; `sudo ufw allow 5000,5001` |
| Stale promotion blocked | Approved old run | Approve **latest** run (stale guard `cd.yml:256`) |
| `concurrency` cancels prod instantly | New push while waiting | Intentional; re-approve latest |
| `appleboy/ssh-action` hangs | Firewall blocks GH Actions IPs | Allow 22, add `timeout: 60s` |
| `No reviewers resolved` → fallback to owner | `production` has no Required reviewers | Add reviewers: Settings → Environments → production → Required reviewers |
| `Resource not accessible by integration` | `notify` missing `issues: write` | Ensure `permissions: issues: write` `cd.yml:422,576` |
| No email but Issue created | Reviewer has Email notifications OFF or not Watching | Reviewer: `Settings → Notifications → Email` ON, repo `Watch → Custom → Issues` ON, check Spam |
| Old `flowchart LR` still in docs | Cached view | This guide removed `flowchart LR` from workflows `cd.yml:519`/`ci.yml:89`; docs no longer show mermaid flowchart |

---

## 10. GitHub Email Notifications — 2 Emails (subjects fixed)

Policy: **2 emails** — `staging deployment` (after CI+staging+prod publish, indicates `waiting for approval`) + `production deployment` (after approval, success/failure). No `flowchart LR`.

### 10.1 How GitHub Email Works (no SMTP)

* GitHub emails when user is **assigned** or **@mentioned** in Issue, if `Settings → Notifications → Email` ON + repo `Watch → Custom → Issues`.
* Jobs resolve reviewers via `GET /repos/{owner}/{repo}/environments/production` → `protection_rules[].reviewers` (same as `environment: production` gate `cd.yml:331`), fallback to repo owner.
* Creates Issue with `title: "staging deployment"` `cd.yml:519` / `"production deployment"` `cd.yml:614` + `labels: preprod-failure`/`prod-success` via `IS_FAILURE` `cd.yml:544,632`. Success issues auto-closed after creation (email already sent).
* Email header becomes `Re: [repo] staging deployment (Issue #N)` — GitHub prefixes `Re: [repo]` (cannot be removed via Issue; for exact `Subject: staging deployment` use SMTP `dawidd6/action-send-mail`).

### 10.2 No Secrets Needed

| Secret | Before (Gmail SMTP) | Now (GitHub Email) |
|---|---|---|
| `GMAIL_USER`/`SMTP_*` | Required | **Not needed — delete** |
| `GITHUB_TOKEN` | Already present | Requires `permissions: issues: write` (+ `actions: read` for preproduction) — present `cd.yml:422,576` |

### 10.3 How Notify Jobs Work Now

* **`ci.yml:89` PR-only** `needs: [lint, test, docker]` `if: always() && github.event_name == 'pull_request'`:
  * Table `| lint | | test | | docker |` (no mermaid) → `labels: ['ci-failure','notify']` (PR failure only).

* **`cd.yml:409` `notify-preproduction`** `needs: [publish-staging, deploy-staging, publish-production]` `if: always()`:
  * Table: `CI lint/test/docker | Staging build/deploy | Production image (publish)` + `digest` + `🚦 Production deployment is waiting for approval`
  * `subject: "staging deployment"` `cd.yml:519`

* **`cd.yml:555` `notify-production`** `needs: [deploy-production]` `if: always()`:
  * Table: `Production deploy` + `is_skipped/is_cancelled/is_failure` handling
  * `subject: "production deployment"` `cd.yml:614`

### 10.4 Verify GitHub Email

```bash
gh api repos/OWNER/REPO/environments/production --jq '.protection_rules[].reviewers'
# push to main → notify-preproduction → Issue "staging deployment" → email
# approve prod → notify-production → Issue "production deployment" → email
# push twice fast → ⚠️ Cancelled — no email
```

## 11. Quick Checklist (2 emails, same-server ports via secrets/vars)

- [ ] Hosts: `docker` + `docker compose` installed, `/opt/ci-cd-pipeline` (`STAGING_PORT=5000`) and `/opt/ci-cd-pipeline-prod` (`PROD_PORT=5001`) present
- [ ] GHCR PAT `read:packages`, secret `GHCR_PAT` set
- [ ] SSH `authorized_keys`, secrets `*_HOST`/`*_USER`/`*_PASSWORD` set — now **fails if `*_HOST` empty** `cd.yml:134,338`
- [ ] Ports/Paths via **secrets or variables**: `STAGING_PORT`/`PROD_PORT` `cd.yml:176,383` (`5000`/`5001` defaults) + `STAGING_PATH`/`PROD_PATH`; `STAGING_PORT` from `secrets` `vars` fallback `cd.yml:176`
- [ ] Environments `staging` (auto) + `production` (Required reviewers = 1) created
- [ ] Secrets `*_HOST`, `*_USER`, `*_PATH`, `GHCR_PAT` set; `STAGING_PORT`/`PROD_PORT` via `vars` or `secrets`
- [ ] **Email:** `permissions: issues: write` `cd.yml:422,576`; reviewers `Watch → Issues` + `Email` ON; subjects `staging deployment`/`production deployment`
- [ ] Push to `main` → `notify-preproduction` → `staging deployment` (waiting) → Approve → `notify-production` → `production deployment`
- [ ] `docker compose config` with `TAG=staging` → `:staging` on `5000`, `TAG=stable` → `:stable` on `5001`

---

## References

- CD workflow: `.github/workflows/cd.yml:1`, `publish-staging` `cd.yml:34`, `deploy-staging` `cd.yml:120`, `publish-production` `cd.yml:207`, `deploy-production` `cd.yml:321`, `notify-preproduction` `cd.yml:409` (`staging deployment`), `notify-production` `cd.yml:555` (`production deployment`)
- CI workflow: `.github/workflows/ci.yml:1`, `lint` `ci.yml:11`, `test` `ci.yml:37`, `docker` `ci.yml:58`, `notify` `ci.yml:89` (PR-only)
- App: `app.py:16` (`/health`), `Dockerfile:20`, `docker-compose.yml:6` (`${TAG:-staging}`)
