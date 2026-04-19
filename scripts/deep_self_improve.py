#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/deep_self_improve.py
=============================
تحسين ذاتي خارق — 8 مراحل تحلل كل chunk في DB وتستخلص كل قيمة.
يعمل داخل Docker (DB_HOST=db) أو محلياً (DB_HOST=localhost).
"""
import os, sys, json, re, time, logging, asyncio
from datetime import datetime
from pathlib import Path

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_URL = f"postgresql://raguser:RAGsecret2024!@{DB_HOST}:5432/ragdb"
OUT = Path(__file__).resolve().parent / "deep_improve_results"
OUT.mkdir(parents=True, exist_ok=True)
LOG = Path(__file__).resolve().parent / "deep_improve.log"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.FileHandler(str(LOG), encoding="utf-8", mode="w")])
log = logging.getLogger("deep")
# safe stdout
try:
    _sh = logging.StreamHandler(open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False))
    _sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(_sh)
except Exception:
    pass

PRINCIPLE_RES = [
    re.compile(r'من\s+المقرر\s+(?:قانوناً?\s+)?(?:أن|في)[^.]{20,400}\.', re.UNICODE),
    re.compile(r'من\s+المستقر\s+عليه[^.]{20,400}\.', re.UNICODE),
    re.compile(r'(?:والمقرر|والثابت|والمستقر)\s+(?:في\s+)?قضاء[^.]{20,400}\.', re.UNICODE),
    re.compile(r'(?:يدل|مفاده|مؤداه)\s+(?:على\s+)?أن[^.]{20,400}\.', re.UNICODE),
]
REF_RE = re.compile(r'(?:الطعن|طعن)\s*(?:رقم)?\s*:?\s*(\d+)\s*/?\s*(?:لسنة\s*)?(\d{4})', re.UNICODE)
ART_RE = re.compile(r'الماد[ةه]\s*[\(\s]*(\d+)', re.UNICODE)

TOPIC_KW = {
    "إثبات": ["إثبات","دليل","بيّنة","شهادة","قرينة"],
    "إجراءات": ["بطلان","تفتيش","قبض","إجراء","دفع شكلي"],
    "عقوبات": ["عقوبة","جريمة","ركن","قصد جنائي"],
    "عقود": ["عقد","التزام","فسخ","تعويض","شرط جزائي"],
    "ملكية": ["ملكية","حيازة","عقار","تسجيل"],
    "عمل": ["عامل","صاحب عمل","فصل","أجر"],
    "أسرة": ["زوج","طلاق","حضانة","نفقة","ميراث"],
    "تجارة": ["تجاري","شركة","شريك","إفلاس","شيك"],
    "مسؤولية": ["مسؤولية","تقصير","ضرر","خطأ"],
    "طعن": ["طعن","تمييز","نقض","استئناف"],
}

def classify_topic(text):
    for topic, kws in TOPIC_KW.items():
        if any(k in text for k in kws):
            return topic
    return "عام"


# ═══════════════════════════════════════════════════════
# Phase 1: Full DB analysis
# ═══════════════════════════════════════════════════════
async def phase1(pool):
    log.info("=" * 60)
    log.info("Phase 1: Full DB analysis")
    async with pool.acquire() as c:
        total = await c.fetchval("SELECT COUNT(*) FROM chunks WHERE is_active=true")
        laws = await c.fetch("SELECT law_name, COUNT(*) cnt FROM chunks WHERE is_active=true AND law_name IS NOT NULL GROUP BY law_name ORDER BY cnt DESC LIMIT 40")
        chambers = await c.fetch("""
            SELECT CASE WHEN law_name LIKE '%جنائي%' THEN 'جنائي' WHEN law_name LIKE '%مدني%' THEN 'مدني'
                        WHEN law_name LIKE '%أسر%' OR law_name LIKE '%أحوال%' THEN 'أسري' ELSE 'أخرى' END ch, COUNT(*) cnt
            FROM chunks WHERE is_active=true AND law_name LIKE '%أحكام محكمة التمييز%' GROUP BY ch ORDER BY cnt DESC""")
    result = {"total_chunks": total, "laws": [(l["law_name"], l["cnt"]) for l in laws],
              "chambers": [(c["ch"], c["cnt"]) for c in chambers]}
    log.info(f"  Total chunks: {total}")
    log.info(f"  Laws: {len(laws)}")
    for ch, cnt in result["chambers"]:
        log.info(f"  Chamber {ch}: {cnt}")
    return result


# ═══════════════════════════════════════════════════════
# Phase 2: Extract judicial principles
# ═══════════════════════════════════════════════════════
async def phase2(pool):
    log.info("=" * 60)
    log.info("Phase 2: Extract judicial principles")
    async with pool.acquire() as c:
        chunks = await c.fetch("""
            SELECT id, content, law_name FROM chunks WHERE is_active=true
            AND (law_name LIKE '%أحكام محكمة التمييز%' OR content LIKE '%محكمة التمييز%')
            AND length(content) > 200""")
    log.info(f"  Ruling chunks: {len(chunks)}")

    all_p = []
    for ch in chunks:
        content = ch["content"]
        law = ch["law_name"] or ""
        chamber = "جنائي" if "جنائي" in law else ("مدني" if "مدني" in law else ("أسري" if "أسر" in law else "عام"))
        ref_m = REF_RE.search(content)
        ruling_ref = f"طعن {ref_m.group(1)}/{ref_m.group(2)}" if ref_m else ""

        for pat in PRINCIPLE_RES:
            for m in pat.finditer(content):
                txt = m.group(0).strip()
                if 30 < len(txt) < 600:
                    all_p.append({"text": txt, "chamber": chamber, "topic": classify_topic(txt),
                                  "ruling_ref": ruling_ref, "chunk_id": ch["id"]})

    # deduplicate
    seen = set()
    unique = []
    for p in all_p:
        key = p["text"][:80]
        if key not in seen:
            seen.add(key)
            unique.append(p)

    by_topic = {}
    for p in unique:
        by_topic.setdefault(p["topic"], []).append(p)

    log.info(f"  Extracted: {len(all_p)} raw, {len(unique)} unique")
    for t, ps in sorted(by_topic.items(), key=lambda x: -len(x[1])):
        log.info(f"    {t}: {len(ps)}")
    return {"total": len(all_p), "unique": len(unique), "by_topic": {k: len(v) for k, v in by_topic.items()},
            "principles": unique, "by_topic_full": by_topic}


# ═══════════════════════════════════════════════════════
# Phase 3: Cross-reference between laws
# ═══════════════════════════════════════════════════════
async def phase3(pool):
    log.info("=" * 60)
    log.info("Phase 3: Law cross-references")
    LAW_NAMES = ["قانون العقوبات","القانون المدني","قانون العمل","قانون الأسرة","قانون التجارة",
                 "قانون الشركات","الإجراءات الجنائية","قانون المرافعات","الجرائم الإلكترونية"]
    async with pool.acquire() as c:
        chunks = await c.fetch("""
            SELECT content FROM chunks WHERE is_active=true AND law_name LIKE '%أحكام محكمة التمييز%'
            AND length(content) > 300 LIMIT 10000""")
    cross = {}
    for ch in chunks:
        found = [n for n in LAW_NAMES if n in ch["content"]]
        if len(found) >= 2:
            for i, l1 in enumerate(found):
                for l2 in found[i+1:]:
                    k = f"{l1} <> {l2}"
                    cross[k] = cross.get(k, 0) + 1
    top = sorted(cross.items(), key=lambda x: -x[1])[:20]
    log.info(f"  Multi-law chunks analyzed: {len(chunks)}")
    for k, v in top[:10]:
        log.info(f"    {k}: {v}")
    return {"total_analyzed": len(chunks), "cross_references": top}


# ═══════════════════════════════════════════════════════
# Phase 4: Auto-generate answers from top articles
# ═══════════════════════════════════════════════════════
async def phase4(pool, principles_by_topic):
    log.info("=" * 60)
    log.info("Phase 4: Auto-generate answers from top articles")
    idx_path = Path(__file__).resolve().parent / "article_ruling_compact.json"
    index = {}
    if idx_path.exists():
        with open(idx_path, "r", encoding="utf-8") as f:
            index = json.load(f)
    top_arts = sorted(index.items(), key=lambda x: len(x[1]) if isinstance(x[1], list) else 1, reverse=True)[:30]
    new_ans = {}
    for art_key, rulings in top_arts:
        art_num_m = re.search(r'م(\d+)', art_key)
        if not art_num_m:
            continue
        art_num = art_num_m.group(1)
        try:
            async with pool.acquire() as c:
                row = await c.fetchrow(
                    "SELECT content, law_name FROM chunks WHERE is_active=true AND content ~ $1 AND law_name NOT LIKE '%أحكام محكمة التمييز%' LIMIT 1",
                    f"المادة[\\s\\n]+{art_num}([^0-9]|$)")
                if row:
                    # find related principle
                    principle = ""
                    for topic_ps in principles_by_topic.values():
                        for p in topic_ps:
                            if art_num in p.get("text", ""):
                                principle = p["text"][:250]
                                break
                        if principle:
                            break
                    new_ans[art_key] = {
                        "article": row["content"][:400],
                        "law": row["law_name"],
                        "principle": principle,
                        "ruling_count": len(rulings) if isinstance(rulings, list) else 1,
                    }
        except Exception:
            pass
    log.info(f"  Generated: {len(new_ans)} auto-answers")
    return new_ans


# ═══════════════════════════════════════════════════════
# Phase 5: Knowledge graph
# ═══════════════════════════════════════════════════════
async def phase5(pool, principles):
    log.info("=" * 60)
    log.info("Phase 5: Knowledge graph")
    async with pool.acquire() as c:
        art_count = await c.fetchval(
            "SELECT COUNT(*) FROM chunks WHERE is_active=true AND law_name NOT LIKE '%أحكام محكمة التمييز%' AND content ~ 'المادة[\\s\\n]+\\d+'")
        rul_count = await c.fetchval(
            "SELECT COUNT(*) FROM chunks WHERE is_active=true AND law_name LIKE '%أحكام محكمة التمييز%'")
    idx_path = Path(__file__).resolve().parent / "article_ruling_compact.json"
    edges = 0
    if idx_path.exists():
        with open(idx_path, "r", encoding="utf-8") as f:
            idx = json.load(f)
        edges = sum(len(v) if isinstance(v, list) else 1 for v in idx.values())
    result = {"article_nodes": art_count, "ruling_nodes": rul_count, "principle_nodes": len(principles),
              "edges": edges, "total_nodes": art_count + rul_count + len(principles)}
    log.info(f"  Articles: {art_count}, Rulings: {rul_count}, Principles: {len(principles)}, Edges: {edges}")
    return result


# ═══════════════════════════════════════════════════════
# Phase 6: Discover gaps
# ═══════════════════════════════════════════════════════
async def phase6(pool, principles):
    log.info("=" * 60)
    log.info("Phase 6: Discover gaps")
    # Most frequent legal keywords in rulings
    kw_rows = []
    if not kw_rows:
        log.info("  Keyword extraction query failed, using simple approach")
        async with pool.acquire() as c:
            sample = await c.fetch(
                "SELECT content FROM chunks WHERE is_active=true AND law_name LIKE '%أحكام محكمة التمييز%' LIMIT 2000")
        word_freq = {}
        for row in sample:
            words = re.findall(r'[\u0600-\u06FF]{4,}', row["content"])
            for w in words:
                word_freq[w] = word_freq.get(w, 0) + 1
        kw_rows = [{"word": w, "cnt": c} for w, c in sorted(word_freq.items(), key=lambda x: -x[1])[:80]]

    # Filter: only legal-relevant keywords
    LEGAL_KW = {"محكمة","القانون","المادة","الحكم","الطعن","الدعوى","المدعي","المتهم","العقد","التعويض",
                "الضرر","البطلان","الإثبات","الشهادة","الملكية","الإيجار","العمل","الفصل","الطلاق",
                "الحضانة","النفقة","الميراث","الشركة","الشريك","الشيك","التزوير","السرقة","الرشوة"}
    gaps = [{"word": r["word"], "freq": r["cnt"]} for r in kw_rows
            if r["word"] not in LEGAL_KW and r["cnt"] > 20][:20]
    log.info(f"  Potential gaps: {len(gaps)}")
    for g in gaps[:10]:
        log.info(f"    {g['word']}: {g['freq']}")
    return {"gaps": gaps}


# ═══════════════════════════════════════════════════════
# Phase 7: Enrich linkage index with principles
# ═══════════════════════════════════════════════════════
async def phase7(principles):
    log.info("=" * 60)
    log.info("Phase 7: Enrich linkage with principles")
    idx_path = Path(__file__).resolve().parent / "article_ruling_compact.json"
    if not idx_path.exists():
        return {"enriched": 0}
    with open(idx_path, "r", encoding="utf-8") as f:
        index = json.load(f)

    enriched = 0
    for p in principles[:500]:
        arts = ART_RE.findall(p["text"])
        for art_num in arts:
            for key in index:
                if f"م{art_num}" in key:
                    cid = p.get("chunk_id", 0)
                    existing = index[key]
                    if isinstance(existing, list) and cid not in existing:
                        existing.append(cid)
                        enriched += 1
                    break

    out_path = OUT / "enriched_linkage_index.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    # Also try to update original
    try:
        with open(idx_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False)
    except PermissionError:
        log.warning("  Could not update original index (permission denied), saved to enriched_linkage_index.json")
    total_links = sum(len(v) if isinstance(v, list) else 1 for v in index.values())
    log.info(f"  Enriched: {enriched} new links, total: {total_links}")
    return {"enriched": enriched, "total_links": total_links, "total_articles": len(index)}


# ═══════════════════════════════════════════════════════
# Phase 8: Save and report
# ═══════════════════════════════════════════════════════
async def phase8(results):
    log.info("=" * 60)
    log.info("Phase 8: Save and report")

    # Save principles (top 500)
    with open(OUT / "extracted_principles.json", "w", encoding="utf-8") as f:
        json.dump(results.get("principles", [])[:500], f, ensure_ascii=False, indent=2)

    # Save cross-refs
    with open(OUT / "law_cross_references.json", "w", encoding="utf-8") as f:
        json.dump(results.get("cross_refs", {}), f, ensure_ascii=False, indent=2)

    # Save auto-answers
    with open(OUT / "auto_generated_answers.json", "w", encoding="utf-8") as f:
        json.dump(results.get("auto_answers", {}), f, ensure_ascii=False, indent=2)

    # Save gaps
    with open(OUT / "discovered_gaps.json", "w", encoding="utf-8") as f:
        json.dump(results.get("gaps", {}), f, ensure_ascii=False, indent=2)

    # Save knowledge graph stats
    with open(OUT / "knowledge_graph.json", "w", encoding="utf-8") as f:
        json.dump(results.get("kg", {}), f, ensure_ascii=False, indent=2)

    # Copy updated index to Docker
    idx_path = Path(__file__).resolve().parent / "article_ruling_compact.json"
    try:
        import subprocess
        subprocess.run(["docker", "cp", str(idx_path), "legal_app:/app/scripts/article_ruling_compact.json"],
                       capture_output=True, timeout=10)
        log.info("  Copied updated index to Docker")
    except Exception:
        pass

    # Final report
    report = {
        "timestamp": datetime.now().isoformat(),
        "db": results.get("db", {}),
        "principles": {"total": results.get("p_stats", {}).get("total", 0),
                        "unique": results.get("p_stats", {}).get("unique", 0),
                        "by_topic": results.get("p_stats", {}).get("by_topic", {})},
        "cross_refs": {"top_10": results.get("cross_refs", {}).get("cross_references", [])[:10]},
        "auto_answers": len(results.get("auto_answers", {})),
        "knowledge_graph": results.get("kg", {}),
        "gaps": len(results.get("gaps", {}).get("gaps", [])),
        "enrichment": results.get("enrichment", {}),
    }
    with open(OUT / "final_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    log.info(f"\n{'='*60}")
    log.info("FINAL REPORT")
    log.info(f"{'='*60}")
    log.info(f"Principles: {report['principles']['unique']} unique")
    log.info(f"  By topic: {report['principles']['by_topic']}")
    log.info(f"Cross-refs (top): {report['cross_refs']['top_10'][:5]}")
    log.info(f"Auto-answers: {report['auto_answers']}")
    log.info(f"Knowledge graph: {report['knowledge_graph']}")
    log.info(f"Gaps discovered: {report['gaps']}")
    log.info(f"Enrichment: {report['enrichment']}")
    return report


# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════
async def main():
    log.info(f"Started: {datetime.now().isoformat()}")
    import asyncpg
    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=5)
    R = {}
    try:
        R["db"] = await phase1(pool)
        p2 = await phase2(pool)
        R["p_stats"] = {k: v for k, v in p2.items() if k not in ("principles", "by_topic_full")}
        R["principles"] = p2["principles"]
        R["cross_refs"] = await phase3(pool)
        R["auto_answers"] = await phase4(pool, p2.get("by_topic_full", {}))
        R["kg"] = await phase5(pool, p2["principles"])
        R["gaps"] = await phase6(pool, p2["principles"])
        R["enrichment"] = await phase7(p2["principles"])
        await phase8(R)
    except Exception as e:
        log.error(f"Error: {e}", exc_info=True)
    finally:
        await pool.close()
    log.info(f"Finished: {datetime.now().isoformat()}")

if __name__ == "__main__":
    asyncio.run(main())
