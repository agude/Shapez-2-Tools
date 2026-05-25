# Shapez 2 Tools

Tools for reading/writing Shapez 2 blueprint files (.spz2bp).

## Project Structure

```
shapez2-tools/
├── src/shapez2_tools/
│   ├── __init__.py
│   ├── blueprint.py    # Core codec
│   └── cli.py          # Command-line interface
├── tests/
│   └── test_blueprint.py
├── pyproject.toml      # uv/hatch config
└── justfile            # Task runner
```

## Blueprints Location

- Blueprints symlink: `~/Projects/shapez_2_blueprints/`
- Actual path: `/mnt/win/c/Users/agude/AppData/LocalLow/tobspr Games/shapez 2/blueprints`

Keep the blueprints folder clean - any subfolder appears as an in-game category.

## Development

```bash
just install    # Install deps
just test       # Run tests
just lint       # Run ruff
just fmt        # Format code
```

## CLI Usage

```bash
just run info path/to/file.spz2bp
just run decode file.spz2bp -o out.json
just run encode out.json -o file.spz2bp
just run icon file.spz2bp --set icon:Platforms null null shape:RuRuRuRu
```

## Blueprint Format

Files: `SHAPEZ2-[version]-[base64(gzip(JSON))]$`

JSON structure:
- `V`: game version (int)
- `BP.$type`: "Island" or "Building"
- `BP.Icon.Data`: 4-element array for icon slots
- `BP.Entries`: building/island placement data

Name is filename-only (no description field in format).

## Goals

1. Organize blueprints (file operations)
2. Edit icons programmatically
3. (Stretch) Blueprint solver/designer
