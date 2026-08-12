# VFX MCP — Houdini ↔ Claude pipeline

## Що це
Pipeline для зв'язку Claude (Desktop / Code) з Houdini через MCP протокол.
Claude Desktop бачить сцену, може створювати ноди, правити whitelisted параметри, рендерити — через VPN на робочу машину.

## Хто я
Senior CG-artist Plarium (Sashok), Houdini 21.0.596 + Nuke 16.0v5. Лайтер. Працюю в `/stage` (LOPs), Arnold + ACES, Plarium pipeline з `pl_*` HDAs.

## Топологія

```
Claude Desktop (локальна)
    ↓ stdio (MCP)
Bridge: houdini/bridge/houdini_mcp_server.py (локальна, .venv)
    ↓ TCP 10.10.10.31:9876
Houdini plugin: houdinimcp/server.py (PC-137, робоча)
    ↓ PySide6 QTimer
Houdini 21.0.596 (сцена, ноди, рендер)
```

- **Локальна:** 192.168.72.194 (Ethernet) + 10.10.11.41 (VPN, стабільна)
- **Робоча PC-137:** 10.10.10.31 — Houdini + продакшен інфра
- **SSH:** `ssh pc137` (ключ `~/.ssh/id_ed25519_pc137`, IdentitiesOnly yes)
- **VPN не приватний:** у 10.10.10.x ферма, ftrack, машини колег — звідси allowlist на плагіні.

## Структура репо

```
vfx-mcp/                        ← git repo (github.com/sandalya/vfx-mcp)
├── README.md                   ← цей файл (читається CD через get_project_context)
├── CLAUDE.md                   ← shared safety doctrine, one copy only
├── BACKLOG.md                  ← живий список done / TODO / known issues
├── .gitignore
├── houdini/
│   ├── CLAUDE.md                ← Houdini-specific rules
│   ├── bridge/houdini_mcp_server.py     ← Bridge MCP server (host=10.10.10.31)
│   ├── plugin/server.py                 ← Канонічна локальна копія runtime-плагіна
│   ├── plugin/HoudiniMCPRender.py
│   └── docs/
│       ├── SCENE_ANALYSIS.md            ← Дамп реальної production сцени, parm vocabulary
│       └── HOUDINI_MCP_REWRITE_PLAN.md  ← Execution plan for the new hmcp/ plugin layer
├── nuke/
│   ├── CLAUDE.md                ← Nuke-specific rules
│   ├── bridge/nuke_mcp_bridge.py        ← Nuke's counterpart bridge (port 9877, see "Nuke MCP bridge" below)
│   └── plugin/nuke_mcp_plugin.py        ← Canonical local copy of the Nuke-side runtime plugin (infra only:
│                                  TCP server, DISPATCH, audit log, MCP control HUD)
├── .venv/                      ← Python 3.14 venv (gitignored)
├── notes/
│   ├── README.md               ← Як працює CD ↔ CC inbox
│   └── cc_inbox.md             ← (з'являється коли CD пише через forward_to_cc)
├── scripts/
│   └── deploy_plugin.sh        ← Backup + scp + reminder для houdini|nuke plugin → pc137
├── patches/                    ← Старі PS1 патчі (historical)
├── upstream/                   ← Reference clone capoom/houdini-mcp
└── .claude/                    ← Claude Code memory (gitignored)

../little_helpers/               ← SEPARATE REPO (github.com/sandalya/little_helpers), checked out as a
                                    sibling directory next to vfx-mcp/, not inside it. THE PRODUCT —
                                    self-contained artist tools (Create Layer Branch / Change Layer
                                    Version / Split Layers), shippable to other compositors on their own;
                                    never imports nuke_mcp_plugin. Its own docs/NUKE_COMP_LAYER_ASSEMBLY.md
                                    and docs/NUKE_PIPELINE_TD_INTEGRATION.md live there too.
                                    deploy_plugin.sh nuke reads it from ../little_helpers.
```

## Безпека (що зроблено)

### IP allowlist
- `ALLOWED_CLIENTS = {'127.0.0.1', '10.10.11.41'}` в `houdini/plugin/server.py`
- Чужі IP → лог `BLOCKED_IP` в `~/houdini_mcp_audit.log` + close
- Audit-log на pc137: `C:\Users\Admin\houdini_mcp_audit.log`

