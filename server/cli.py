"""Admin CLI. From the repo root:

    .venv\\Scripts\\python -m server.cli init-db
    .venv\\Scripts\\python -m server.cli create-instructor --username prof [--password ...]
    .venv\\Scripts\\python -m server.cli create-section --name "Section A - Fall 2026"
"""

import argparse
import getpass
import sys
import time

from . import db as dbmod
from .config import Settings
from .security import hash_password, new_class_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="server.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db")

    p_instr = sub.add_parser("create-instructor")
    p_instr.add_argument("--username", required=True)
    p_instr.add_argument("--password", default=None)

    p_sec = sub.add_parser("create-section")
    p_sec.add_argument("--name", required=True)

    args = parser.parse_args(argv)
    settings = Settings()
    settings.ensure_dirs()
    dbmod.init_db(settings.db_path)

    if args.cmd == "init-db":
        print(f"database ready at {settings.db_path}")
        return 0

    conn = dbmod.connect(settings.db_path)
    try:
        if args.cmd == "create-instructor":
            password = args.password or getpass.getpass("Password: ")
            try:
                conn.execute(
                    "INSERT INTO users (username, password_hash, role, created_at)"
                    " VALUES (?,?, 'instructor', ?)",
                    (args.username, hash_password(password), time.time()),
                )
                conn.commit()
            except Exception as exc:
                print(f"failed: {exc}")
                return 1
            print(f"instructor '{args.username}' created")
        elif args.cmd == "create-section":
            code = new_class_code()
            conn.execute(
                "INSERT INTO sections (name, class_code, created_at) VALUES (?,?,?)",
                (args.name, code, time.time()),
            )
            conn.commit()
            print(f"section '{args.name}' created — class code: {code}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
