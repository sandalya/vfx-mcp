# VFX MCP — Houdini ↔ Claude pipeline

## Що це
Pipeline для зв'язку Claude (Desktop/Code) з Houdini через MCP протокол.
Claude Desktop бачить сцену, може створювати ноди, рендерити — через VPN на робочу машину.

## Хто я
Senior CG-artist Plarium, Houdini 21.0.596 + Nuke 16.0v5.

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
- **VPN не приватний:** у 10.10.10.x ферма, ftrack, машини колег

## Структура репо

```
vfx-mcp/                        ← git repo (github.com/sandalya/vfx-mcp)
├── README.md                   ← цей файл
├── .gitignore
├── houdini_mcp_server.py       ← Bridge MCP server (host=10.10.10.31)
├── urls.env                    ← OPUS API ключі (в .gitignore)
├── .venv/                      ← Python 3.14 venv (в .gitignore)
├── remote/                     ← копія runtime-плагіна з PC-137
│   └── houdinimcp/
│       ├── __init__.py         ← start_server(host, port), без auto-start
│       ├── server.py           ← PySide6, allowlist, hardened dispatcher
│       ├── HoudiniMCPRender.py ← рендер-функції
│       └── pyproject.toml
├── upstream/                   ← оригінал з capoom/houdini-mcp (reference)
│   ├── README.md, LICENSE, main.py, pyproject.toml, uv.lock, ...
│   └── ...
├── patches/                    ← PS1 скрипти використані для патчів
│   ├── patch_init.ps1
│   ├── patch_ipfilter.ps1
│   └── patch_server.ps1
└── .claude/                    ← Claude Code memory (в .gitignore)
```

## Безпека (що зроблено)

### IP allowlist
- `ALLOWED_CLIENTS = {'127.0.0.1', '10.10.11.41'}` в `server.py`
- Чужі IP → лог `BLOCKED_IP` в `~/houdini_mcp_audit.log` + close
- Audit-log: `C:\Users\Admin\houdini_mcp_audit.log`

### Hardened dispatcher
Видалено з handlers (методи в класі залишились, але не маршрутизуються):
- `execute_code` — довільне виконання коду
- `modify_node` — зміна параметрів нод
- `delete_node` — видалення нод

### Auto-start вимкнено
`import houdinimcp` більше не стартує сервер автоматично. Запуск вручну:
```python
import houdinimcp
houdinimcp.start_server(host='0.0.0.0')  # для доступу ззовні
```

## Файли на PC-137 (runtime)

| Шлях | Що |
|------|----|
| `C:\Users\Admin\Documents\houdini21.0\scripts\python\houdinimcp\` | Runtime плагін (Houdini імпортує звідси) |
| `C:\houdini-mcp\` | Оригінальний clone capoom/houdini-mcp (застарілий, PySide2) |
| `C:\houdini_mcp_sandbox\houdiniworkscene_cld.hip` | Sandbox-сцена (481 нода) |
| `C:\Users\Admin\houdini_mcp_audit.log` | Audit log |

### Бекапи на PC-137
- `server.py.orig` — до всіх змін
- `server.py.orig_dispatcher` — до видалення execute_code/modify_node/delete_node
- `server.py.orig_allowlist` — до додавання IP-фільтра
- `__init__.py.orig_allowlist` — до зміни start_server()

## Claude Desktop

### Конфіг (UWP / Microsoft Store версія!)
```
C:\Users\gamai\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json
```
**НЕ** `%AppData%\Roaming\Claude\` — це UWP-специфіка.

### Доступні MCP tools (Houdini)
- `get_scene_info` — інфо про сцену
- `create_node` — створення нод
- `get_node_info` — інфо про ноду
- `set_material` — матеріали
- `render_single_view` / `render_quad_view` / `render_specific_camera` — рендер
- `import_opus_url` — імпорт OPUS моделей
- `get_asset_lib_status` — статус бібліотеки ассетів

### Заблоковані (з диспатчера)
- `execute_code`, `modify_node`, `delete_node`

## Workflow

| Задача | Де |
|--------|----|
| Патчити код, SSH, git, налаштування | **Claude Code** (термінал) |
| Працювати з Houdini-сценою | **Claude Desktop** (MCP tools) |
| Щось зламалось | **Claude Code** |

## Запуск плагіна в Houdini Python Shell

```python
import houdinimcp
houdinimcp.start_server(host='0.0.0.0')
```

Зупинка + перезапуск після змін:
```python
houdinimcp.stop_server()
import importlib, houdinimcp.server
importlib.reload(houdinimcp.server)
importlib.reload(houdinimcp)
houdinimcp.start_server(host='0.0.0.0')
```

## Sync: локальна → PC-137

Після зміни файлів в `remote/houdinimcp/`:
```bash
scp remote/houdinimcp/server.py pc137:"C:/Users/Admin/Documents/houdini21.0/scripts/python/houdinimcp/server.py"
scp remote/houdinimcp/__init__.py pc137:"C:/Users/Admin/Documents/houdini21.0/scripts/python/houdinimcp/__init__.py"
```
Потім reload в Houdini Python Shell (див. вище).

## Що не працює (не копати)
SSH-тунель `ssh -L 9876:127.0.0.1:9876` — Windows OpenSSH quirk з loopback forwarding під SYSTEM. Рішення — прямий TCP через VPN з allowlist.

## Файловий workflow на робочій
- Syntax check: `& "C:\Program Files\Side Effects Software\Houdini 21.0.596\bin\hython.exe" -c "import ast; ast.parse(open('...').read()); print('OK')"`
- Не запускати/закривати Houdini — це робить юзер вручну
- Не міняти прод-сцени, тільки sandbox `C:/houdini_mcp_sandbox/`

## Жорсткі правила для Claude Code
- Перед кожною командою: машина (локальна/робоча), шелл, права, чи Houdini має бути запущений
- Не запускати/закривати Houdini
- Не міняти прод-сцени
- Зміни runtime-копії плагіна — бекап `.orig` перед кожною правкою
- `ssh pc137` — основний канал на робочу