### Hardened dispatcher
Знято з handlers (методи в класі залишились, але не маршрутизуються):
- `execute_code` — довільне виконання Python в Houdini
- `modify_node` — broad-set параметрів нод
- `delete_node` — видалення нод

Натомість додано вузький **`set_node_parameter`** з `SAFE_PARMS` whitelist (transforms, базова геометрія, флаги — див. `houdini/plugin/server.py`).

### Auto-start вимкнено
`import houdinimcp` сам не стартує сервер. Запуск вручну (shelf-button `Start MCP` або в Python Shell):
```python
import houdinimcp
houdinimcp.start_server(host='0.0.0.0')  # для доступу ззовні
```

## Доступні MCP tools

Поточний список (визначений в `houdini/bridge/houdini_mcp_server.py`):

| Tool | Призначення |
|------|----|
| `get_project_context` | Повертає цей README (CD має кликнути на початку чату) |
| `get_scene_info` | Дамп сцени з `max_nodes` + `context_filter` (e.g. `["stage"]`); response містить `truncated` |
| `get_node_info` | Детально по одній ноді; параметри: `max_parms` (cap), `only_non_default` (фільтр що реально налаштовано) |
| `create_node` | Створює ноду; `parameters` dict сетить whitelisted parms одразу |
| `set_node_parameter` | Сетить ОДИН whitelisted parm на існуючій ноді (повертає old/new value) |
| `execute_houdini_code` | ⚠️ зареєстрований у bridge, але плагін зараз блокує — повертає "Unknown command type" |
| `render_single_view` / `render_quad_views` / `render_specific_camera` | OpenGL/Karma рендер (untested через MCP) |
| `forward_to_cc` | Пише структуровану задачу в `notes/cc_inbox.md` для Claude Code |
| `read_cc_inbox` | Читає inbox (для уникнення дублікатів) |
| `viewport_snapshot` | Швидкий OpenGL-grab поточного viewport, повертає inline image |

## Файли на PC-137 (runtime)

