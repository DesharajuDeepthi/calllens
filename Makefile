.PHONY: build up down db-wait ingest smoke test test-unit lint psql \
        mcp-up mcp-down mcp-logs mcp-token mcp-smoke \
        eval eval-judge eval-reset \
        graph-up graph-build graph-browser

# ── Docker lifecycle ───────────────────────────────────────────────────────
build:
	docker compose build

up:
	docker compose up -d postgres redis

down:
	docker compose down

db-wait:
	@echo "Waiting for Postgres..."
	@until docker compose exec postgres pg_isready -U calllens -d calllens > /dev/null 2>&1; do sleep 1; done
	@echo "Postgres ready."

# ── Ingestion ──────────────────────────────────────────────────────────────
# Runs the ingestion CLI inside the app container against /data/raaw
ingest: db-wait
	docker compose run --rm app

# ── Smoke check ────────────────────────────────────────────────────────────
smoke:
	@echo "\n=== Call count ==="
	@docker compose exec postgres psql -U calllens -d calllens -c \
		"SELECT COUNT(*) AS total_calls FROM calls;"
	@echo "\n=== Sentiment breakdown ==="
	@docker compose exec postgres psql -U calllens -d calllens -c \
		"SELECT overall_sentiment, COUNT(*) FROM call_summaries GROUP BY 1 ORDER BY 2 DESC;"
	@echo "\n=== Top 15 topics ==="
	@docker compose exec postgres psql -U calllens -d calllens -c \
		"SELECT unnest(topics) AS topic, COUNT(*) AS freq \
		 FROM call_summaries GROUP BY 1 ORDER BY 2 DESC LIMIT 15;"
	@echo "\n=== Unique participant emails ==="
	@docker compose exec postgres psql -U calllens -d calllens -c \
		"SELECT COUNT(DISTINCT email) AS unique_emails FROM participants;"
	@echo "\n=== Transcript turns total ==="
	@docker compose exec postgres psql -U calllens -d calllens -c \
		"SELECT COUNT(*) AS total_turns FROM transcript_turns;"

# ── Pipeline ──────────────────────────────────────────────────────────────
pipeline-run: db-wait
	docker compose run --rm --entrypoint calllens-pipeline app run

pipeline-review:
	docker compose run --rm --entrypoint calllens-pipeline app review --batch-id $(BATCH_ID)

pipeline-resume:
	docker compose run --rm --entrypoint calllens-pipeline app resume \
		--batch-id $(BATCH_ID) --corrections '$(CORRECTIONS)'

# ── Tests (run inside Docker) ─────────────────────────────────────────────
test-unit:
	docker compose run --rm --entrypoint pytest app tests/unit -v

test-integration: db-wait
	docker compose run --rm --entrypoint pytest app tests/integration -v -m integration

# ── Direct DB access ──────────────────────────────────────────────────────
psql:
	docker compose exec postgres psql -U calllens -d calllens

# ── MCP server ────────────────────────────────────────────────────────────
# Start the MCP server (also starts Postgres + Redis)
mcp-up: db-wait
	docker compose up -d mcp
	@echo "MCP server running at http://localhost:8001"
	@echo "  SSE endpoint : http://localhost:8001/mcp/sse"
	@echo "  Health check : http://localhost:8001/health"

mcp-down:
	docker compose stop mcp

mcp-logs:
	docker compose logs -f mcp

# Generate test JWT tokens for all personas
mcp-token:
	docker compose run --rm --entrypoint python app scripts/generate_token.py

# Smoke test: list tools via SSE (requires curl + jq)
# Usage: make mcp-smoke TOKEN=<paste token here>
mcp-smoke:
	@if [ -z "$(TOKEN)" ]; then \
		echo "Usage: make mcp-smoke TOKEN=<your_jwt_token>"; \
		exit 1; \
	fi
	@echo "\n--- Health check ---"
	curl -sf http://localhost:8001/health | python3 -m json.tool
	@echo "\n--- get_my_insights (first 1000 chars) ---"
	curl -sf \
		-H "Authorization: Bearer $(TOKEN)" \
		-H "Accept: text/event-stream" \
		"http://localhost:8001/mcp/sse" | head -c 1000

# ── Eval harness ─────────────────────────────────────────────────────────
# Run the accuracy + coverage gate (no LLM cost — DB queries only)
eval: db-wait
	docker compose run --rm --entrypoint pytest app \
		tests/evals/test_pipeline_accuracy.py \
		-m eval -v --tb=short

# Run the LLM-as-judge quality gate (costs API credits)
eval-judge: db-wait
	docker compose run --rm --entrypoint pytest app \
		tests/evals/test_insight_quality.py \
		-m "eval and llm_judge" -v --tb=short

# Reset the baseline so next eval saves a fresh snapshot
eval-reset:
	rm -f tests/evals/baseline_metrics.json
	@echo "Baseline cleared — next 'make eval' will save a new baseline."

# ── Neo4j knowledge graph ─────────────────────────────────────────────────
# Start Neo4j alongside Postgres + Redis
graph-up:
	docker compose up -d postgres redis neo4j
	@echo "Neo4j starting at http://localhost:7474 (user: neo4j / calllens_dev)"

# Build the knowledge graph from Postgres call data
graph-build: graph-up
	@echo "Waiting for Neo4j..."
	@until docker compose exec neo4j neo4j status > /dev/null 2>&1; do sleep 2; done
	docker compose run --rm --entrypoint python app scripts/build_graph.py
	@echo "Graph ready — open http://localhost:7474 to explore"

# Open Neo4j Browser directly
graph-browser:
	open http://localhost:7474

# ── Lint (local if python available, otherwise skip) ──────────────────────
lint:
	docker compose run --rm --entrypoint ruff app check src tests
