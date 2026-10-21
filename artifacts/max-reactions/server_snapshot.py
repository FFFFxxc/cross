"""Read-only snapshot; never print environment values or session contents."""
import hashlib
import json
import subprocess
from pathlib import Path

root = Path.home() / "cross"
names = ("cross", "cross-before-vpn", "tg-publisher-app-1")
snapshot = {"containers": {}, "files": {}}
for name in names:
    result = subprocess.run([
        "docker", "inspect", "--format",
        "{{.Id}}|{{.State.StartedAt}}|{{.Config.Image}}|{{.HostConfig.NetworkMode}}", name,
    ], capture_output=True, text=True)
    snapshot["containers"][name] = result.stdout.strip() if result.returncode == 0 else None
files = [root / "tg_migrator/telegram.py", root / "pyproject.toml", root / "Dockerfile"]
files.extend(path for path in root.glob(".env*") if path.is_file())
for path in files:
    snapshot["files"][str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
snapshot["socks_status"] = subprocess.run(
    ["systemctl", "is-active", "telegram-socks"], capture_output=True, text=True,
).stdout.strip()
snapshot["cross_volume"] = subprocess.check_output(
    ["docker", "volume", "inspect", "cross-data", "--format", "{{.Name}}"], text=True,
).strip()
print(json.dumps(snapshot, indent=2))
