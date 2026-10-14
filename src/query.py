"""Exécute un fichier SQL (ou une requête) sur la base et affiche les résultats.

Utilisation :
    python src/query.py sql/03_first_look.sql
    python src/query.py "SELECT count(*) FROM loans"
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DB_PATH  # noqa: E402


def split_statements(sql_text: str) -> list[tuple[str, str]]:
    """Découpe le texte en requêtes ; le titre est le dernier commentaire '--' qui précède."""
    statements, title, buffer = [], "", []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not buffer and not stripped:
            continue
        if not buffer and stripped.startswith("--"):
            if stripped.strip("-= "):
                title = stripped.lstrip("- ").strip()
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statements.append((title, "\n".join(buffer)))
            buffer, title = [], ""
    if "".join(buffer).strip():
        statements.append((title, "\n".join(buffer)))
    return statements


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    arg = sys.argv[1]
    sql_text = Path(arg).read_text(encoding="utf-8") if arg.endswith(".sql") else arg
    con = duckdb.connect(str(DB_PATH), read_only=True)
    for title, statement in split_statements(sql_text):
        if title:
            print(f"\n=== {title}")
        print(con.sql(statement))
    con.close()


if __name__ == "__main__":
    main()
