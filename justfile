# Default recipe
default:
    @just --list

# Install dependencies
install:
    uv sync --all-extras

# Run tests
test *args:
    uv run pytest {{ args }}

# Run linter
lint:
    uv run ruff check src tests

# Format code
fmt:
    uv run ruff format src tests
    uv run ruff check --fix src tests

# Run the CLI
run *args:
    uv run shapez2 {{ args }}

# Decode a blueprint to JSON
decode file:
    uv run shapez2 decode "{{ file }}"

# Show blueprint info
info file:
    uv run shapez2 info "{{ file }}"

# Install git pre-commit hook
hooks-install:
    @echo "Installing pre-commit hook..."
    @mkdir -p .git/hooks
    @cp bin/pre-commit.sh .git/hooks/pre-commit
    @chmod +x .git/hooks/pre-commit
    @echo "Pre-commit hook installed."
