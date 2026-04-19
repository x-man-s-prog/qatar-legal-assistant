#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/deep_self_train.py — تدريب ذاتي عميق: أنماط أحكام + روابط + دفوع + سوابق
"""
import asyncio, asyncpg, json, re, os, logging
from datetime import datetime
from collections import defaultdict

DB_URL = f"postgresql://raguser:RAGsecret2024!@{os.environ.get('DB_HOST','db')}:5432/ragdb"
OUT = "scripts/self_training_results"
os.makedirs(OUT, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("scripts/self_training.log", encoding="utf-8", mode="w")])
log = logging.getLogger("train")
try:
    import sys
    _sh = logging.StreamHandler(open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False))
    _sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(_sh)
except: pass

ART_RE = re.compile(r'الماد[ةه]\s*[\(\s]*(\d+)\s*[\)\s]*', re.UNICODE)
REF_RE = re.compile(r'(?:الطعن|طعن)\s*(?:رقم)?\s*:?\s*(\d+)\s*/?\s*(\d{4})', re.UNICODE)
PRIN_RE = re.compile(r'(?:من\s+المقرر|المستقر\s+عليه|والثابت\s+في\s+قضاء)[^.]{30,400}\.', re.UNICODE)

TOPIC_KW = {
    "ضرب": ["ضرب","إيذاء","اعتداء","جسدي"], "سرقة": ["سرقة","سرق","اختلس"],
    "شيك": ["شيك","بدون رصيد"], "مخدرات": ["مخدر","حيازة","تعاطي","اتجار"],
    "فصل": ["فصل","إنهاء عقد عمل","تعسفي"], "طلاق": ["طلاق","خلع","تطليق"],
    "حضانة": ["حضانة","محضون"], "إيجار": ["إيجار","مستأجر","إخلاء"],
    "تعويض": ["تعويض","ضرر","مسؤولية"], "شركة": ["شركة","شريك","مساهم"],
    "تزوير": ["تزوير","محرر","مزور"], "قتل": ["قتل","وفاة"],
    "تشهير": ["تشهير","قذف","سب"], "تفتيش": ["تفتيش","قبض","ضبط","إذن"],
}
RESULT_RE = {
    "قبول": re.compile(r'(?:قبول|قبلت|تقبل)\s+(?:الطعن|الاستئناف|الدعوى)', re.UNICODE),
    "رفض": re.compile(r'(?:رفض|رفضت|ترفض)\s+(?:الطعن|الاستئناف|الدعوى)', re.UNICODE),
    "نقض": re.compile(r'(?:نقض|نقضت)\s+(?:الحكم)', re.UNICODE),
    "تأييد": re.compile(r'(?:تأييد|أيّد|تؤيد)\s+(?:الحكم)', re.UNICODE),
    "براءة": re.compile(r'(?:براءة|ببراءة)', re.UNICODE),
    "إدانة": re.compile(r'(?:إدانة|أدانت|بإدانة)', re.UNICODE),
}
DEFENSE_RE = {
    "بطلان_القبض": re.compile(r'بطلان\s+(?:القبض|إجراءات\s+القبض)', re.UNICODE),
    "بطلان_التفتيش": re.compile(r'بطلان\s+(?:التفتيش|إجراء)', re.UNICODE),
    "انتفاء_القصد": re.compile(r'(?:انتفاء|عدم\s+توافر)\s+(?:القصد|الركن)', re.UNICODE),
    "دفاع_شرعي": re.compile(r'(?:دفاع\s+شرعي|الدفاع\s+عن\s+النفس)', re.UNICODE),
    "تقادم": re.compile(r'(?:تقادم|سقوط.*بمضي)', re.UNICODE),
    "عدم_اختصاص": re.compile(r'عدم\s+(?:ال)?اختصاص', re.UNICODE),
    "قصور_تسبيب": re.compile(r'(?:قصور|القصور)\s+(?:في\s+)?(?:التسبيب|الأسباب)', re.UNICODE),
    "إخلال_حق_دفاع": re.compile(r'(?:إخلال|الإخلال)\s+بحق\s+الدفاع', re.UNICODE),
}

def get_topic(text):
    for t, kws in TOPIC_KW.items():
        if any(k in text for k in kws): return t
    return "عام"


async def train1_patterns(pool):
    log.info("=" * 60); log.info("Train 1: Ruling patterns")
    async with pool.acquire() as c:
        chunks = await c.fetch("SELECT id,content,law_name FROM chunks WHERE is_active=true AND law_name LIKE '%أحكام محكمة التمييز%' AND length(content)>300")
    patterns = defaultdict(lambda: defaultdict(int))
    for ch in chunks:
        topics = [t for t, kws in TOPIC_KW.items() if any(k in ch["content"] for k in kws)]
        results = [r for r, pat in RESULT_RE.items() if pat.search(ch["content"])]
        for t in topics:
            for r in results:
                patterns[t][r] += 1
    with open(f"{OUT}/ruling_patterns.json","w",encoding="utf-8") as f:
        json.dump(dict(patterns), f, ensure_ascii=False, indent=2)
    log.info(f"  {len(patterns)} topics")
    for t, rs in sorted(patterns.items()):
        log.info(f"    {t}: {dict(rs)}")
    return dict(patterns)


async def train2_linkage(pool):
    log.info("=" * 60); log.info("Train 2: Dense linkage")
    async with pool.acquire() as c:
        chunks = await c.fetch("SELECT id,content FROM chunks WHERE is_active=true AND law_name LIKE '%أحكام محكمة التمييز%' AND length(content)>300")
    pairs = defaultdict(int)
    defense_stats = defaultdict(lambda: {"total":0,"accepted":0})
    for ch in chunks:
        arts = list(set(m.group(1) for m in ART_RE.finditer(ch["content"])))
        for i, a1 in enumerate(arts):
            for a2 in arts[i+1:]:
                pairs[tuple(sorted([a1,a2]))] += 1
        accepted = bool(re.search(r'(?:قبول|قبلت|نقض|نقضت)', ch["content"]))
        for d, pat in DEFENSE_RE.items():
            if pat.search(ch["content"]):
                defense_stats[d]["total"] += 1
                if accepted: defense_stats[d]["accepted"] += 1
    top_pairs = sorted(pairs.items(), key=lambda x:-x[1])[:50]
    rates = {}
    for d, s in defense_stats.items():
        rates[d] = {"total": s["total"], "accepted": s["accepted"],
                     "rate": round(s["accepted"]/max(s["total"],1)*100, 1)}
    log.info(f"  {len(pairs)} article pairs, {len(rates)} defenses")
    log.info("  Top 10 pairs:")
    for (a1,a2), cnt in top_pairs[:10]:
        log.info(f"    م{a1} + م{a2}: {cnt}")
    log.info("  Defense success rates:")
    for d, r in sorted(rates.items(), key=lambda x:-x[1]["rate"]):
        log.info(f"    {d}: {r['rate']}% ({r['accepted']}/{r['total']})")
    result = {"top_pairs": [{"pair":[a1,a2],"count":c} for (a1,a2),c in top_pairs],
              "defense_rates": rates}
    with open(f"{OUT}/dense_linkage.json","w",encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return result


async def train3_defense_map(patterns, linkage):
    log.info("=" * 60); log.info("Train 3: Optimal defense map")
    mapping = {
        "ضرب": ["دفاع_شرعي","انتفاء_القصد"], "سرقة": ["انتفاء_القصد","بطلان_القبض","بطلان_التفتيش"],
        "شيك": ["انتفاء_القصد"], "مخدرات": ["بطلان_التفتيش","بطلان_القبض"],
        "تزوير": ["انتفاء_القصد"], "قتل": ["دفاع_شرعي","انتفاء_القصد"],
        "تفتيش": ["بطلان_التفتيش","بطلان_القبض"],
    }
    rates = linkage.get("defense_rates",{})
    dmap = {}
    for topic, defs in mapping.items():
        td = [{"defense":d, "rate": rates.get(d,{}).get("rate",0), "total": rates.get(d,{}).get("total",0)} for d in defs if d in rates]
        td.sort(key=lambda x:-x["rate"])
        dmap[topic] = td
        if td: log.info(f"  {topic}: best={td[0]['defense']} ({td[0]['rate']}%)")
    with open(f"{OUT}/optimal_defense_map.json","w",encoding="utf-8") as f:
        json.dump(dmap, f, ensure_ascii=False, indent=2)
    return dmap


async def train4_precedents(pool):
    log.info("=" * 60); log.info("Train 4: Precedent database")
    async with pool.acquire() as c:
        chunks = await c.fetch("SELECT id,content,law_name FROM chunks WHERE is_active=true AND law_name LIKE '%أحكام محكمة التمييز%' AND (content LIKE '%من المقرر%' OR content LIKE '%المستقر%') AND length(content)>400 LIMIT 3000")
    pdb = defaultdict(list)
    for ch in chunks:
        ref_m = REF_RE.search(ch["content"])
        ref = f"طعن {ref_m.group(1)}/{ref_m.group(2)}" if ref_m else ""
        topic = get_topic(ch["content"])
        for m in PRIN_RE.finditer(ch["content"]):
            txt = m.group(0).strip()
            if 40 < len(txt) < 500:
                pdb[topic].append({"principle": txt, "ref": ref, "chunk_id": ch["id"]})
    for t in pdb:
        seen = set(); unique = []
        for p in pdb[t]:
            k = p["principle"][:80]
            if k not in seen: seen.add(k); unique.append(p)
        pdb[t] = unique[:30]
    total = sum(len(v) for v in pdb.values())
    log.info(f"  {total} precedents in {len(pdb)} topics")
    for t, ps in sorted(pdb.items(), key=lambda x:-len(x[1])):
        log.info(f"    {t}: {len(ps)}")
    with open(f"{OUT}/precedent_database.json","w",encoding="utf-8") as f:
        json.dump(dict(pdb), f, ensure_ascii=False, indent=2)
    return dict(pdb)


async def main():
    log.info(f"Started: {datetime.now().isoformat()}")
    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=5)
    R = {}
    try:
        R["patterns"] = await train1_patterns(pool)
        R["linkage"] = await train2_linkage(pool)
        R["defense_map"] = await train3_defense_map(R["patterns"], R["linkage"])
        R["precedents"] = await train4_precedents(pool)
        report = {
            "timestamp": datetime.now().isoformat(),
            "ruling_patterns": len(R["patterns"]),
            "article_pairs": len(R["linkage"].get("top_pairs",[])),
            "defense_rates": R["linkage"].get("defense_rates",{}),
            "defense_map_topics": len(R["defense_map"]),
            "precedents_total": sum(len(v) for v in R["precedents"].values()),
        }
        with open(f"{OUT}/training_report.json","w",encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        log.info(f"\n{'='*60}")
        log.info("REPORT:")
        for k, v in report.items():
            if k != "defense_rates": log.info(f"  {k}: {v}")
        log.info(f"  Defense rates:")
        for d, r in sorted(report.get("defense_rates",{}).items(), key=lambda x:-x[1].get("rate",0)):
            log.info(f"    {d}: {r['rate']}% ({r['accepted']}/{r['total']})")
    except Exception as e:
        log.error(f"Error: {e}", exc_info=True)
    finally:
        await pool.close()
    log.info(f"Finished: {datetime.now().isoformat()}")

if __name__ == "__main__":
    asyncio.run(main())
