IMAGE=ci-cd-pipeline-test:latest
CONTAINER=ci-test
PORT=5000

# Auto-detect if sudo needed for docker
DOCKER:=$(shell docker ps >/dev/null 2>&1 && echo docker || echo sudo docker)

.PHONY: build run up logs down restart compose test clean lint format lint-fix

build:
	$(DOCKER) build -t $(IMAGE) .

# up = just run (no build) - fast, uses existing image
up:
	-$(DOCKER) rm -f $(CONTAINER) 2>/dev/null || true
	$(DOCKER) run -d -p $(PORT):5000 --name $(CONTAINER) $(IMAGE)
	@sleep 2
	@$(DOCKER) logs $(CONTAINER)
	@echo "=> http://localhost:$(PORT)/health"

# up-build = build + run (use when code changed)
up-build: build up

run: up
rebuild: down build up

logs:
	$(DOCKER) logs -f $(CONTAINER)

down:
	-$(DOCKER) stop $(CONTAINER) 2>/dev/null || true
	-$(DOCKER) rm $(CONTAINER) 2>/dev/null || true

restart: down up

compose:
	docker compose up --build -d || sudo docker compose up --build -d || docker-compose up --build -d

test:
	pytest -v

lint:
	ruff check .

format:
	ruff format --check .

lint-fix:
	ruff check --fix .
	ruff format .

clean: down
	-$(DOCKER) rmi $(IMAGE) 2>/dev/null || true
