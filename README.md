# 🐳 DockerDeck v3

**Production-grade Docker GUI** — manage containers, images, networks, volumes,
compose stacks, and registries from a single dark-themed desktop app.

**Zero pip dependencies** — pure Python 3.8+ stdlib (tkinter, subprocess, threading, json, …).

---

## Quick Start

```bash
python main.py
```

> Requires Python 3.8+ with tkinter available.
> On Ubuntu/Debian: `sudo apt install python3-tk`

---

## Project Structure

```
dockerdeck/
├── main.py              # Entry point
├── app.py               # DockerDeck main window + all tab builders (UI only)
├── docker_runner.py     # subprocess wrappers for Docker CLI
├── validation.py        # Input validation & sanitisation (no tkinter)
├── ui_components.py     # Reusable widget factories
├── utils.py             # Thread helpers, debounce, notification log, constants
├── actions/             # Business logic — NO tkinter imports in any file here
│   ├── containers.py    # Container tab actions
│   ├── images.py        # Image tab actions
│   ├── deploy.py        # Deploy form + validation + presets
│   ├── network_volume.py# Network & Volume tab actions
│   └── registry.py      # Registry login/push/pull (secure credentials)
├── tests/
│   ├── test_validation.py    # 38 validation tests
│   ├── test_deploy.py        # 22 build_run_command / validate_field tests
│   └── test_docker_runner.py #  9 subprocess smoke tests (mocked)
├── dockerdeck.spec      # PyInstaller one-file build spec
└── README.md
```

**Architecture rule:** `actions/`, `validation.py`, `docker_runner.py`, and `utils.py`
contain **zero tkinter imports** — all business logic is fully testable without a display.
Only `app.py` and `ui_components.py` import tkinter.

---

## Running Tests

```bash
pip install pytest
cd dockerdeck
pytest tests/ -v
```

Expected: **69 tests pass** in under 5 seconds (no Docker required, no display required).

---

## Building a Distributable Binary (P1 #3)

### Prerequisites
```bash
pip install pyinstaller
```

### Build (all platforms)
```bash
cd dockerdeck
pyinstaller dockerdeck.spec
```

Output: `dist/DockerDeck` (Linux/macOS) or `dist/DockerDeck.exe` (Windows).

### Platform notes
| Platform | tkinter source                      | Notes                        |
|----------|-------------------------------------|------------------------------|
| Windows  | Bundled with Python installer        | Works out of the box         |
| macOS    | python.org installer (not Homebrew)  | Homebrew Python lacks tkinter|
| Linux    | `sudo apt install python3-tk`        | Must install before building |

> Cross-compilation is not supported by PyInstaller — build on the target OS.

---

## What's In v3

### Priority 1 — Blockers

| # | Item                              | Status                                         |
|---|-----------------------------------|------------------------------------------------|
| 1 | Monolithic god class split        | ✅ 7 modules + `actions/` package              |
| 2 | `docker events` actually wired up | ✅ JSON stream, targeted per-type refresh      |
| 3 | Distributable binary              | ✅ `dockerdeck.spec` PyInstaller one-file build|
| 4 | Automated tests                   | ✅ 69 pytest tests, zero Docker/display needed |

### Priority 2 — Pre-release

| # | Item                              | Status                                              |
|---|-----------------------------------|-----------------------------------------------------|
| 5 | Real-time field validation        | ✅ `KeyRelease` + `FocusOut`, red dots + error labels|
| 6 | Persistent notification log       | ✅ `deque(200)` + "📋 Log" viewer in header         |
| 7 | Consistent ttk styling            | ✅ Treeview headings, Combobox, Spinbox themed      |
| 8 | Version / update check            | ✅ GitHub API on startup, toast if newer version    |
| 9 | Password zeroing                  | ✅ `ctypes.memset` + `del` + GC after `communicate`|

### Priority 3 — Polish

| Item                              | Status |
|-----------------------------------|--------|
| Debounce (250ms) on keystrokes    | ✅     |
| Copy command / output to clipboard| ✅ Deploy + Terminal panes |
| First-run wizard (Docker missing) | ✅ Install links dialog    |
| `Ctrl+R` / `F5` global refresh    | ✅     |
| WCAG contrast (`text_disabled`)   | ✅     |

---

## Security Notes

- Registry passwords are **never** passed as CLI arguments — piped via `--password-stdin` only
- Password entry widget is **wiped immediately** before the background thread starts
- After `communicate()`, password bytes are overwritten via `ctypes.memset` and `del`'d
- All deploy fields validated against a **strict allowlist** before any subprocess call
- A **confirmation dialog with full command preview** is shown before every `docker run`
- `validate_extra_args` permits only known-safe flags (explicit allowlist)

---

## Keyboard Shortcuts

| Key      | Action           |
|----------|------------------|
| `Ctrl+R` | Refresh all views|
| `F5`     | Refresh all views|

---

## Presets

Deploy configurations are saved to `~/.dockerdeck_presets.json`.
Use Save / Load / Delete buttons in the Deploy tab.
