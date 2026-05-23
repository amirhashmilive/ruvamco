.PHONY: help setup build test lint up down clean deploy

help:
	@echo "RUVAMCO - Self-Service Edge Proxy Platform"
	@echo ""
	@echo "Available commands:"
	@echo "  make setup    - Initialize development environment"
	@echo "  make build    - Build all Docker images"
	@echo "  make test     - Run all tests"
	@echo "  make lint     - Run linters"
	@echo "  make up       - Start local development environment"
	@echo "  make down     - Stop local development environment"
	@echo "  make clean    - Clean build artifacts"
	@echo "  make deploy   - Deploy to production"
	@echo "  make docs     - Generate documentation"

setup:
	@echo "🔧 Setting up development environment..."
	python -m venv venv
	. venv/bin/activate && pip install -r requirements-dev.txt
	pip install -e ./cli
	@echo "✅ Setup complete"

build:
	@echo "🏗️ Building Docker images..."
	docker-compose build
	@echo "✅ Build complete"

test:
	@echo "🧪 Running tests..."
	pytest tests/unit/ -v --cov=broker --cov=worker --cov=control_plane
	pytest tests/integration/ -v
	pytest tests/e2e/ -v
	@echo "✅ Tests complete"

lint:
	@echo "🔍 Running linters..."
	black broker/ worker/ control_plane/ cli/ tests/
	flake8 broker/ worker/ control_plane/ cli/ tests/
	mypy broker/ worker/ control_plane/
	@echo "✅ Linting complete"

up:
	@echo "🚀 Starting RUVAMCO platform..."
	docker-compose up -d
	@echo "✅ Services started:"
	@echo "  - Broker API: http://localhost:8080/docs"
	@echo "  - Control Plane: http://localhost:8081"
	@echo "  - Envoy Admin: http://localhost:9901"
	@echo "  - Prometheus: http://localhost:9090"
	@echo "  - Grafana: http://localhost:3000 (admin/admin)"
	@echo "  - Jaeger: http://localhost:16686"

down:
	@echo "🛑 Stopping RUVAMCO platform..."
	docker-compose down -v
	@echo "✅ Services stopped"

clean:
	@echo "🧹 Cleaning artifacts..."
	docker-compose down -v
	docker system prune -f
	rm -rf data/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	@echo "✅ Clean complete"

deploy:
	@echo "🚀 Deploying to production..."
	cd terraform && terraform init && terraform apply -auto-approve
	@echo "✅ Deployment complete"

docs:
	@echo "📚 Generating documentation..."
	pdoc --html --output-dir docs/ broker/ worker/ control_plane/ cli/
	@echo "✅ Documentation generated in docs/"

logs:
	docker-compose logs -f

shell:
	docker-compose exec broker /bin/bash

init-db:
	@echo "Initializing DynamoDB tables..."
	python scripts/init_database.py

create-buckets:
	@echo "Creating S3 buckets..."
	python scripts/create_buckets.py

.PHONY: help setup build test lint up down clean deploy docs
