import asyncio, asyncpg

async def v():
    conn = await asyncpg.connect("postgresql://raguser:RAGsecret2024!@legal_db:5432/ragdb")
    print("=== BAD-MATCH DIAGNOSIS ===")
    for art in ["49","54","37","41"]:
        rows = await conn.fetch(
            "SELECT DISTINCT law_name FROM chunks WHERE is_active=true AND article_number=$1 AND law_name NOT LIKE $2 LIMIT 10",
            art, "%أحكام محكمة التمييز%")
        print("art=" + art)
        for r in rows: print("    - " + r["law_name"])
        print()
    print("=== VERIFY ARTICLES ===")
    for art, lawp in [
        ("324","%عقوبات%"),("325","%عقوبات%"),("353","%عقوبات%"),
        ("354","%عقوبات%"),("357","%عقوبات%"),("204","%عقوبات%"),
        ("206","%عقوبات%"),("210","%عقوبات%"),("362","%عقوبات%"),
        ("113","%أسرة%"),("120","%أسرة%"),
    ]:
        r = await conn.fetchrow(
            "SELECT content, law_name FROM chunks WHERE is_active=true AND article_number=$1 AND law_name LIKE $2 AND law_name NOT LIKE $3 ORDER BY length(content) DESC LIMIT 1",
            art, lawp, "%التمييز%")
        if r:
            content = r["content"][:100].replace("\n", " ")
            lname = r["law_name"][:30]
            print("  art=" + art + " [" + lname + "]: " + content)
        else:
            print("  art=" + art + ": MISS")
    print()
    rows = await conn.fetch("SELECT DISTINCT law_name FROM chunks WHERE is_active=true AND law_name LIKE $1 LIMIT 6", "%إيجار%")
    print("Rental laws:")
    for r in rows: print("    - " + r["law_name"])
    await conn.close()

asyncio.run(v())
