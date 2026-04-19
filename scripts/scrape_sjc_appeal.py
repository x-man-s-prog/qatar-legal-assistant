# -*- coding: utf-8 -*-
"""
scrape_sjc_appeal.py — سحب أحكام ومبادئ محكمة الاستئناف من موسوعة SJC
"""
import urllib.request, ssl, re, urllib.parse, time, json, sys, io, asyncio
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DB_DSN = "postgresql://raguser:RAGsecret2024!@localhost:5432/ragdb"
OLLAMA_URL = "http://localhost:11434/api/embeddings"
BASE_URL = "https://encyclop.sjc.gov.qa"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

def get_emb(text):
    data = json.dumps({"model": "nomic-embed-text", "prompt": text[:2000]}).encode()
    req = urllib.request.Request(OLLAMA_URL, data=data, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        emb = json.loads(resp.read()).get("embedding", [])
        return "[" + ",".join(f"{x:.8f}" for x in emb) + "]" if emb else None
    except: return None

def get_field(html, name):
    m = re.search(rf'name="{re.escape(name)}"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else ''

def fetch_get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    resp = urllib.request.urlopen(req, context=ctx, timeout=25)
    cookies = resp.headers.get_all('Set-Cookie') or []
    cookie_str = '; '.join(c.split(';')[0] for c in cookies)
    return resp.read().decode('utf-8'), cookie_str, resp.geturl()

def fetch_post(url, data, cookie_str, referer):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode('utf-8'),
        headers={'User-Agent': UA, 'Content-Type': 'application/x-www-form-urlencoded',
                 'Cookie': cookie_str, 'Referer': referer})
    resp = urllib.request.urlopen(req, context=ctx, timeout=30)
    return resp.read().decode('utf-8'), resp.geturl()


def scrape_appeal_court():
    """Scrape all appeal court principles from SJC encyclopedia."""
    all_items = []

    # Step 1: Get main menu
    print("Step 1: Loading main menu...")
    page1, cookies, _ = fetch_get(f"{BASE_URL}/portal1/Menu.aspx?gcc=1")
    vs = get_field(page1, '__VIEWSTATE')
    ev = get_field(page1, '__EVENTVALIDATION')
    vg = get_field(page1, '__VIEWSTATEGENERATOR')
    print(f"  VS={len(vs)} EV={len(ev)}")

    # Step 2: Click "البحث بالموضوع" for محكمة الاستئناف (ctl02)
    print("\nStep 2: Navigating to appeal court alphabetical search...")
    time.sleep(2)
    page2, url2 = fetch_post(f"{BASE_URL}/portal1/Menu.aspx?gcc=1", {
        '__EVENTTARGET': 'ctl00$Main$DataList1$ctl02$lnkbtnAlpha',
        '__EVENTARGUMENT': '', '__VIEWSTATE': vs,
        '__VIEWSTATEGENERATOR': vg, '__EVENTVALIDATION': ev,
    }, cookies, f"{BASE_URL}/portal1/Menu.aspx?gcc=1")
    print(f"  Page: {len(page2)} chars | URL: {url2}")

    # Step 3: Find alphabet links (ctl00$Main$DLstAlphabets$ctlXX$lnkAlphabet)
    alpha_targets = re.findall(r"__doPostBack\('(ctl00\$Main\$DLstAlphabets\$ctl\d+\$lnkAlphabet)'", page2)
    # Also get the letter text
    alpha_letters = re.findall(r'DLstAlphabets[^>]+>([^<]+)<', page2)
    alpha_letters = [l.strip() for l in alpha_letters if l.strip()]

    print(f"  Found {len(alpha_targets)} alphabet links: {alpha_letters[:15]}")

    # Step 4: Click each letter and extract topics
    for idx, target in enumerate(alpha_targets):
        letter = alpha_letters[idx] if idx < len(alpha_letters) else f"#{idx}"
        print(f"\n  [{idx+1}/{len(alpha_targets)}] Letter: {letter}")

        time.sleep(2)
        vs2 = get_field(page2, '__VIEWSTATE')
        ev2 = get_field(page2, '__EVENTVALIDATION')
        vg2 = get_field(page2, '__VIEWSTATEGENERATOR')

        if not vs2 or not ev2:
            print("    Skipped - no VIEWSTATE")
            continue

        try:
            page3, url3 = fetch_post(url2, {
                '__EVENTTARGET': target,
                '__EVENTARGUMENT': '', '__VIEWSTATE': vs2,
                '__VIEWSTATEGENERATOR': vg2, '__EVENTVALIDATION': ev2,
            }, cookies, url2)

            # Extract topics/principles from this letter
            # Look for links to detail pages
            details = re.findall(r'href="([^"]*Detail[^"]*)"[^>]*>([^<]+)', page3)
            # Also look for inline principle text
            principle_blocks = re.findall(r'<td[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)</td>', page3, re.DOTALL)
            # And TreeView nodes
            tree_items = re.findall(r'TreeView[^>]*>([^<]+)', page3)
            # Generic text blocks that look like legal content
            legal_blocks = re.findall(r'>([^<]{80,})<', page3)
            legal_blocks = [b.strip() for b in legal_blocks if any(k in b for k in ['طعن', 'حكم', 'محكمة', 'مادة', 'قانون', 'التزام', 'عقد', 'ضرر'])]

            print(f"    Details: {len(details)} | Principles: {len(principle_blocks)} | Legal blocks: {len(legal_blocks)}")

            for text in legal_blocks:
                clean = re.sub(r'\s+', ' ', text).strip()
                if len(clean) > 50:
                    all_items.append({
                        "content": clean,
                        "letter": letter,
                        "court": "محكمة الاستئناف",
                        "source": "sjc_encyclopedia",
                    })

            # Follow detail links if found
            for href, title in details[:20]:  # Limit per letter
                if href.startswith('/') or href.startswith('http'):
                    full_url = href if href.startswith('http') else f"{BASE_URL}{href}"
                else:
                    full_url = f"{BASE_URL}/Portal1/ahkam/{href}"

                try:
                    time.sleep(1)
                    detail_page, _, _ = fetch_get(full_url)
                    # Extract principle text
                    detail_text = re.sub(r'<[^>]+>', ' ', detail_page)
                    detail_text = re.sub(r'\s+', ' ', detail_text).strip()

                    # Find actual legal content
                    for block in re.findall(r'[^.]{100,}\.', detail_text):
                        if any(k in block for k in ['طعن', 'حكم', 'قضت', 'التمييز', 'الاستئناف', 'مبدأ']):
                            all_items.append({
                                "content": block.strip()[:2000],
                                "letter": letter,
                                "court": "محكمة الاستئناف",
                                "source": "sjc_encyclopedia",
                                "title": title.strip(),
                            })
                except:
                    pass

            # Update page2 for next letter click (use current page's VIEWSTATE)
            page2 = page3
            url2 = url3

        except Exception as e:
            print(f"    ERROR: {str(e)[:60]}")

    return all_items


async def store_items(items):
    import asyncpg
    conn = await asyncpg.connect(DB_DSN)
    pre = await conn.fetchval("SELECT count(*) FROM chunks WHERE is_active=true")
    inserted = 0

    for i, item in enumerate(items):
        art_num = f"sjc-استئناف-{i+1}"
        exists = await conn.fetchval("SELECT count(*) FROM chunks WHERE article_number=$1 AND is_active=true", art_num)
        if exists > 0:
            continue

        content = f"مبدأ قضائي — {item['court']}:\n{item['content']}"
        emb = get_emb(content)
        if emb:
            await conn.execute("""
                INSERT INTO chunks (law_name, law_number, law_year, article_number,
                    content, embedding, domain, source, is_active)
                VALUES ($1, $2, $3, $4, $5, $6::vector, $7, 'almeezan', true)
            """, "أحكام محكمة الاستئناف القطرية", "0", "2024",
                art_num, content, emb, "مدني")
            inserted += 1

    post = await conn.fetchval("SELECT count(*) FROM chunks WHERE is_active=true")
    print(f"\nInserted: {inserted} | Before: {pre:,} | After: {post:,}")
    await conn.close()


def main():
    print("=" * 60)
    print("  سحب أحكام محكمة الاستئناف من موسوعة SJC")
    print("=" * 60)

    items = scrape_appeal_court()
    print(f"\n{'='*60}")
    print(f"Total items extracted: {len(items)}")

    if items:
        asyncio.run(store_items(items))
        with open("scripts/sjc_appeal_results.json", "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        print(f"Saved to sjc_appeal_results.json")
    else:
        print("No items extracted")


if __name__ == "__main__":
    main()
