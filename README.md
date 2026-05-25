# shapez2-tools

Tools for reading/writing Shapez 2 blueprint files (.spz2bp).

## Installation

```bash
uv sync --all-extras
```

## Usage

```bash
# Show blueprint info
uv run shapez2 info path/to/file.spz2bp

# Decode to JSON
uv run shapez2 decode file.spz2bp -o out.json

# Encode JSON to blueprint
uv run shapez2 encode out.json -o file.spz2bp

# View/set icon
uv run shapez2 icon file.spz2bp
uv run shapez2 icon file.spz2bp --set icon:Platforms null null shape:RuRuRuRu
```
