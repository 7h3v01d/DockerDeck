# DockerDeck — Architecture Guide

> **Scope:** Personal/team local Docker operator console.  
> Not a Docker Desktop replacement. Not a production deployment platform.  
> Its primary identity is: **the safest, clearest local operator console for developers who use Docker daily.**

---

## Folder Responsibilities

```
dockerdeck/
├── main.py                  Entry point. Parses args, configures logging, starts app.
│
├── app.py                   Root Tk window. Builds all tab UI. Wires controllers.
│                            Owns startup sequence: check_docker → events → refresh.
│                            Orchestrates refresh calls. Handles global shortcuts.
│                            DOES NOT own business logic or state.
│
├── services/                Internal service boundary — pure Python, no tkinter
│   ├── result.py            OperationResult model + ErrorKind taxonomy
│   ├── docker_service.py    Real command execution layer (sync/stream/login)
│   ├── state_store.py       Central app state (daemon status, selection, ops)
│   ├── notifications_service.py  Structured notification log + operation events
│   └── settings_service.py  Persistent settings + deploy presets
│
├── controllers/             Feature controllers — bridge services ↔ UI
│   ├── containers_controller.py
│   ├── images_controller.py
│   ├── deploy_controller.py
│   ├── registry_controller.py
│   ├── network_volume_controller.py
│   └── events_service.py    Docker events watcher + daemon health monitor
│
├── actions/                 Legacy business logic (kept for test compatibility)
│   ├── containers.py        → superseded by ContainersController
│   ├── images.py            → superseded by ImagesController
│   ├── deploy.py            Validation + command building (still used directly)
│   ├── network_volume.py    → superseded by NetworkVolumeController
│   └── registry.py          → superseded by RegistryController
│
├── docker_runner.py         Backward-compat shim → delegates to docker_service
├── validation.py            Input allowlist validators (pure functions, no I/O)
├── ui_components.py         Reusable tkinter widget factories
├── utils.py                 Constants (COLORS, FONTS), safe_thread, Debouncer
│
└── tests/
    ├── test_architecture.py  Import boundary enforcement (runs without daemon)
    ├── test_validation.py    Validation unit tests
    ├── test_deploy.py        Deploy logic unit tests
    ├── test_docker_runner.py Docker runner shim tests
    └── test_integration_smoke.py  Integration smoke tests (mocked subprocess)
```

---

## Allowed Dependencies

```
Layer           May Import From
──────────────  ────────────────────────────────────────────────
services/*      stdlib only (no tkinter, no actions, no controllers)
validation.py   stdlib only (no tkinter, no subprocess)
actions/*       docker_runner, validation, utils — NO tkinter
controllers/*   services/*, utils, ui_components (after()), actions/deploy
ui_components   utils (COLORS, FONTS) — NO subprocess, NO services
app.py          All of the above — owns all widget construction
```

**Enforced automatically** by `tests/test_architecture.py`.

---

## Event Flow

```
Docker daemon event
  └── EventsService._events_loop()
        └── _dispatch_event()
              ├── container event → fire _container_cbs
              ├── image event     → fire _image_cbs
              └── ...
                    └── ContainersController._request_refresh()
                          └── (300ms coalesce) → _do_refresh()
                                └── run_sync(["ps", ...])
                                      └── _populate_tree()

User clicks "Stop"
  └── app.py _c_stop()
        └── ContainersController.stop(names)
              └── safe_thread → run_sync(["stop", name])
                    └── OperationResult
                          ├── _write_result() → output console
                          ├── notifications.record_result()
                          └── _request_refresh()
```

---

## State Flow

```
app_state (AppStateStore singleton)
  ├── daemon_status     set by EventsService → UI labels subscribe
  ├── selected_container  set by TreeviewSelect → controllers read
  ├── active_operations   register/complete per operation → status bar
  └── show_all_containers  set by checkbox → ContainersController reads on refresh
```

---

## Threading Rules

1. **Background work** always runs in `safe_thread()` daemon threads.
2. **UI updates** always go through `root.after(0, fn)` — never call tkinter from a background thread.
3. **Refresh coalescing** — each controller has a `_refresh_pending` flag; multiple refresh requests within 300ms produce exactly one tree update.
4. **Cancellation** — all stream operations accept a `threading.Event` stop_event. Set it to cancel. `EventsService.stop()` sets a single `_stop` event that terminates both background loops.
5. **On close** — `app.on_close()` calls `events_service.stop()` and `app_state.cancel_all()` before `destroy()`.

---

## Operation Lifecycle

```
User action
  → Controller validates input
  → Controller calls run_sync() or run_stream() via services/docker_service
  → OperationResult returned
  → Controller calls notifications.record_result(result)
  → Controller calls _write_result() → output console
  → If ok: controller calls _request_refresh()
```

All failures surface through `result.failure_message()` — never raw stderr.

---

## What "stdlib only" Costs

**Gained:**
- Zero installation friction — `python main.py` just works
- No dependency conflicts, no virtual environments
- Easy to distribute as a single zip / PyInstaller binary

**Lost:**
- No `asyncio` — we use `threading` + `root.after()` instead, which is more verbose and less composable
- No rich process management — `subprocess.Popen` with manual watchdog threads instead of `asyncio.create_subprocess_exec`
- No proper state management library — hand-rolled `AppStateStore` instead of something like `dataclasses-json` + reactive bindings
- No type-checking beyond `mypy` on Python stubs

This trade-off is **deliberate**. If the app grows significantly, the right next step is migrating the async process layer to `asyncio` (Python stdlib) before reaching for third-party packages.

---

## Security Model Summary

See [SECURITY.md](SECURITY.md) for the full threat model.

Short version:
- Passwords: stdin-only, best-effort memory wipe, not logged
- Secrets: not persisted anywhere (presets store config, not credentials)
- Input: allowlist-validated before every subprocess call
- Trust boundary: local machine is trusted; DockerDeck is not hardened for multi-user or networked environments
