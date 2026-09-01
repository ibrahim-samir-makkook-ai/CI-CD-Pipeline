# CI-CD-Pipeline-Test

![CI](https://github.com/isamir0/CI-CD-Pipeline-Test/actions/workflows/ci.yml/badge.svg)

Simple Python + Docker + GitHub Actions pipeline for learning CI/CD.

## Quick Start

**Local (no Docker):**
```bash
pip install -r requirements.txt
python app.py          # http://localhost:5000
pytest -v              # run tests
```

**Docker (via Make):**

```bash
make build             # build image (only when code/requirements changed)
make up                # run container (no build, fast)
make up-build          # build + run
make rebuild           # down + build + up
make logs              # follow logs
make down              # stop & remove
make compose           # docker compose up --build -d
```

**Docker (raw):**
```bash
docker build -t ci-cd-pipeline-test:latest .
docker run -d -p 5000:5000 --name ci-test ci-cd-pipeline-test:latest
docker compose up --build -d
```

Endpoints: `GET /`, `GET /health`, `GET /add/<a>/<b>`

## Pipeline

- **CI:** `test` job — setup Python 3.11, `pip install`, `pytest`
- **CD (build):** `docker` job (needs test) — `docker build` + smoke test with `curl /health`

See [PIPELINE.md](./PIPELINE.md) for full cycle documentation (diagram, Dockerfile breakdown, local vs CI flow, troubleshooting).

## Workflow File

`.github/workflows/ci.yml` triggers on `push`/`pull_request` to `main`.

## Verify

1. `git push origin main`
2. Check `Actions` tab on GitHub — workflow should be green.
3. Try breaking a test to see CI fail and block.