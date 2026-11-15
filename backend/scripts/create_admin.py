"""Create an administrator.

Usage: python -m scripts.create_admin <username> [--role admin|auditor] [--name "Full Name"]
                                       [--engineer ENG-0001]
``--engineer`` links the admin to their own engineer record: they will not be able to approve or
reject their own access requests.
The password is read interactively (or from DCG_ADMIN_PASSWORD for automation).
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from sqlalchemy import select

from app.core.errors import DomainError
from app.db.session import SessionLocal
from app.models import Engineer
from app.models.enums import AdminRole
from app.services.auth import create_admin


def main() -> int:
    parser = argparse.ArgumentParser(description="Crear administrador de DC Guardian")
    parser.add_argument("username")
    parser.add_argument("--role", choices=[r.value for r in AdminRole], default=AdminRole.ADMIN.value)
    parser.add_argument("--name", default=None)
    parser.add_argument("--engineer", default=None, help="ID de ingeniero propio (p. ej. ENG-0001)")
    args = parser.parse_args()

    password = os.environ.get("DCG_ADMIN_PASSWORD")
    if not password:
        password = getpass.getpass("Contraseña (mín. 10 caracteres): ")
        if password != getpass.getpass("Repite la contraseña: "):
            print("Las contraseñas no coinciden.", file=sys.stderr)
            return 1

    with SessionLocal() as db:
        engineer_id = None
        if args.engineer:
            engineer_id = db.execute(
                select(Engineer.id).where(Engineer.engineer_id == args.engineer.strip().upper())
            ).scalar_one_or_none()
            if engineer_id is None:
                print(f"Error: no existe el ingeniero {args.engineer}", file=sys.stderr)
                return 1
        try:
            admin = create_admin(db, args.username, password, args.name or args.username, AdminRole(args.role),
                                 engineer_id=engineer_id)
            db.commit()
        except DomainError as exc:
            print(f"Error: {exc.message}", file=sys.stderr)
            return 1
    print(f"Administrador '{admin.username}' creado con rol {admin.role}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
