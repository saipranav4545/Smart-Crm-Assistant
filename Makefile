.PHONY: install playground run test lint

install:
	uv sync

playground:
	uv run adk web --host 127.0.0.1 --port 18081 --reload_agents

run:
	uv run uvicorn app.agent_runtime_app:app --host 127.0.0.1 --port 8080

test:
	uv run pytest tests/unit

lint:
	uv run ruff check app
