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
Bridge: houdini_mcp_server.py (локальна, .venv)
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
├── BACKLOG.md                  ← живий список done / TODO / known issues
├── .gitignore
├── houdini_mcp_server.py       ← Bridge MCP server (host=10.10.10.31)
├── .venv/                      ← Python 3.14 venv (gitignored)
├── plugin/
│   └── server.py               ← Канонічна локальна копія runtime-плагіна
├── docs/
│   └── SCENE_ANALYSIS.md       ← Дамп реальної production сцени, parm vocabulary
├── notes/
│   ├── README.md               ← Як працює CD ↔ CC inbox
│   └── cc_inbox.md             ← (з'являється коли CD пише через forward_to_cc)
├── scripts/
│   └── deploy_plugin.sh        ← Backup + scp + reminder для plugin/server.py → pc137
├── patches/                    ← Старі PS1 патчі (historical)
├── upstream/                   ← Reference clone capoom/houdini-mcp
└── .claude/                    ← Claude Code memory (gitignored)
```

## Безпека (що зроблено)

### IP allowlist
- `ALLOWED_CLIENTS = {'127.0.0.1', '10.10.11.41'}` в `plugin/server.py`
- Чужі IP → лог `BLOCKED_IP` в `~/houdini_mcp_audit.log` + close
- Audit-log на pc137: `C:\Users\Admin\houdini_mcp_audit.log`

### Hardened dispatcher
Знято з handlers (методи в класі залишились, але не маршрутизуються):
- `execute_code` — довільне виконання Python в Houdini
- `modify_node` — broad-set параметрів нод
- `delete_node` — видалення нод

Натомість додано вузький **`set_node_parameter`** з `SAFE_PARMS` whitelist (transforms, базова геометрія, флаги — див. `plugin/server.py`).

### Auto-start вимкнено
`import houdinimcp` сам не стартує сервер. Запуск вручну (shelf-button `Start MCP` або в Python Shell):
```python
import houdinimcp
houdinimcp.start_server(host='0.0.0.0')  # для доступу ззовні
```

## Доступні MCP tools

Поточний список (визначений в `houdini_mcp_server.py`):

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

Після змін у `plugin/server.py`:
```bash
./scripts/deploy_plugin.sh
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

Якщо змінився `houdini_mcp_server.py` (bridge) — повний рестарт **Claude Desktop**, щоб новий subprocess з новими schemas стартував.

## Kill switches

| Спосіб | Що робить |
|---|---|
| Відключити VPN на локалці | Найшвидший — нічого не доходить до pc137 |
| Shelf-кнопка `Stop MCP` в Houdini | Зупиняє сервер, Houdini лишається |
| SSH-команда вбити процес що тримає 9876 | Nuclear (поки не використовується) |

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
- **Зміни плагіна:** `plugin/server.py` — канонічна копія, deploy через `scripts/deploy_plugin.sh`, що сам робить timestamped backup.
- **На вимогу "перевір inbox":** прочитати `notes/cc_inbox.md`, опрацювати накопичене, відмітити що зроблено (`> resolved: <sha>`) або перенести в постійний документ.

## Жорсткі правила

- VPN allowlist + hardened dispatcher треба тримати. Будь-яке розширення capabilities — через нову narrow tool, не через повернення `execute_code`.
- Backup плагіна перед кожним deploy (deploy-скрипт це робить).
- Syntax check на pc137 через hython після scp: `& "C:\Program Files\Side Effects Software\Houdini 21.0.596\bin\hython.exe" -m py_compile <path>`
- SSH-тунель `ssh -L 9876:127.0.0.1:9876` не працює (Windows OpenSSH quirk з loopback forwarding під SYSTEM). Рішення — прямий TCP через VPN з allowlist.
