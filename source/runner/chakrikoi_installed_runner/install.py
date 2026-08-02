"""Install the packaged runner as a per-user auto-start service."""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
from pathlib import Path


def linux_install(binary: Path, bootstrap: Path) -> None:
    target = Path.home() / ".local/bin/chakrikoi-runner"
    unit = Path.home() / ".config/systemd/user/chakrikoi-runner.service"
    target.parent.mkdir(parents=True, exist_ok=True)
    unit.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(binary, target)
    unit.write_text(
        "[Unit]\nDescription=Chakri Koi local code runner\n"
        "[Service]\nExecStart=%h/.local/bin/chakrikoi-runner --bootstrap " + str(bootstrap) + "\n"
        "Restart=on-failure\nRestartSec=3\n"
        "[Install]\nWantedBy=default.target\n",
        encoding="utf-8",
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "chakrikoi-runner.service"], check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--bootstrap", type=Path, required=True)
    arguments = parser.parse_args()
    if platform.system() != "Linux":
        raise SystemExit("This draft includes a Linux installer. Add LaunchAgent and Scheduled Task installers before release.")
    linux_install(arguments.binary, arguments.bootstrap)


if __name__ == "__main__":
    main()