| Шлях | Що |
|------|----|
| `C:\Users\Admin\Documents\houdini21.0\scripts\python\houdinimcp\` | Runtime плагін (Houdini імпортує звідси) |
| `C:\houdini_mcp_sandbox\houdiniworkscene_cld.hip` | Sandbox-сцена |
| `C:\Users\Admin\houdini_mcp_audit.log` | Audit log плагіну |

### Backup-и плагіна на PC-137
- `server.py.orig_dispatcher`, `.orig_allowlist` — історичні
- `server.py.pre_setparam` — до додавання set_node_parameter
- `server.py.bak_<YYYYMMDD_HHMMSS>` — створює `scripts/deploy_plugin.sh` при кожному deploy

## Claude Desktop

### Конфіг (UWP / Microsoft Store версія!)
```
C:\Users\gamai\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json
```
**НЕ** `%AppData%\Roaming\Claude\` — це UWP-специфіка.

## Workflow split

| Задача | Де |
|--------|----|
| Аналіз сцени, інспекція нод, set whitelisted parms, render | **Claude Desktop** (MCP tools) |
| Код плагіна/брижа, SSH, git, deploy, інфра-фіксы | **Claude Code** (termінал) |
| Передача задач CD → CC | `forward_to_cc` → `notes/cc_inbox.md` → "перевір inbox" |

## Sync: локальна → PC-137

Після змін у `houdini/plugin/server.py`:
```bash
./scripts/deploy_plugin.sh houdini
```
(робить ssh ping → backup на pc137 → scp → виводить нагадування про reload)

Reload в Houdini після deploy:
- Shelf-button `Stop MCP` → закрий цей Houdini-інстанс → відкрий заново → `Start MCP`
- АБО importlib.reload:
```python
houdinimcp.stop_server()
import importlib, houdinimcp.server
importlib.reload(houdinimcp.server)
importlib.reload(houdinimcp)
houdinimcp.start_server(host='0.0.0.0')
```

Якщо змінився `houdini/bridge/houdini_mcp_server.py` (bridge) — повний рестарт **Claude Desktop**, щоб новий subprocess з новими schemas стартував.

## Kill switches

| Спосіб | Що робить |
|---|---|
| Відключити VPN на локалці | Найшвидший — нічого не доходить до pc137 |
| Shelf-кнопка `Stop MCP` в Houdini | Зупиняє сервер, Houdini лишається |
| SSH-команда вбити процес що тримає 9876 | Nuclear (поки не використовується) |

---

## hmcp connection modes: pc137/VPN vs. local Houdini

The hmcp bridge (`houdini/bridge/hmcp_bridge.py`, port 9878, registered as
`houdini2` in **Claude Code's** MCP config -- not Claude Desktop, which only
has the old `houdini`/9876 entry) reads its target host from the `HMCP_HOST`
env var, defaulting to pc137's VPN address if unset:

```python
HOST = os.environ.get("HMCP_HOST", "10.10.10.31")
```

Two modes, same tools, same plugin code — only the target machine changes:

| Mode | Houdini runs on | `HMCP_HOST` | Deploy with |
|---|---|---|---|
| 1. Remote (default) | pc137, over VPN | unset | `./scripts/deploy_plugin.sh hmcp` |
| 2. Local | this machine (SASHOKPC), Houdini 20.5.278, loopback | `127.0.0.1` | `./scripts/deploy_plugin.sh hmcp-local` |

No plugin-side change is needed for local mode: `hmcp.start_server()` already
binds `0.0.0.0`, and `127.0.0.1` is already in the plugin's `ALLOWED_CLIENTS`.

The plugin's audit/diagnostic log is `hmcp_audit.log` under Houdini's own
prefs dir (`hou.homeHoudiniDirectory()`) — per machine, per user, so each
mode writes locally. `hmcp.status()` in Houdini's Python Shell reports
`running / pump / ticks / client / address / log`; `ticks` must climb between
two calls or the server is listening but deaf (see
`houdini/docs/HMCP_LOCAL_TIMEOUT_TRIAGE.md`).

To switch to local mode:
1. `./scripts/deploy_plugin.sh hmcp-local` (copies the plugin to
   `Documents/houdini20.5/scripts/python/hmcp/` on this machine, py_compiles
   it with the local hython).
2. Open local Houdini, load/create a sandbox scene, press the **`hmcp start`**
   shelf button (below).
3. Edit `~/.claude.json` (this machine: `C:\Users\gamai\.claude.json`) --
   under `projects."C:/Users/gamai/vfx-mcp".mcpServers.houdini2.env`, set:
   `{"HMCP_HOST": "127.0.0.1"}` (the key already exists as an empty `{}`).
4. Restart the Claude Code session (MCP servers are spawned at session
   start; env vars only take effect on a fresh subprocess launch).

### Starting the plugin: use the shelf buttons

`houdini/shelf/hmcp.shelf` ships two tools — **`hmcp start`** (start, or
restart against freshly deployed code: it purges every `hmcp*` module from
`sys.modules` first, so a deploy lands without restarting Houdini) and
**`hmcp stop`**. Both deploy targets copy it into the machine's
`toolbar/` dir; the shelf *tab* has to be added to the shelf set by hand once
per machine (the `+` at the right of the shelf tabs → `hmcp`).

Prefer these over typing `start_server()` in the Python Shell. Shelf tools run
on Houdini's **main thread**; the Python Shell pane does not, and starting the
server from a non-main thread is exactly what made local mode deaf — the
`QTimer` fallback pump never fires there. The current pump
(`hou.ui.addEventLoopCallback`) is immune either way, but the buttons keep it
that way for free, and they also mean a redeploy is one click instead of a
hand-typed reload over RDP.

To go back to mode 1: set that `env` block back to `{}` (or remove
`HMCP_HOST`) and restart Claude Code again.

`scripts/check_contract.py` respects the same `HMCP_HOST` env var, so
`HMCP_HOST=127.0.0.1 ./scripts/check_contract.py` verifies the local plugin
independent of Claude Code/Desktop -- or just `./scripts/check_contract_local.sh`,
a one-line wrapper that already sets `HMCP_HOST` for you.

### Opt-in sandbox for project scenes (not just SANDBOX_ROOT)

`houdini/plugin/hmcp/guards.py`'s write boundary (`is_sandbox_scene`) accepts
a scene either because its `.hip` lives under `c:/houdini_mcp_sandbox/`, or
because the scene itself has a global variable `hmcp = 1` set (Edit >
Variables in Houdini, or `hou.hscript("set -g hmcp = 1")`). That variable is
saved inside the .hip, so a project-tree scene can opt in individually
without being moved into the sandbox folder. Deliberately checked via
`hscript("set")` (the scene's own variable table), not `hou.getenv` --
`getenv` falls back to the OS process environment, which would let an
unrelated ambient env var of the same name satisfy the check.

### Known limitation: image paths in remote mode

`viewport_snapshot` and `render_snapshot` both return a filesystem path
generated by the plugin on whichever machine Houdini is running on. In local
mode (`HMCP_HOST=127.0.0.1`) that path is on this machine, so Claude Code's
Read tool opens it directly. **In remote mode (the default,
`HMCP_HOST=10.10.10.31`), the path is on pc137 -- Claude Code cannot Read it,
since it never receives the image, only the path string.**

This is `HMCP_FEEDBACK_LOOP_PLAN.md` Stage 4, deliberately left undone: the
plan makes it conditional ("do this only if Stage 3 leaves an actual gap"),
and every stage so far (0-3) was live-verified in local mode, so the gap has
not actually bitten yet. The designed fix if/when it does --
`scripts/fetch_render.sh`, a thin `scp` wrapper on the **bridge** side (the
plugin's no-`subprocess` doctrine only applies inside
`houdini/plugin/hmcp/`) -- is fully specified in the plan's Stage 4 section
but not built. Revisit when work actually resumes against pc137 in remote
mode.

---

## Nuke MCP bridge

Second bridge/plugin pair, same shape as the Houdini one above, running
alongside it on a separate port. Written in English per this repo's doc
convention (Ukrainian is for conversation, not for reference docs).

### Topology

```
Claude Desktop / Claude Code (local)
    ↓ stdio (MCP), `uv run`
