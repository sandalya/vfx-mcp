$path = 'C:\Users\Admin\Documents\houdini21.0\scripts\python\houdinimcp\server.py'
$content = [System.IO.File]::ReadAllText($path)

# 1. Add ALLOWED_CLIENTS after imports block
$marker = '# Info about the extension (optional metadata)'
$insert = "# --- SECURITY: IP allowlist ---`r`nALLOWED_CLIENTS = {'127.0.0.1', '10.10.11.41'}`r`n`r`n# Info about the extension (optional metadata)"
$content = $content.Replace($marker, $insert)

# 2. Replace accept block with IP filter
$old = @"
                    self.client, address = self.socket.accept()
                    self.client.setblocking(False)
                    print(f"Connected to client: {address}")
"@

$new = @"
                    self.client, address = self.socket.accept()
                    # --- IP allowlist filter ---
                    if address[0] not in ALLOWED_CLIENTS:
                        import os as _os, datetime as _dt
                        _log_path = _os.path.join(_os.path.expanduser('~'), 'houdini_mcp_audit.log')
                        with open(_log_path, 'a') as _f:
                            _f.write(f"[{_dt.datetime.now().isoformat()}] BLOCKED_IP: {address[0]}:{address[1]}\n")
                        print(f"BLOCKED connection from {address}")
                        self.client.close()
                        self.client = None
                    else:
                        self.client.setblocking(False)
                        print(f"Connected to client: {address}")
"@

$content = $content.Replace($old, $new)

[System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))
Write-Host 'server.py patched OK'
