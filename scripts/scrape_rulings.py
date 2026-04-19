# -*- coding: utf-8 -*-
"""
scrape_rulings.py — سحب جميع أحكام محكمة التمييز من الميزان
يمسح IDs من 1 إلى 2000، يستخرج المبادئ والنصوص، يخزنها مع embeddings
"""
import asyncio, json, re, ssl, time, html as h_mod, urllib.request, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DB_DSN = "postgresql://raguser:RAGsecret2024!@localhost:5432/ragdb"
OLLAMA_URL = "http://localhost:11434/api/embeddings"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

MAX_ID = 2000
DELAY = 1.5  # seconds between requests
PROGRESS_FILE = "scripts/rulings_progress.json"
LOG_EVERY = 50

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    resp = urllib.request.urlopen(req, context=CTX, timeout=25)
    return resp.read().decode('utf-8')

def get_emb(text):
    data = json.dumps({"model": "nomic-embed-text", "prompt": text[:2000]}).encode()
    req = urllib.request.Request(OLLAMA_URL, data=data, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        emb = json.loads(resp.read()).get("embedding", [])
        return "[" + ",".join(f"{x:.8f}" for x in emb) + "]" if emb else None
    except: return None

def clean_html(raw):
    text = re.sub(r'<script[^>]*>.*?</script>', '', raw, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<p[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = h_mod.unescape(text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' +', ' ', text)
    return text

def extract_ruling(ruling_id):
    """Extract ruling metadata, principles, and text from almeezan."""
    result = {"id": ruling_id, "found": False}

    # 1. Get metadata from RulingPage
    try:
        html = fetch(f'https://www.almeezan.qa/RulingPage.aspx?id={ruling_id}&language=ar')
    except:
        return result

    # Extract metadata
    meta_fields = {
        'lblTitle': 'title',
        'lblNumber': 'number',
        'lbldate': 'date',
        'lblcardtype': 'chamber',
    }
    for html_id, key in meta_fields.items():
        m = re.search(rf'id="ContentPlaceHolder1_{html_id}"[^>]*>(.*?)</span>', html, re.DOTALL)
        if m:
            result[key] = re.sub(r'<[^>]+>', '', m.group(1)).strip().split('\n')[0].strip()

    title = result.get('title', '')
    if not title or len(title) < 5 or 'محكمة' not in title:
        return result

    result['found'] = True

    # Extract RulingView link
    view_match = re.search(r'RulingView\.aspx\?opt&RulID=(\d+)', html)
    view_id = view_match.group(1) if view_match else str(ruling_id)

    # Extract keywords/principles from RulingPage
    # Keywords are in the format: "حكم" وصف الحكم ". معارضة "..."
    text_from_page = clean_html(html)
    lines = [l.strip() for l in text_from_page.split('\n') if l.strip() and len(l.strip()) > 20]

    # Find principle lines (numbered with parentheses)
    principles = []
    for line in lines:
        # Match patterns like: ) 1 ( حكم "..."
        if re.match(r'\)\s*\d+\s*\(', line) or re.match(r'\(\s*\d+\s*\)', line):
            principles.append(line.strip())
        # Or lines that look like principles (short, legal keywords)
        elif len(line) < 300 and any(k in line for k in ['شرطه', 'أساسه', 'أثره', 'علته', 'مناطه']):
            principles.append(line.strip())

    result['principles'] = principles
    result['keywords'] = title  # The title usually contains keywords

    # 2. Get full text from RulingView
    try:
        time.sleep(0.5)
        view_html = fetch(f'https://www.almeezan.qa/RulingView.aspx?opt&RulID={view_id}&language=ar')
        full_text = clean_html(view_html)
        full_lines = [l.strip() for l in full_text.split('\n') if l.strip() and len(l.strip()) > 30]

        # Find the actual ruling text (starts with بعد الاطلاع or similar)
        ruling_text_lines = []
        in_text = False
        for line in full_lines:
            if any(k in line for k in ['بعد الاطلاع على الأوراق', 'حيث إن الطعن', 'من حيث أن', 'لما كان']):
                in_text = True
            if in_text:
                ruling_text_lines.append(line)
            # Also capture principles section
            if re.match(r'[\)\(]\s*\d+\s*[\)\(]', line):
                if not in_text:
                    principles.append(line)

        result['full_text'] = '\n'.join(ruling_text_lines) if ruling_text_lines else ''
        result['full_text_length'] = len(result['full_text'])

    except Exception as e:
        result['full_text'] = ''
        result['view_error'] = str(e)[:100]

    # Parse court and chamber from title
    if 'الجنائية' in title or 'جنائي' in title:
        result['domain'] = 'جنائي'
    elif 'المدنية' in title or 'التجارية' in title or 'مدني' in title:
        result['domain'] = 'مدني'
    elif 'الأحوال' in title or 'أسرة' in title:
        result['domain'] = 'أسري'
    else:
        result['domain'] = 'عام'

    # Parse ruling year
    year_match = re.search(r'/\s*(\d{4})', title)
    result['year'] = year_match.group(1) if year_match else ''

    return result


def chunk_ruling(ruling):
    """Split a ruling into searchable chunks."""
    chunks = []
    rid = ruling['id']
    title = ruling.get('title', '')
    number = ruling.get('number', '').replace('الرقم:', '').strip()
    year = ruling.get('year', '')
    domain = ruling.get('domain', 'عام')
    chamber = ruling.get('chamber', '')

    # Chunk 1: Each principle as separate chunk (MOST IMPORTANT)
    for i, principle in enumerate(ruling.get('principles', [])):
        if len(principle) > 30:
            chunks.append({
                "law_name": f"أحكام محكمة التمييز — {domain}",
                "law_number": number,
                "law_year": year,
                "article_number": f"مبدأ-تمييز-{rid}-{i+1}",
                "content": f"مبدأ قضائي — محكمة التمييز ({chamber}) — الطعن رقم {number}/{year}:\n{principle}",
                "domain": domain,
            })

    # Chunk 2: Summary (title + metadata + first principle)
    summary_parts = [title]
    if ruling.get('date'):
        summary_parts.append(f"تاريخ الجلسة: {ruling['date']}")
    if ruling.get('principles'):
        summary_parts.append("المبادئ: " + " | ".join(p[:100] for p in ruling['principles'][:3]))
    summary = '\n'.join(summary_parts)
    if len(summary) > 50:
        chunks.append({
            "law_name": f"أحكام محكمة التمييز — {domain}",
            "law_number": number,
            "law_year": year,
            "article_number": f"حكم-تمييز-{rid}-ملخص",
            "content": summary,
            "domain": domain,
        })

    # Chunk 3+: Full text in 2000-char chunks
    full_text = ruling.get('full_text', '')
    if full_text and len(full_text) > 100:
        # Split into 2000-char chunks
        pos = 0
        chunk_num = 1
        while pos < len(full_text):
            end = min(pos + 2000, len(full_text))
            # Try to split at paragraph boundary
            if end < len(full_text):
                last_break = full_text.rfind('\n', pos, end)
                if last_break > pos + 500:
                    end = last_break
            chunk_text = full_text[pos:end].strip()
            if len(chunk_text) > 50:
                chunks.append({
                    "law_name": f"أحكام محكمة التمييز — {domain}",
                    "law_number": number,
                    "law_year": year,
                    "article_number": f"حكم-تمييز-{rid}-نص-{chunk_num}",
                    "content": chunk_text,
                    "domain": domain,
                })
                chunk_num += 1
            pos = end

    return chunks


async def main():
    import asyncpg
    conn = await asyncpg.connect(DB_DSN)

    # Load progress
    done_ids = set()
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            prog = json.load(f)
            done_ids = set(prog.get('done_ids', []))

    pre_count = await conn.fetchval("SELECT count(*) FROM chunks WHERE is_active=true")
    print(f"BEFORE: {pre_count:,} active chunks | {len(done_ids)} IDs already done")

    stats = {"found": 0, "not_found": 0, "errors": 0, "chunks_inserted": 0,
             "principles": 0, "by_domain": {}, "by_year": {}}

    for rid in range(1, MAX_ID + 1):
        if rid in done_ids:
            continue

        try:
            ruling = extract_ruling(rid)
            done_ids.add(rid)

            if not ruling['found']:
                stats['not_found'] += 1
            else:
                stats['found'] += 1
                domain = ruling.get('domain', 'عام')
                year = ruling.get('year', '?')
                stats['by_domain'][domain] = stats['by_domain'].get(domain, 0) + 1
                stats['by_year'][year] = stats['by_year'].get(year, 0) + 1
                stats['principles'] += len(ruling.get('principles', []))

                # Create and insert chunks
                chunks = chunk_ruling(ruling)
                for chunk in chunks:
                    # Check if exists
                    exists = await conn.fetchval(
                        "SELECT count(*) FROM chunks WHERE article_number=$1 AND is_active=true",
                        chunk['article_number']
                    )
                    if exists > 0:
                        continue

                    emb = get_emb(chunk['content'])
                    if emb:
                        await conn.execute("""
                            INSERT INTO chunks (law_name, law_number, law_year, article_number,
                                              content, embedding, domain, source, is_active)
                            VALUES ($1, $2, $3, $4, $5, $6::vector, $7, 'almeezan', true)
                        """, chunk['law_name'], chunk['law_number'], chunk['law_year'],
                            chunk['article_number'], chunk['content'], emb, chunk['domain'])
                        stats['chunks_inserted'] += 1

        except Exception as e:
            stats['errors'] += 1
            done_ids.add(rid)

        # Progress logging
        if rid % LOG_EVERY == 0:
            total_processed = stats['found'] + stats['not_found'] + stats['errors']
            print(f"  [{rid}/{MAX_ID}] found={stats['found']} | chunks={stats['chunks_inserted']} | "
                  f"principles={stats['principles']} | errors={stats['errors']}")

            # Save progress
            with open(PROGRESS_FILE, 'w') as f:
                json.dump({"done_ids": list(done_ids), "stats": stats}, f)

        time.sleep(DELAY)

    # Final save
    with open(PROGRESS_FILE, 'w') as f:
        json.dump({"done_ids": list(done_ids), "stats": stats}, f)

    post_count = await conn.fetchval("SELECT count(*) FROM chunks WHERE is_active=true")

    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    print(f"  Rulings found:     {stats['found']}")
    print(f"  IDs not found:     {stats['not_found']}")
    print(f"  Errors:            {stats['errors']}")
    print(f"  Principles:        {stats['principles']}")
    print(f"  Chunks inserted:   {stats['chunks_inserted']}")
    print(f"  BEFORE: {pre_count:,} | AFTER: {post_count:,} (+{post_count-pre_count})")
    print(f"\n  By domain: {stats['by_domain']}")
    print(f"  By year: {dict(sorted(stats['by_year'].items()))}")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
