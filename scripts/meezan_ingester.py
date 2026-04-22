# -*- coding: utf-8 -*-
"""Ingest parsed Al-Meezan law records into the laws_v2 schema.

Reads: data/meezan_laws/{law_id}/parsed.json
Writes: rows in laws_v2, articles_v2, attachments_v2, subjects_v2,
         law_subjects_v2, law_relationships_v2 (detected refs).

Upsert semantics — laws are upserted on almeezan_id.

Usage:
    python scripts/meezan_ingester.py --ids 9923,2559
    python scripts/meezan_ingester.py --all-parsed
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

ROOT = Path(__file__).parent.parent
LAW_DIR = ROOT / "data" / "meezan_laws"

# Try TCP connection to the docker network IP of legal_db. Fall back to
# exec-based psql via docker stdin if that fails (slower but always works).
_CONN = None
_DOCKER_MODE = False
_DB_HOSTS = (
    os.environ.get("LEGAL_DB_HOST") or "",
    "172.20.0.4",      # default docker network IP for legal_db
    "localhost",
    "127.0.0.1",
    "host.docker.internal",
)


def _conn():
    global _CONN, _DOCKER_MODE
    if _DOCKER_MODE:
        return None
    if _CONN and not _CONN.closed:
        return _CONN
    for host in _DB_HOSTS:
        if not host:
            continue
        try:
            c = psycopg2.connect(
                host=host, port=5432,
                dbname="ragdb", user="raguser",
                password="RAGsecret2024!",
                connect_timeout=3,
            )
            c.autocommit = True
            _CONN = c
            print(f"[db] psycopg2 connected via {host}", file=sys.stderr)
            return c
        except Exception:
            continue
    # Fallback — docker exec mode (once)
    print("[db] falling back to docker exec psql mode", file=sys.stderr)
    _DOCKER_MODE = True
    _CONN = None
    return None


def _quote_lit(v, *, as_jsonb: bool = False):
    """Escape a python value to a PostgreSQL literal.

    as_jsonb=True forces JSON serialization for lists/dicts (use when
    the target column is jsonb — not a text[] array).
    """
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    if as_jsonb or isinstance(v, dict) or (
        isinstance(v, list) and v and isinstance(v[0], (dict, list))
    ):
        s = json.dumps(v if v is not None else [], ensure_ascii=False)
        return "'" + s.replace("'", "''") + "'::jsonb"
    if isinstance(v, (list, tuple)):
        parts = [_quote_lit(x) for x in v]
        return "ARRAY[" + ",".join(parts) + "]::text[]"
    s = str(v).replace("'", "''")
    return "'" + s + "'"


def _pg_exec_docker(sql: str, params: tuple | list = (), *, fetch: bool = False):
    """Execute SQL via docker exec psql stdin (robust fallback)."""
    # Substitute %s with quoted literals
    if params:
        parts = sql.split("%s")
        if len(parts) - 1 != len(params):
            raise RuntimeError(
                f"Placeholder count mismatch: {len(parts)-1} %s vs {len(params)} params"
            )
        rendered = parts[0]
        for i, p in enumerate(params):
            rendered += _quote_lit(p) + parts[i + 1]
    else:
        rendered = sql

    import subprocess
    cmd = [
        "docker", "exec", "-i", "legal_db",
        "psql", "-U", "raguser", "-d", "ragdb",
        "-t", "-A", "-F", chr(31),
    ]
    r = subprocess.run(
        cmd, input=rendered, capture_output=True, text=True,
        check=False, timeout=60, encoding="utf-8",
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"docker psql failed: {r.stderr[:400]}\nSQL: {rendered[:500]}"
        )
    if fetch:
        rows = []
        for line in r.stdout.strip().split("\n"):
            if not line:
                continue
            rows.append(tuple(line.split(chr(31))))
        return rows
    return None


def _pg_exec(sql: str, params: list | tuple | None = None, *, fetch: bool = False):
    global _DOCKER_MODE
    c = _conn()
    if c is None or _DOCKER_MODE:
        return _pg_exec_docker(sql, params or (), fetch=fetch)
    cur = c.cursor()
    try:
        cur.execute(sql, params or ())
        if fetch:
            return cur.fetchall()
        return None
    finally:
        cur.close()


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _legal_domain_of(law_type: str | None, subjects: list[str]) -> str | None:
    """Heuristic mapping to a top-level legal domain."""
    if not law_type and not subjects:
        return None
    blob = " ".join(filter(None, [law_type] + (subjects or [])))
    if any(k in blob for k in ("جزائي", "عقوبات", "جنائي", "مخدرات")):
        return "criminal"
    if any(k in blob for k in ("مدني", "عقود", "التزامات")):
        return "civil"
    if any(k in blob for k in ("أسرة", "شخصية", "حضانة", "طلاق")):
        return "family"
    if any(k in blob for k in ("عمل", "عمال", "خدمة مدنية")):
        return "labor"
    if any(k in blob for k in ("تجار", "شركات", "بنوك", "تمويل")):
        return "commercial"
    if any(k in blob for k in ("إيجار", "عقار")):
        return "real_estate"
    if any(k in blob for k in ("مرور", "سير", "رخصة")):
        return "traffic"
    if any(k in blob for k in ("صحة", "طبي", "دوائية")):
        return "health"
    if any(k in blob for k in ("جمارك", "ضرائب", "ميزانية")):
        return "fiscal"
    if any(k in blob for k in ("جنسية", "إقامة", "تأشيرة")):
        return "immigration"
    return "administrative"


def _pg_batch(sql_script: str) -> str:
    """Run a multi-statement SQL script via docker-exec psql stdin.
    Returns stdout. Raises RuntimeError on failure."""
    import subprocess
    cmd = [
        "docker", "exec", "-i", "legal_db",
        "psql", "-U", "raguser", "-d", "ragdb",
        "-v", "ON_ERROR_STOP=1",
        "-q",
    ]
    r = subprocess.run(
        cmd, input=sql_script, capture_output=True, text=True,
        check=False, timeout=180, encoding="utf-8",
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"psql batch failed:\n{r.stderr[:2000]}\n---\n{r.stdout[-500:]}"
        )
    return r.stdout


def _build_sql_for_law(data: dict, law_id: int) -> str:
    """Generate a single multi-statement SQL script ingesting one law
    and returning nothing (we'll re-query PKs as needed).

    Uses DO blocks + temp variables so we can reference the law's PK
    across multiple inserts without client-side round-trips.
    """
    law = data["law"]
    subject = law.get("subject")
    subjects_list = [subject["name"]] if subject and subject.get("name") else []
    articles = data.get("articles", []) or []
    attachments = data.get("attachments", []) or []
    refs = data.get("all_references", []) or []

    full_text = "\n\n".join(a["text"] for a in articles)
    full_hash = _sha256(full_text) if full_text else None
    law_name = law.get("law_name")
    law_name_norm = re.sub(r"\s+", " ", (law_name or "")).strip()
    legal_domain = _legal_domain_of(law.get("law_type"), subjects_list)
    issue_date = law.get("issue_date") or None
    source_url = law.get("source_url")

    stmts: list[str] = []
    stmts.append("BEGIN;")

    # 1) Subject upsert (if any)
    if subject and subject.get("entry_id"):
        stmts.append(
            f"INSERT INTO subjects_v2 (almeezan_entry_id, name) VALUES "
            f"({subject['entry_id']}, {_quote_lit(subject['name'])}) "
            f"ON CONFLICT (almeezan_entry_id) DO UPDATE SET name=EXCLUDED.name;"
        )

    # 2) Law upsert
    subjects_pg = (
        "ARRAY[" + ",".join(_quote_lit(s) for s in subjects_list) + "]::text[]"
        if subjects_list else "ARRAY[]::text[]"
    )
    stmts.append(
        "INSERT INTO laws_v2 "
        "(almeezan_id, law_type, law_number, law_year, law_name, law_name_normalized, "
        " status, source, source_url, fulltext_url, pdf_url, subjects, legal_domain, "
        " content_hash, issue_date) VALUES ("
        f"{law_id}, "
        f"{_quote_lit(law.get('law_type'))}, "
        f"{_quote_lit(law.get('law_number'))}, "
        f"{_quote_lit(law.get('law_year'))}, "
        f"{_quote_lit(law_name)}, "
        f"{_quote_lit(law_name_norm)}, "
        f"{_quote_lit(law.get('status') or 'unknown')}, "
        f"'almeezan', "
        f"{_quote_lit(source_url)}, "
        f"{_quote_lit(law.get('fulltext_url'))}, "
        f"{_quote_lit(f'https://www.almeezan.qa/LocalPdfLaw.aspx?Target={law_id}&language=ar')}, "
        f"{subjects_pg}, "
        f"{_quote_lit(legal_domain)}, "
        f"{_quote_lit(full_hash)}, "
        f"CAST({_quote_lit(issue_date)} AS DATE)"
        ") ON CONFLICT (almeezan_id) DO UPDATE SET "
        "  law_type            = EXCLUDED.law_type, "
        "  law_number          = EXCLUDED.law_number, "
        "  law_year            = EXCLUDED.law_year, "
        "  law_name            = EXCLUDED.law_name, "
        "  law_name_normalized = EXCLUDED.law_name_normalized, "
        "  status              = EXCLUDED.status, "
        "  source_url          = EXCLUDED.source_url, "
        "  fulltext_url        = EXCLUDED.fulltext_url, "
        "  pdf_url             = EXCLUDED.pdf_url, "
        "  subjects            = EXCLUDED.subjects, "
        "  legal_domain        = EXCLUDED.legal_domain, "
        "  content_hash        = EXCLUDED.content_hash, "
        "  issue_date          = EXCLUDED.issue_date, "
        "  ingested_at         = NOW();"
    )

    # Use a DO block so we can capture law_pk once and re-use it.
    do_stmts: list[str] = []
    do_stmts.append("DECLARE v_law_id INT; v_sub_id INT;")
    do_stmts.append("BEGIN")
    do_stmts.append(
        f"  SELECT id INTO v_law_id FROM laws_v2 WHERE almeezan_id={law_id};"
    )

    # Subject link
    if subject and subject.get("entry_id"):
        do_stmts.append(
            f"  SELECT id INTO v_sub_id FROM subjects_v2 "
            f"WHERE almeezan_entry_id={subject['entry_id']};"
        )
        do_stmts.append(
            "  IF v_sub_id IS NOT NULL THEN "
            "INSERT INTO law_subjects_v2 (law_id, subject_id) VALUES "
            "(v_law_id, v_sub_id) ON CONFLICT DO NOTHING; END IF;"
        )

    # Wipe old children
    do_stmts.append("  DELETE FROM articles_v2    WHERE law_id=v_law_id;")
    do_stmts.append("  DELETE FROM attachments_v2 WHERE law_id=v_law_id;")

    # Insert articles — track unique (law_id, tree_id) constraint
    seen_tree_ids: set[int] = set()
    for pos, a in enumerate(articles, 1):
        refs_a = a.get("referenced_laws") or []
        tree_id = a.get("almeezan_tree_id")
        src_url = (
            f"https://www.almeezan.qa/LawArticles.aspx?"
            f"LawTreeSectionID={tree_id}&lawId={law_id}&language=ar"
            if tree_id else None
        )
        use_tree = None
        if tree_id is not None and tree_id not in seen_tree_ids:
            use_tree = tree_id
            seen_tree_ids.add(tree_id)

        do_stmts.append(
            "  INSERT INTO articles_v2 "
            "(law_id, almeezan_tree_id, article_number, article_number_int, "
            " article_type, parent_hierarchy, text, text_normalized, "
            " referenced_laws, position, content_hash, source_url) VALUES ("
            f"v_law_id, "
            f"{use_tree if use_tree is not None else 'NULL'}, "
            f"{_quote_lit(a.get('article_number'))}, "
            f"{_quote_lit(a.get('article_number_int'))}, "
            f"'article', "
            f"{_quote_lit(a.get('parent_hierarchy'))}, "
            f"{_quote_lit(a['text'])}, "
            f"{_quote_lit(re.sub(r'\\s+', ' ', a['text']).strip())}, "
            f"{_quote_lit(refs_a, as_jsonb=True)}, "
            f"{pos}, "
            f"{_quote_lit(a.get('content_hash'))}, "
            f"{_quote_lit(src_url)}"
            ");"
        )

    # Insert attachments
    seen_att_urls: set[str] = set()
    for seq, att in enumerate(attachments, 1):
        url = att.get("url") or ""
        if not url or url in seen_att_urls:
            continue
        seen_att_urls.add(url)
        if att.get("kind") == "image" and any(
            k in url.lower()
            for k in ("logo", "hukoomi", "app_png", "pr1", "icon", "loading", "favicon")
        ):
            continue
        do_stmts.append(
            "  INSERT INTO attachments_v2 "
            "(law_id, attachment_type, sequence_num, title, file_url, "
            " file_path, file_size, content_hash, mime_type, source_url) VALUES ("
            f"v_law_id, "
            f"{_quote_lit(att.get('kind') or 'file')}, "
            f"{seq}, "
            f"{_quote_lit(url.rsplit('/', 1)[-1][:200])}, "
            f"{_quote_lit(url)}, "
            f"{_quote_lit(att.get('local_path'))}, "
            f"{_quote_lit(att.get('size'))}, "
            f"{_quote_lit(att.get('hash'))}, "
            f"{_quote_lit(att.get('mime'))}, "
            f"{_quote_lit(source_url)}"
            ");"
        )

    do_stmts.append("END;")
    stmts.append("DO $$\n" + "\n".join(do_stmts) + "\n$$;")

    stmts.append("COMMIT;")
    return "\n".join(stmts)


def ingest_law_batch(law_id: int) -> dict:
    """Batched single-docker-exec ingestion — FAST path."""
    parsed_fp = LAW_DIR / str(law_id) / "parsed.json"
    if not parsed_fp.exists():
        return {"error": f"parsed.json missing for {law_id}"}
    with parsed_fp.open(encoding="utf-8") as f:
        data = json.load(f)
    sql = _build_sql_for_law(data, law_id)
    try:
        _pg_batch(sql)
    except Exception as e:
        return {"error": f"ingest failed: {type(e).__name__}: {str(e)[:500]}"}
    return {
        "ok":          True,
        "articles":    len(data.get("articles", [])),
        "attachments": len(data.get("attachments", [])),
        "references":  len(data.get("all_references", [])),
    }


def ingest_law_legacy(law_id: int) -> dict:
    """Insert/update one law + its articles + attachments + subject."""
    parsed_fp = LAW_DIR / str(law_id) / "parsed.json"
    if not parsed_fp.exists():
        return {"error": f"parsed.json missing for {law_id}"}

    with parsed_fp.open(encoding="utf-8") as f:
        data = json.load(f)

    law = data["law"]
    subject = law.get("subject")
    subjects_list = [subject["name"]] if subject and subject.get("name") else []

    # 1) subject upsert
    subject_pk = None
    if subject and subject.get("entry_id"):
        _pg_exec(
            "INSERT INTO subjects_v2 (almeezan_entry_id, name) VALUES (%s, %s) "
            "ON CONFLICT (almeezan_entry_id) DO UPDATE SET name=EXCLUDED.name;",
            (subject["entry_id"], subject["name"]),
        )
        rows = _pg_exec(
            "SELECT id FROM subjects_v2 WHERE almeezan_entry_id=%s;",
            (subject["entry_id"],),
            fetch=True,
        )
        if rows:
            subject_pk = int(rows[0][0])

    # 2) law upsert
    full_text = "\n\n".join(a["text"] for a in data.get("articles", []))
    full_hash = _sha256(full_text) if full_text else None
    law_name = law.get("law_name")
    law_name_norm = re.sub(r"\s+", " ", (law_name or "")).strip()
    legal_domain = _legal_domain_of(law.get("law_type"), subjects_list)
    issue_date = law.get("issue_date") or None
    source_url = law.get("source_url")

    _pg_exec(
        """INSERT INTO laws_v2
        (almeezan_id, law_type, law_number, law_year, law_name, law_name_normalized,
         status, source, source_url, fulltext_url, pdf_url, subjects, legal_domain,
         content_hash, issue_date)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                CAST(%s AS DATE))
        ON CONFLICT (almeezan_id) DO UPDATE SET
          law_type            = EXCLUDED.law_type,
          law_number          = EXCLUDED.law_number,
          law_year            = EXCLUDED.law_year,
          law_name            = EXCLUDED.law_name,
          law_name_normalized = EXCLUDED.law_name_normalized,
          status              = EXCLUDED.status,
          source_url          = EXCLUDED.source_url,
          fulltext_url        = EXCLUDED.fulltext_url,
          pdf_url             = EXCLUDED.pdf_url,
          subjects            = EXCLUDED.subjects,
          legal_domain        = EXCLUDED.legal_domain,
          content_hash        = EXCLUDED.content_hash,
          issue_date          = EXCLUDED.issue_date,
          ingested_at         = NOW();
        """,
        (
            law_id, law.get("law_type"), law.get("law_number"), law.get("law_year"),
            law_name, law_name_norm, law.get("status") or "unknown",
            "almeezan", source_url, law.get("fulltext_url"),
            f"https://www.almeezan.qa/LocalPdfLaw.aspx?Target={law_id}&language=ar",
            subjects_list, legal_domain, full_hash, issue_date,
        ),
    )

    rows = _pg_exec(
        "SELECT id FROM laws_v2 WHERE almeezan_id=%s;",
        (law_id,),
        fetch=True,
    )
    if not rows:
        return {"error": f"failed to resolve law PK for {law_id}"}
    law_pk = int(rows[0][0])

    # 3) subject link
    if subject_pk:
        _pg_exec(
            "INSERT INTO law_subjects_v2 (law_id, subject_id) VALUES (%s,%s) "
            "ON CONFLICT DO NOTHING;",
            (law_pk, subject_pk),
        )

    # 4) articles — wipe & reinsert
    _pg_exec("DELETE FROM articles_v2 WHERE law_id=%s;", (law_pk,))
    for pos, a in enumerate(data.get("articles", []), 1):
        refs = a.get("referenced_laws") or []
        tree_id = a.get("almeezan_tree_id")
        src_url = (
            f"https://www.almeezan.qa/LawArticles.aspx?"
            f"LawTreeSectionID={tree_id}&lawId={law_id}&language=ar"
            if tree_id else None
        )
        try:
            _pg_exec(
                """INSERT INTO articles_v2
                (law_id, almeezan_tree_id, article_number, article_number_int,
                 article_type, parent_hierarchy, text, text_normalized,
                 referenced_laws, position, content_hash, source_url)
                VALUES (%s,%s,%s,%s,'article',%s,%s,%s,%s::jsonb,%s,%s,%s);""",
                (
                    law_pk, tree_id,
                    a.get("article_number"), a.get("article_number_int"),
                    a.get("parent_hierarchy"), a["text"],
                    re.sub(r"\s+", " ", a["text"]).strip(),
                    json.dumps(refs, ensure_ascii=False),
                    pos, a.get("content_hash"), src_url,
                ),
            )
        except psycopg2.errors.UniqueViolation:
            # tree_id duplicate — articles_v2 unique index on (law_id, tree_id);
            # LawView can yield multiple "articles" that map to the same section
            # if the section header repeats. Fall back to insert without tree_id.
            _pg_exec(
                """INSERT INTO articles_v2
                (law_id, article_number, article_number_int, article_type,
                 parent_hierarchy, text, text_normalized, referenced_laws,
                 position, content_hash, source_url)
                VALUES (%s,%s,%s,'article',%s,%s,%s,%s::jsonb,%s,%s,%s);""",
                (
                    law_pk,
                    a.get("article_number"), a.get("article_number_int"),
                    a.get("parent_hierarchy"), a["text"],
                    re.sub(r"\s+", " ", a["text"]).strip(),
                    json.dumps(refs, ensure_ascii=False),
                    pos, a.get("content_hash"), src_url,
                ),
            )

    # 5) attachments
    _pg_exec("DELETE FROM attachments_v2 WHERE law_id=%s;", (law_pk,))
    for seq, att in enumerate(data.get("attachments", []), 1):
        url = att.get("url") or ""
        if att.get("kind") == "image" and any(
            k in url.lower()
            for k in ("logo", "hukoomi", "app_png", "pr1", "icon", "loading", "favicon")
        ):
            continue
        _pg_exec(
            """INSERT INTO attachments_v2
            (law_id, attachment_type, sequence_num, title, file_url,
             file_path, file_size, content_hash, mime_type, source_url)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);""",
            (
                law_pk, att.get("kind") or "file", seq,
                url.rsplit("/", 1)[-1][:200],
                url, att.get("local_path"),
                att.get("size"), att.get("hash"), att.get("mime"),
                source_url,
            ),
        )

    # 6) law-level references
    seen = set()
    for ref in data.get("all_references", []) or []:
        key = (ref["law_number"], ref["law_year"])
        if key in seen:
            continue
        seen.add(key)
        tgt_rows = _pg_exec(
            "SELECT id FROM laws_v2 WHERE source='almeezan' AND "
            "law_number=%s AND law_year=%s LIMIT 1;",
            (ref["law_number"], ref["law_year"]),
            fetch=True,
        )
        tgt_pk = int(tgt_rows[0][0]) if tgt_rows else None
        try:
            _pg_exec(
                """INSERT INTO law_relationships_v2
                (source_law_id, target_law_id, target_law_ref,
                 relationship_type, detected_by, confidence)
                VALUES (%s, %s, %s::jsonb, 'references', 'regex', 0.8)
                ON CONFLICT (source_law_id, target_law_id, relationship_type)
                DO NOTHING;""",
                (
                    law_pk, tgt_pk,
                    json.dumps({"law_number": ref["law_number"],
                                "law_year":   ref["law_year"]}),
                ),
            )
        except Exception:
            pass

    return {
        "ok":          True,
        "law_pk":      law_pk,
        "articles":    len(data.get("articles", [])),
        "attachments": len(data.get("attachments", [])),
        "references":  len(data.get("all_references", [])),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="Comma-separated law IDs")
    ap.add_argument("--all-parsed", action="store_true")
    args = ap.parse_args()

    ids: list[int] = []
    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
    elif args.all_parsed:
        for d in LAW_DIR.iterdir():
            if d.is_dir() and d.name.isdigit():
                if (d / "parsed.json").exists():
                    ids.append(int(d.name))
        ids.sort()
    else:
        print("ERROR: supply --ids or --all-parsed", file=sys.stderr)
        return 2

    ok = 0
    for i, lid in enumerate(ids, 1):
        try:
            r = ingest_law_batch(lid)
            if r.get("ok"):
                ok += 1
                print(
                    f"[{i}/{len(ids)}] {lid}: {r['articles']} articles, "
                    f"{r['attachments']} attachments, {r['references']} refs"
                )
            else:
                print(f"[{i}/{len(ids)}] {lid}: ERROR {r.get('error')}")
        except Exception as e:
            print(f"[{i}/{len(ids)}] {lid}: EXCEPTION {type(e).__name__}: {e}")
    print(f"\n=== ingested {ok}/{len(ids)} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
