#!/usr/bin/env python3
"""Vypne podsvícení přes NC kontakt relé: BCM GPIO21 = HIGH."""
import argparse
import os
import shutil
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Vypíše příkaz bez změny GPIO.")
    args = parser.parse_args(argv)
    command = ["pinctrl", "set", "21", "op", "dh"]
    if args.dry_run:
        print(" ".join(command))
        return 0
    if os.geteuid() != 0:
        print("Spusť skript přes sudo python3.", file=sys.stderr)
        return 1
    binary = shutil.which("pinctrl")
    if binary is None:
        print("Chybí pinctrl; nainstaluj balík raspi-utils.", file=sys.stderr)
        return 1
    command[0] = binary
    try:
        subprocess.run(command, check=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as error:
        print(f"Nastavení GPIO21 selhalo: {error}", file=sys.stderr)
        return 1
    print("GPIO21 = HIGH; podsvícení OFF při zapojení přes NC kontakt relé.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
