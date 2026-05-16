# VFX MCP Setup — контекст сесії

## Хто я
Senior CG-artist Plarium, Houdini 21.0.596 + Nuke 16.0v5.
Локальна Win (юзер gamai) ←VPN Loky VPD→ Робоча Win PC-137 (юзер Admin).

## Топологія
- Локальна: 192.168.72.194 (Ethernet) + 10.10.11.41 (VPN, СТАБІЛЬНА)
- Робоча: 10.10.10.31 — там Houdini + продакшен інфра
- VPN не приватний: у 10.10.10.x ферма, ftrack, машини колег. Голий 0.0.0.0 без allowlist неприйнятний.

## Стан інфри (готово)
- Claude Desktop на локальній (поставлено)
- OpenSSH Server на робочій: працює, аліас `ssh pc137`, ключ `~/.ssh/id_ed25519_pc137`, IdentitiesOnly yes
- Firewall на робочій: правило `OpenSSH-Server-In-TCP-VPN-Only` пускає тільки 10.10.11.41:22
- Репо `capoom/houdini-mcp` склонований у `C:\houdini-mcp\` на робочій
- Плагін у `C:\Users\Admin\Documents\houdini21.0\scripts\python\houdinimcp\` — звідти Houdini імпортує
- Sandbox-сцена: `C:/houdini_mcp_sandbox/houdiniworkscene_cld.hip` (481 нода)
- Плагін стартує: `import houdinimcp; houdinimcp.start_server()` → слухає 127.0.0.1:9876, відповідає JSON
- Audit-log: `C:\Users\Admin\houdini_mcp_audit.log`
- Бекапи зроблено: `C:\Users\gamai\backups\local_2026-05-16_2139` та `C:\Users\Admin\backups\pc137_2026-05-16_2140`

## ВАЖЛИВО — стан файлів плагіна
Дві копії, ХЕШІ РІЗНІ:
- `C:\houdini-mcp\server.py` (репо) — містить `from PySide2 import...`, тобто фікс PySide6 сюди НЕ доїхав
- `C:\Users\Admin\Documents\houdini21.0\scripts\python\houdinimcp\server.py` (runtime, який Houdini імпортує)

Невідомо який з них містить актуальні правки (PySide6, audit-log, видалення execute_code/modify_node/delete_node з диспатчера).
ПЕРША ДІЯ Claude Code: через `ssh pc137` прочитати обидва файли, звірити, з'ясувати правду.

## Що не працює (НЕ КОПАТИ)
SSH-тунель `ssh -L 9876:127.0.0.1:9876` — Windows OpenSSH quirk з loopback forwarding під SYSTEM. Витратили багато часу. Рішення — НЕ тунель.

## Поточний план
1. З'ясувати який server.py справжній (звірити з тим що в Houdini)
2. Прибрати auto-start з `__init__.py` (зараз `initialize_plugin()` стартує плагін при імпорті — небажано)
3. Додати `host` параметр у `start_server()` (`__init__.py`) для пробросу в `HoudiniMCPServer(host=...)`
4. Запатчити правильний server.py:
   - Константа вгорі: `ALLOWED_CLIENTS = {'127.0.0.1', '10.10.11.41'}`
   - У `_process_server()` після `self.client, address = self.socket.accept()` — фільтр по `address[0]`
   - Чужі IP: лог `BLOCKED_IP` у audit, `client.close()`, не зберігати в `self.client`
5. Reload плагіна в Houdini Python Shell (юзер робить ВРУЧНУ — Houdini зона користувача)
6. `Test-NetConnection 10.10.10.31 -Port 9876` з локальної — має бути True
7. Прямий тест get_scene_info на 10.10.10.31:9876 без тунелю
8. Bridge `houdini_mcp_server.py` на локальну з hardcoded host = `10.10.10.31`
9. Claude Desktop config → перший end-to-end

## Що вже зроблено в плагіні (НЕ ПОВТОРЮВАТИ)
- Видалено з диспатчера: `execute_code`, `modify_node`, `delete_node` (методи в класі залишились)
- Audit-log пише в `~/houdini_mcp_audit.log` — інлайн-блок у обробці команди, не функція
- Бекап: `C:\houdini-mcp\server.py.orig`

## Файловий workflow на робочій (стиль користувача)
- Малі правки: `Set-Content` через PowerShell, sed-style
- Великі патчі: PowerShell here-string `@'...'@ | Set-Content` потім `& hython.exe скрипт.py`
- Syntax check: `& "C:\Program Files\Side Effects Software\Houdini 21.0.596\bin\hython.exe" -c "import ast; ast.parse(open('...').read()); print('OK')"`

## Жорсткі правила для Claude Code
- Перед кожною командою кажи: машина (локальна/робоча), шелл (PowerShell/cmd/Houdini Python Shell), права (звичайний/адмін), чи має Houdini бути запущений
- Не запускати/закривати Houdini — це робить юзер вручну
- Не міняти прод-сцени, тільки sandbox `C:/houdini_mcp_sandbox/`
- Зміни runtime-копії плагіна — після кожної правки робити бекап `.orig` поряд
- `ssh pc137` — основний канал на робочу
- VPN-IP 10.10.11.41 — допустима для зовнішнього доступу до 9876