Bridge: nuke/bridge/nuke_mcp_bridge.py (local, .venv)
    ↓ TCP 10.10.10.31:9877
Nuke plugin: nuke_mcp_plugin.py (PC-137, ~/.nuke/)
    ↓ PySide6 (Nuke 16 is itself a Qt app — no separate process)
Nuke 16.0v5 (script, DAG, hotkey HUDs)
```

- Same VPN path as Houdini (10.10.11.41 ↔ 10.10.10.31), separate port so both plugins run at once.
- `menu.py` on pc137 calls `nuke_mcp_plugin.register_menu()` at Nuke startup — hotkeys/menu items exist on a clean session, no manual step.
- Socket server itself is **manual start only** (mirrors Houdini's "no auto-start" rule) — started/stopped from the MCP HUD (`Ctrl+Shift+T`), not on Nuke launch.
- Audit log on pc137: `C:\Users\Admin\nuke_mcp_audit.log` (every command: timestamp, ip, cmd, payload, ok). Every command also prints live to Nuke's Script Editor for on-the-spot debugging.

### Status: scaffold phase — not hardened yet

Unlike the Houdini plugin, this one has **no IP allowlist and no command
restrictions applied yet**:
- `ALLOWED_CLIENTS = set()` — empty, so `_handle_client` accepts any IP that can reach port 9877.
- `_is_allowed(cmd_type, payload)` unconditionally returns `True`.
- `nuke_execute_code` runs **raw, unsandboxed Python** inside the live Nuke session — intentionally, for now, to unblock the round-trip. It is the Nuke-side equivalent of Houdini's `execute_code`, which is permanently blocked there.

This is a known, deliberate gap while the bridge is still scaffold-only —
not an oversight. Before this plugin is used from anywhere but this
dev loop, it needs the same treatment Houdini already got: an IP
allowlist and a narrow whitelisted command set replacing free-form
`execute_code`. Per the safety rules at the top of this doc, don't
treat `nuke_execute_code` as a stable capability to build on.

### Available MCP tools

Defined in `nuke/bridge/nuke_mcp_bridge.py`, relayed to the matching `cmd_*` handler in `nuke/plugin/nuke_mcp_plugin.py`:

| Tool | Purpose |
|------|---------|
| `nuke_ping` | Liveness check |
| `nuke_get_script_info` | Script name, node count, frame range |
| `nuke_list_nodes` | All nodes, optional `node_class` filter |
| `nuke_get_nodes_in_view` | Nodes inside the current Node Graph viewport (pan/zoom-aware), each flagged `in_view` |
| `nuke_get_selected_nodes` | Current DAG selection; `Read` nodes also report their `file` knob |
| `nuke_get_node_knobs` | Full knob dump (`knob.toScript()`) + inputs, for named nodes or current selection; `only_non_default=True` by default |
| `nuke_get_env` | `os.environ` by prefix; keys matching `KEY`/`TOKEN`/`SECRET`/`PASSWORD`/`PWD`/`CREDENTIAL`/`AUTH`/`COOKIE` (case-insensitive) are redacted — added after a real `FTRACK_API_KEY` leak was caught live |
| `nuke_list_render_dir` | Lists a render-share directory (default `$FTRACK_RENDER_PATH`) from the Nuke/pc137 side — this bridge's own host has no working SMB access to the share |
| `nuke_execute_code` | ⚠️ Raw Python exec, unrestricted — see scaffold-phase warning above |

### Product tools live in the separate `little_helpers` repo, not here

The three artist-facing tools below (Create Layer Branch / Change Layer
Version / Split Layers) are implemented in `little_helpers`
(`github.com/sandalya/little_helpers`, checked out as a sibling directory
next to this repo — see `nuke/CLAUDE.md`), not in `nuke_mcp_plugin.py`.
`nuke_mcp_plugin.py` is dev-zone infra only (TCP server, DISPATCH, audit
log, MCP control HUD) and imports `little_helpers` lazily, from inside two
MCP command handlers (`cmd_get_nodes_in_view`, `cmd_list_render_dir`) —
never the other way around. `little_helpers` is meant to be copy-pasted
into another compositor's `~/.nuke/` on its own, with no MCP/socket/server
code along for the ride; see its own `README.md` for that install path.

Menu registration is split the same way: `little_helpers.register_menu()`
owns the `Little Helpers/...` menu (product only), and
`nuke_mcp_plugin.register_menu()` owns `MCP/Server/...` (dev-only: the
print-test PoC and the MCP control HUD). `menu.py` on pc137 calls both.

### Nuke-native hotkeys (Function 1 / Function 2)

These automate the layer-branch comp pattern documented in
`docs/NUKE_COMP_LAYER_ASSEMBLY.md` in the `little_helpers` repo — read
that doc before touching any of this code. Registered Nuke-side via `little_helpers.register_menu()`
under `Little Helpers/...`, reload-safe (`little_helpers.reload_all()`
runs on every press, by design, so edit → deploy → press hotkey is the
whole dev loop — no Nuke restart needed). An OS-level global hotkey (the
`keyboard` package's low-level keyboard hook) was tried first and
never fired, most likely swallowed by AV/EDR since that hook shape is
exactly what keyloggers use — hence hotkeys live inside Nuke itself.

| Hotkey | Function | What it does |
|--------|----------|---------------|
| `Shift+A` | Function 1 — layer-branch init | Opens a picker HUD listing layer-branches from `little_helpers.nuke_utils.list_render_dir`; picking one calls `little_helpers.layer_branch.build_layer_branch(layer_name)`, which builds the full confirmed 4-Read init template (`ShuffleCopy4/9/11 → Copy16 → ShuffleCopy12 → empty Cryptomatte → Copy24 → StickyNote`), with per-pass version/frame-range auto-resolution and a gap check that flags incomplete sequences on the Read node itself. Optional "Split layers" checkbox (default off): if checked, `run_split_layers()` launches the standalone `little_helpers/split_layers/` tool, unmodified, on the branch's last node right after it's built — same manual layer-picking panel as always, just auto-opened on the right node instead of selected by hand |
| `Shift+E` | Function 2 — version stepping | Opens `_VersionHUD` ("Latest version" / "Version +" / "Version -") acting on selected `Read` nodes, falling back to whatever's visible in the viewport if nothing is selected. Each Read is resolved and bumped independently against its own (layer, pass). Keeps a row of disconnected history Reads in sync alongside the live one (`_HISTORY_COUNTS = {"lights": 1, "beauty": 5}`), and shows a live status panel (OK / outdated / missing-frames tags) |
| `F10` | Split Layers, standalone | Runs the per-lightgroup comp splitter on whatever's currently selected, independent of Function 1 |
| `Ctrl+Shift+T` | MCP HUD (`MCP/Server/...` menu, not `Little Helpers/...`) | Start / Restart / Stop the socket server, shows current status |

### Deploy

`scripts/deploy_plugin.sh` takes a target now: `<houdini|nuke|all>` —
backs up the previous version on pc137 before copying, same as the
Houdini flow. For `nuke`, it deploys `nuke_mcp_plugin.py` to `~/.nuke/`,
then `little_helpers/` (and its `split_layers/` subpackage) — read from
the sibling `../little_helpers` checkout, not from inside this repo —
to `~/.nuke/little_helpers/`, and clears any stale `__pycache__` under
that dir. Reload in a live Nuke session doesn't need a restart: pressing
any of the hotkeys above re-imports the relevant module(s).

### Kill switches

Same options as Houdini: disconnect the local VPN (fastest), or hit
Stop in the MCP HUD (`Ctrl+Shift+T`). There is no OS-level hook to
worry about — see the hotkey note above.

---

## Інструкції для агентів

### Claude Desktop (CD)

**Старт сесії:**
- Виклич `get_project_context` як перший крок у новому чаті — отримуєш цей файл цілком.

**Handoff в CC:**
- **Не дампи знахідки в чат** — використовуй `forward_to_cc(title, body, category)`. Категорії: `bug`, `observation`, `question`, `note`.
  - `bug` — плагін/bridge/інфра defect з repro
  - `observation` — workflow-патерн, parm-ім'я для whitelist, аномалія сцени
  - `question` — щось що не зміг резолвити, треба CC research
  - `note` — будь-який handoff
- **Перед додаванням** виклич `read_cc_inbox` щоб не дублювати.
- **chkp-формат** (`chkp <project> "summary" "deliverables" "context"`) — структурований ticket header, продовжуй використовувати.

**Інспекція сцени:**
- **Початок:** `get_scene_info(context_filter=["stage"], max_nodes=300)` — твоя реальна робоча зона `/stage` (LOPs); `/obj` зараз містить sandbox-сміття від ранніх MCP-тестів.
- **На кожну цікаву ноду:** `get_node_info(path, only_non_default=true)` — повертає тільки те що реально налаштоване, ігноруючи 80%+ defaults. Без цього прапора 600-parm нода (rendersettings) вб'є token budget за один виклик.
- **Якщо `get_node_info` повертає `error` з полем `traceback`** — це конкретний плагінний баг. Зроби `forward_to_cc(category="bug", ...)` з шляхом ноди + traceback. Не пробуй обійти інакше.
- **Великі сцени (300+ нод):** замість дампу всіх нод через MCP скажи Саші запустити `scripts/dump_scene.py` у Houdini Python Shell — це дає `stage_dump.json`+`obj_dump.json` локально на pc137, працює за секунди і не тратить токени.
- **USD-encoded parm-імена** виду `xn__inputsexposure_vya` — це **нормально**. Solaris пише USD-атрибути з name-mangling-ом, hash-суфікси стабільні. Це не баг.

**Робота з сценою:**
- **Bypassed ноди — навмисні.** Це feature flags Саші. Не активуй їх без явного дозволу. Записуй у audit-доку.
- **Не торкатись прод-сцен** — sandbox = `C:/houdini_mcp_sandbox/`, прод = все інше.
- **Аналізуй один шот глибоко** + патерн-інференс для решти. Не дампи кожен шот окремо — patterns однакові, токени марно.

**Vision (показати картинку):**
- `viewport_snapshot()` — швидкий OpenGL-grab поточного viewport, повертається як inline image. Використовуй коли треба ПОКАЗАТИ Саші стан сцени.
- `render_single_view`, `render_specific_camera`, `render_quad_views` теж повертають inline images.

### Claude Code (CC)

- **Перед командами:** машина (локальна/робоча), шелл, права, чи Houdini має бути запущений.
- **Не запускати/закривати Houdini** — це робить юзер вручну.
- **Не міняти прод-сцени** — тільки sandbox `C:/houdini_mcp_sandbox/`.
- **Зміни плагіна:** `houdini/plugin/server.py` — канонічна копія, deploy через `scripts/deploy_plugin.sh`, що сам робить timestamped backup.
- **На вимогу "перевір inbox":** прочитати `notes/cc_inbox.md`, опрацювати накопичене, відмітити що зроблено (`> resolved: <sha>`) або перенести в постійний документ.

## Жорсткі правила

- VPN allowlist + hardened dispatcher треба тримати. Будь-яке розширення capabilities — через нову narrow tool, не через повернення `execute_code`.
- Backup плагіна перед кожним deploy (deploy-скрипт це робить).
- Syntax check на pc137 через hython після scp: `& "C:\Program Files\Side Effects Software\Houdini 21.0.596\bin\hython.exe" -m py_compile <path>`
- SSH-тунель `ssh -L 9876:127.0.0.1:9876` не працює (Windows OpenSSH quirk з loopback forwarding під SYSTEM). Рішення — прямий TCP через VPN з allowlist.
