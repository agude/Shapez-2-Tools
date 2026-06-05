# Shapez 2 Tools

Tools for reading/writing Shapez 2 blueprint files (.spz2bp), plus an in-progress
effort to **lift, verify, and synthesize** blueprints.

## Project Structure

```
shapez2-tools/
├── src/shapez2_tools/
│   ├── blueprint.py    # .spz2bp codec (decode/encode)
│   ├── generator.py    # tile-replication generator + Entity model + render
│   ├── lift.py         # placed blueprint -> machine-level netlist
│   ├── shapes.py       # shape model + absolute machine ops
│   ├── interpret.py    # push shapes through a lifted netlist (verify)
│   ├── router.py       # DEPRECATED A* prototype (not used; ignore)
│   └── cli.py          # CLI entry point
├── tests/              # pytest
├── data/
│   ├── identifiers.json   # game identifiers (icons, buildings, layouts)
│   ├── platforms.json     # platform geometry (seam-aware unit model)
│   ├── reference/         # oracle/fixture blueprints used by tests + generator
│   └── ICONS.md
├── docs/
│   ├── generator-spec.md  # THE PLAN + live status (read §0 first)
│   ├── machines.md        # building footprints/ports + absolute-direction rules
│   └── QUESTIONS.md       # open questions for the user
├── pyproject.toml
└── justfile
```

## Synthesis effort (active work) — read the docs first

**`docs/generator-spec.md` §0 is the source of truth for current status.** It
tracks what's built (codec, generator, lift, shapes, interpret, CLI), the rung
ladder (lift → simulate → re-route → synthesize), and the active blocker. The
north star is intra-platform place-and-route for dense platforms; the easy
single-op platforms are the test harness. `docs/QUESTIONS.md` holds anything
waiting on the user.

## Blueprints Location

- Blueprints symlink: `~/Projects/shapez_2_blueprints/`
- Actual path: `/mnt/win/c/Users/agude/AppData/LocalLow/tobspr Games/shapez 2/blueprints`

Keep the blueprints folder clean - any subfolder appears as an in-game category.
Naming and icon conventions are documented in the blueprints repo's `CLAUDE.md`.

## Development

```bash
just install    # Install deps (uv sync --all-extras)
just test       # Run tests (pytest)
just lint       # Run ruff
just fmt        # Format code
```

## CLI Usage

```bash
just run info path/to/file.spz2bp           # blueprint summary
just run decode file.spz2bp -o out.json     # to JSON
just run encode out.json -o file.spz2bp     # from JSON
just run icon file.spz2bp --set icon:Platforms null null shape:RuRuRuRu
just run gen rotate cw --platform 1x1 -o out.spz2bp   # generate a rotator
just run diff a.spz2bp b.spz2bp             # compare functional entities
just run show file.spz2bp --layer 0         # per-floor ASCII map
just run lift file.spz2bp                   # lift to a netlist + interpret
just run viz file.spz2bp --open             # HTML/SVG visualization (browser)
just run place file.spz2bp -o out.spz2bp    # re-place + re-route via CP-SAT
```

## Blueprint Format

Files: `SHAPEZ2-[version]-[base64(gzip(JSON))]$`

JSON: `V` (game version) · `BP.$type` ("Island"/"Building") · `BP.Icon.Data`
(4 icon slots) · `BP.Entries` (top-level = platforms; each platform's `B.Entries`
= buildings in platform-local coords, `{X, Y, R, L, T}`).

Name is filename-only (no description field in format).

## Status

Done: organize blueprints, edit icons, naming convention (`Quarter` vs
`Full Belt`), icon convention. In progress: the synthesis effort above — see
`docs/generator-spec.md §0`.
