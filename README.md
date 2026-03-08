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
├── app.py               # DockerDeck main window + all tab builders
├── docker_runner.py     # subprocess wrappers for Docker CLI
├── validation.py        # Input validation & sanitisation
├── ui_components.py     # Reusable widget factories
├── utils.py             # Thread helpers, debounce, notification log, constants
├── actions/
│   ├── containers.py    # Container tab actions
│   ├── images.py        # Image tab actions
│   ├── deploy.py        # Deploy form + validation + presets
│   ├── network_volume.py# Network & Volume tab actions
│   └── registry.py      # Registry login/push/pull (secure credentials)
├── tests/
│   ├── test_validation.py    # ~20 validation tests
│   ├── test_deploy.py        # ~12 build_run_command tests
│   └── test_docker_runner.py # ~8 subprocess smoke tests
├── dockerdeck.spec      # PyInstaller build spec
└── README.md
```

---

## Running Tests

```bash
pip install pytest
cd dockerdeck
pytest tests/ -v
```

Expected: **40 tests pass** in under 5 seconds (no Docker required).

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

Output will be in `dist/DockerDeck` (Linux/macOS) or `dist/DockerDeck.exe` (Windows).

### Platform notes
| Platform | tkinter source | Build command |
|----------|---------------|---------------|
| Windows  | Bundled with Python installer | `pyinstaller dockerdeck.spec` |
| macOS    | python.org installer (not Homebrew) | `pyinstaller dockerdeck.spec` |
| Linux    | `sudo apt install python3-tk` | `pyinstaller dockerdeck.spec` |

> Cross-compilation is not supported by PyInstaller.
> Build on the target OS for best results.

---

## What's New in v3

### Priority 1 — Blockers fixed

| # | Item | Status |
|---|------|--------|
| 1 | Monolithic god class split | ✅ 7 files + actions/ package |
| 2 | docker events actually implemented | ✅ JSON event parsing, targeted refresh |
| 3 | Distributable binary | ✅ PyInstaller spec included |
| 4 | Automated tests | ✅ 40 pytest tests |

### Priority 2 — Strongly recommended

| # | Item | Status |
|---|------|--------|
| 5 | Real-time field validation | ✅ KeyRelease + FocusOut, red indicator dots |
| 6 | Persistent log / notification history | ✅ deque(200) + "📋 Log" viewer |
| 7 | Consistent ttk styling | ✅ Improved (Combobox, Spinbox, Treeview headings) |
| 8 | Version / update check | ✅ GitHub API on startup, toast notification |
| 9 | Password zeroing | ✅ ctypes.memset + del + GC |

### Priority 3 — Polish

| # | Item | Status |
|---|------|--------|
| — | Debounce on validation keystrokes | ✅ Debouncer(250ms) |
| — | Copy command to clipboard | ✅ Deploy + Terminal output panes |
| — | First-run wizard (Docker not found) | ✅ Install links dialog |
| — | Ctrl+R / F5 global refresh | ✅ |
| — | Contrast improvements | ✅ text_disabled color + secondary text |

---

## Security Notes

- Registry passwords are **never** passed as CLI arguments — piped via stdin only (`--password-stdin`)
- Password entry field is **wiped immediately** after reading
- After `communicate()`, the password bytes are overwritten with `ctypes.memset` and deleted
- All deploy fields use **strict allowlist validation** before any subprocess call
- A full command **confirmation dialog** is shown before every `docker run`
- `validate_extra_args` allows only known-safe flags

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+R` | Refresh all views |
| `F5` | Refresh all views |

---

## Presets

Deploy configurations are saved to `~/.dockerdeck_presets.json`.
Use Save / Load / Delete in the Deploy tab.
