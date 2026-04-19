# -*- coding: utf-8 -*-
"""
scrape_sjc.py — سحب مبادئ محكمة التمييز من موسوعة المجلس الأعلى للقضاء
encyclop.sjc.gov.qa — يستخدم Playwright لمحاكاة المتصفح
"""
import json, re, time, sys, io, asyncio, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DB_DSN = "postgresql://raguser:RAGsecret2024!@localhost:5432/ragdb"
OLLAMA_URL = "http://localhost:11434/api/embeddings"

def get_emb(text):
    data = json.dumps({"model": "nomic-embed-text", "prompt": text[:2000]}).encode()
    req = urllib.request.Request(OLLAMA_URL, data=data, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        emb = json.loads(resp.read()).get("embedding", [])
        return "[" + ",".join(f"{x:.8f}" for x in emb) + "]" if emb else None
    except: return None


def scrape_sjc():
    """Use Playwright to scrape SJC encyclopedia."""
    from playwright.sync_api import sync_playwright

    all_principles = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for gcc in [1, 2, 5]:  # gcc=1 civil, gcc=2 criminal, gcc=5 other
            gcc_label = {1: "مدني", 2: "جنائي", 5: "أخرى"}.get(gcc, str(gcc))
            print(f"\n=== Section gcc={gcc} ({gcc_label}) ===")

            try:
                page.goto(f"https://encyclop.sjc.gov.qa/portal1/Menu.aspx?gcc={gcc}", timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)

                # Find "البحث بالموضوع" link (lnkbtnAlpha) for each DataList item
                # ctl01 = محكمة التمييز, ctl02 = محكمة الاستئناف
                for ctl in ["ctl01", "ctl02"]:
                    court = "محكمة التمييز" if ctl == "ctl01" else "محكمة الاستئناف"
                    try:
                        # Click "البحث بالموضوع"
                        selector = f"[id*='DataList1_{ctl}_lnkbtnAlpha']"
                        link = page.query_selector(selector)
                        if not link:
                            print(f"  {court}: link not found")
                            continue

                        link.click()
                        page.wait_for_load_state("networkidle", timeout=15000)
                        time.sleep(2)

                        # Get the page content after click
                        content = page.content()
                        print(f"  {court}: page loaded ({len(content)} chars)")

                        # Extract alphabetical links or topic links
                        # Look for principle content
                        principle_texts = re.findall(r'<td[^>]*>([^<]{50,})</td>', content)
                        print(f"  {court}: found {len(principle_texts)} text blocks")

                        for pt in principle_texts[:100]:  # Limit per section
                            clean = re.sub(r'\s+', ' ', pt).strip()
                            if len(clean) > 30 and any(k in clean for k in ['حكم', 'مبدأ', 'طعن', 'محكمة', 'قانون', 'المادة']):
                                all_principles.append({
                                    "content": clean,
                                    "court": court,
                                    "gcc": gcc,
                                    "gcc_label": gcc_label,
                                })

                        # Try to navigate alphabet letters
                        alpha_links = page.query_selector_all("a[id*='Alpha']")
                        print(f"  {court}: {len(alpha_links)} alphabet links found")

                        # Go back
                        page.go_back()
                        page.wait_for_load_state("networkidle", timeout=10000)
                        time.sleep(1)

                    except Exception as e:
                        print(f"  {court}: ERROR - {str(e)[:80]}")

            except Exception as e:
                print(f"  gcc={gcc}: ERROR - {str(e)[:80]}")

        browser.close()

    return all_principles


async def store_principles(principles):
    """Store extracted principles in database."""
    import asyncpg
    conn = await asyncpg.connect(DB_DSN)

    pre = await conn.fetchval("SELECT count(*) FROM chunks WHERE is_active=true")
    inserted = 0

    for i, p in enumerate(principles):
        art_num = f"sjc-مبدأ-{i+1}"
        exists = await conn.fetchval(
            "SELECT count(*) FROM chunks WHERE article_number=$1 AND is_active=true", art_num
        )
        if exists > 0:
            continue

        content = f"مبدأ قضائي — {p['court']} ({p['gcc_label']}):\n{p['content']}"
        domain = "مدني" if p['gcc'] == 1 else ("جنائي" if p['gcc'] == 2 else "عام")

        emb = get_emb(content)
        if emb:
            await conn.execute("""
                INSERT INTO chunks (law_name, law_number, law_year, article_number,
                                  content, embedding, domain, source, is_active)
                VALUES ($1, $2, $3, $4, $5, $6::vector, $7, 'almeezan', true)
            """, f"مبادئ {p['court']} — {p['gcc_label']}", "0", "2024",
                art_num, content, emb, domain)
            inserted += 1

    post = await conn.fetchval("SELECT count(*) FROM chunks WHERE is_active=true")
    print(f"\nInserted: {inserted} | Before: {pre:,} | After: {post:,}")
    await conn.close()


def main():
    print("=" * 60)
    print("  سحب مبادئ من موسوعة المجلس الأعلى للقضاء")
    print("=" * 60)

    principles = scrape_sjc()
    print(f"\nTotal principles extracted: {len(principles)}")

    if principles:
        asyncio.run(store_principles(principles))
        # Save to file
        with open("scripts/sjc_principles.json", "w", encoding="utf-8") as f:
            json.dump(principles, f, ensure_ascii=False, indent=2)
        print(f"Saved to scripts/sjc_principles.json")
    else:
        print("No principles extracted — SJC site may require interactive browsing")


if __name__ == "__main__":
    main()
