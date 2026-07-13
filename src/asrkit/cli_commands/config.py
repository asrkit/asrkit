"""Persistent config CLI command."""
from __future__ import annotations

import sys


def add_parsers(sub) -> None:
    cp = sub.add_parser("config", help="persistent config: keys, default engine, models root")
    cp.set_defaults(_parser=cp)
    csub = cp.add_subparsers(dest="ccmd")
    ck = csub.add_parser("set-key", help="store credentials for a vendor")
    ck.add_argument("vendor")
    ck.add_argument("key", nargs="?", default=None, help="API key (single-key vendors)")
    ck.add_argument("--app-key", default=None, help="app key (dual-key vendors, e.g. doubao)")
    ck.add_argument("--access-key", default=None, help="access key (dual-key vendors)")
    cg = csub.add_parser("get-key", help="show stored credentials for a vendor (masked)")
    cg.add_argument("vendor")
    cs = csub.add_parser("set", help="set a value (default-engine | models-root)")
    cs.add_argument("name", choices=("default-engine", "models-root"))
    cs.add_argument("value")
    csub.add_parser("list", help="show all config (keys masked)")
    csub.add_parser("path", help="print the config file location")


def handle(a) -> int:
    from .. import config

    if a.ccmd == "set-key":
        if not (a.key or a.app_key or a.access_key):
            print("[error] provide a key, or --app-key/--access-key", file=sys.stderr)
            return 1
        config.set_creds(a.vendor, api_key=a.key, app_key=a.app_key, access_key=a.access_key)
        print(f"✓ stored credentials for '{a.vendor}' → {config.path()}", file=sys.stderr)
        print("  note: keys are stored in plaintext (file perms 0600). "
              "Prefer env vars if you'd rather not persist them.", file=sys.stderr)
        return 0
    if a.ccmd == "get-key":
        creds = config.get_creds(a.vendor)
        if not creds:
            print(f"(no stored credentials for '{a.vendor}')")
            return 0
        for k, v in creds.items():
            print(f"{k}: {config.mask(v)}")
        return 0
    if a.ccmd == "set":
        if a.name == "default-engine":
            config.set_default("engine", a.value)
        else:
            config.set_setting("models_root", a.value)
        print(f"✓ {a.name} → {a.value}")
        return 0
    if a.ccmd == "list":
        cfg = config.load()
        print(f"path: {config.path()}")
        print("keys:")
        for vendor, creds in (cfg.get("keys") or {}).items():
            masked = ", ".join(f"{k}={config.mask(v)}" for k, v in creds.items())
            print(f"  {vendor}: {masked}")
        print(f"defaults: {cfg.get('defaults') or {}}")
        print(f"settings: {cfg.get('settings') or {}}")
        return 0
    if a.ccmd == "path":
        print(config.path())
        return 0
    a._parser.print_help()
    return 0
