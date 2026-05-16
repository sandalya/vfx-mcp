$path = 'C:\Users\Admin\Documents\houdini21.0\scripts\python\houdinimcp\server.py'
$lines = [System.IO.File]::ReadAllLines($path)

# Lines 97-99 (0-indexed: 96-98) are:
#   self.client, address = self.socket.accept()
#   self.client.setblocking(False)
#   print(f"Connected to client: {address}")
# Replace with IP filter block

$newBlock = @(
    '                    self.client, address = self.socket.accept()',
    '                    # --- IP allowlist filter ---',
    '                    if address[0] not in ALLOWED_CLIENTS:',
    '                        import os as _os, datetime as _dt',
    "                        _log_path = _os.path.join(_os.path.expanduser('~'), 'houdini_mcp_audit.log')",
    "                        with open(_log_path, 'a') as _f:",
    '                            _f.write(f"[{_dt.datetime.now().isoformat()}] BLOCKED_IP: {address[0]}:{address[1]}\n")',
    '                        print(f"BLOCKED connection from {address}")',
    '                        self.client.close()',
    '                        self.client = None',
    '                    else:',
    '                        self.client.setblocking(False)',
    '                        print(f"Connected to client: {address}")'
)

$result = @()
$result += $lines[0..95]       # lines 1-96 unchanged
$result += $newBlock            # replacement for lines 97-99
$result += $lines[99..($lines.Length-1)]  # lines 100+ unchanged

[System.IO.File]::WriteAllLines($path, $result, [System.Text.UTF8Encoding]::new($false))
Write-Host "IP filter patched OK - total lines: $($result.Length)"
