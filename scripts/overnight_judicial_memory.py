#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""المهمة 2+3: ذاكرة قضائية + تفكير محامي + سلاسل تسبيب"""
import asyncio, asyncpg, json, re, os, sys, logging
from datetime import datetime
from collections import defaultdict

DB_URL = f"postgresql://raguser:RAGsecret2024!@{os.environ.get('DB_HOST','db')}:5432/ragdb"
OUT = "scripts/judicial_memory"
os.makedirs(OUT, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(f"{OUT}/overnight.log", encoding="utf-8", mode="w")])
log = logging.getLogger("jm")
try:
    _sh = logging.StreamHandler(open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False))
    _sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(_sh)
except: pass

TOPIC_KW = {
    "ضرب":["ضرب","إيذاء","اعتداء"],"سرقة":["سرقة","سرق","اختلس"],
    "شيك":["شيك","بدون رصيد"],"مخدرات":["مخدر","حيازة","تعاطي"],
    "فصل":["فصل","إنهاء عقد","تعسفي"],"طلاق":["طلاق","خلع","تطليق"],
    "حضانة":["حضانة","محضون"],"تعويض":["تعويض","ضرر","مسؤولية"],
    "شركة":["شركة","شريك"],"تزوير":["تزوير","محرر","مزور"],
    "تفتيش":["تفتيش","قبض","ضبط"],"إيجار":["إيجار","مستأجر","إخلاء"],
}
REF_RE = re.compile(r'(?:الطعن|طعن)\s*(?:رقم)?\s*:?\s*(\d+)\s*/?\s*(\d{4})', re.UNICODE)
FACT_RE = re.compile(r'(?:تتحصل|تتلخص)\s+(?:واقعات?|وقائع)[^.]{20,500}\.', re.UNICODE)
DEFENSE_RE = re.compile(r'(?:ينعى|ينعاه|يثير)\s+(?:الطاعن|المتهم|المدعي)[^.]{20,400}\.', re.UNICODE)
RULE_RE = re.compile(r'(?:من\s+المقرر|المستقر\s+عليه|والثابت\s+في\s+قضاء)[^.]{30,400}\.', re.UNICODE)
APPLY_RE = re.compile(r'(?:لما\s+كان\s+ذلك|وإذ\s+كان\s+الثابت|وبإنزال)[^.]{20,400}\.', re.UNICODE)
RESULT_RE = re.compile(r'(?:حكمت|قضت|قررت)\s+المحكمة[^.]{10,300}\.', re.UNICODE)
CHAIN_RE = re.compile(r'(?:لما\s+كان|وحيث\s+إن)[^.]{20,200}\.\s*(?:وكان|و(?:حيث|إذ))[^.]{20,200}\.\s*(?:ومن\s+ثم|فإن|الأمر\s+الذي)[^.]{20,300}\.', re.UNICODE|re.DOTALL)

def get_topic(text):
    for t, kws in TOPIC_KW.items():
        if any(k in text for k in kws): return t
    return "عام"

async def task2_ruling_units(pool):
    log.info("=== Task 2A: Ruling Units ===")
    async with pool.acquire() as c:
        chunks = await c.fetch("SELECT id, content, law_name FROM chunks WHERE is_active=true AND law_name LIKE '%أحكام محكمة التمييز%' AND length(content)>800 LIMIT 3000")
    units = defaultdict(list)
    for ch in chunks:
        ct = ch["content"]; topic = get_topic(ct)
        ref_m = REF_RE.search(ct)
        ref = f"طعن {ref_m.group(1)}/{ref_m.group(2)}" if ref_m else ""
        u = {"topic": topic, "ref": ref, "chunk_id": ch["id"], "score": 0}
        # Extract components
        fact_m = FACT_RE.search(ct)
        if fact_m: u["facts"] = fact_m.group(0)[:300]; u["score"] += 2
        def_m = DEFENSE_RE.search(ct)
        if def_m: u["defense"] = def_m.group(0)[:300]; u["score"] += 2
        rule_m = RULE_RE.search(ct)
        if rule_m: u["rule"] = rule_m.group(0)[:300]; u["score"] += 3
        apply_m = APPLY_RE.search(ct)
        if apply_m: u["application"] = apply_m.group(0)[:300]; u["score"] += 3
        res_m = RESULT_RE.search(ct)
        if res_m: u["result"] = res_m.group(0)[:200]; u["score"] += 2
        if u["score"] >= 4:
            units[topic].append(u)
    # Keep top 20 per topic
    for t in units:
        units[t] = sorted(units[t], key=lambda x: -x["score"])[:20]
    total = sum(len(v) for v in units.values())
    log.info(f"  Ruling units: {total} in {len(units)} topics")
    for t, us in sorted(units.items(), key=lambda x: -len(x[1])):
        log.info(f"    {t}: {len(us)} (avg score: {sum(u['score'] for u in us)/max(len(us),1):.1f})")
    with open(f"{OUT}/ruling_units.json","w",encoding="utf-8") as f:
        json.dump(dict(units), f, ensure_ascii=False, indent=2)
    return total

async def task2_reasoning_chains(pool):
    log.info("=== Task 2C: Reasoning Chains ===")
    async with pool.acquire() as c:
        chunks = await c.fetch("SELECT content FROM chunks WHERE is_active=true AND law_name LIKE '%أحكام محكمة التمييز%' AND length(content)>600 LIMIT 5000")
    chains = []
    for ch in chunks:
        for m in CHAIN_RE.finditer(ch["content"]):
            txt = m.group(0).strip()
            if 80 < len(txt) < 800:
                chains.append({"text": txt, "topic": get_topic(txt)})
    seen = set(); unique = []
    for c in chains:
        k = c["text"][:80]
        if k not in seen: seen.add(k); unique.append(c)
    unique = unique[:200]
    log.info(f"  Reasoning chains: {len(unique)}")
    with open(f"{OUT}/reasoning_chains.json","w",encoding="utf-8") as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)
    return len(unique)

async def task3_defense_outcomes(pool):
    log.info("=== Task 3A: Defense Outcomes ===")
    DEFENSES = {
        "بطلان_تفتيش": re.compile(r'بطلان\s+(?:التفتيش|إجراء)', re.UNICODE),
        "بطلان_قبض": re.compile(r'بطلان\s+(?:القبض|إجراءات\s+القبض)', re.UNICODE),
        "انتفاء_قصد": re.compile(r'(?:انتفاء|عدم\s+توافر)\s+(?:القصد|الركن)', re.UNICODE),
        "دفاع_شرعي": re.compile(r'(?:دفاع\s+شرعي|الدفاع\s+عن\s+النفس)', re.UNICODE),
        "تقادم": re.compile(r'(?:تقادم|سقوط.*بمضي)', re.UNICODE),
        "قصور_تسبيب": re.compile(r'(?:قصور|القصور)\s+(?:في\s+)?(?:التسبيب|الأسباب)', re.UNICODE),
        "إخلال_حق_دفاع": re.compile(r'(?:إخلال|الإخلال)\s+بحق\s+الدفاع', re.UNICODE),
    }
    async with pool.acquire() as c:
        chunks = await c.fetch("SELECT content FROM chunks WHERE is_active=true AND law_name LIKE '%أحكام محكمة التمييز%' AND length(content)>300")
    outcomes = {}
    for dname, dpat in DEFENSES.items():
        success = []; failure = []
        for ch in chunks:
            ct = ch["content"]
            if dpat.search(ct):
                accepted = bool(re.search(r'(?:قبول|قبلت|نقض|نقضت|سديد|في\s+محله)', ct))
                rejected = bool(re.search(r'(?:رفض|رفضت|غير\s+سديد|مردود|في\s+غير)', ct))
                if accepted and not rejected:
                    reason = RULE_RE.search(ct)
                    success.append(reason.group(0)[:200] if reason else "")
                elif rejected:
                    reason = re.search(r'(?:ذلك\s+(?:أن|بأن))[^.]{20,300}\.', ct, re.UNICODE)
                    failure.append(reason.group(0)[:200] if reason else "")
        rate = len(success)/(max(len(success)+len(failure),1))*100
        outcomes[dname] = {
            "total": len(success)+len(failure), "success": len(success), "failure": len(failure),
            "rate": round(rate,1),
            "success_reasons": list(set(s for s in success if s))[:5],
            "failure_reasons": list(set(f for f in failure if f))[:5],
        }
        log.info(f"  {dname}: {rate:.0f}% ({len(success)}/{len(success)+len(failure)})")
    with open(f"{OUT}/defense_outcomes.json","w",encoding="utf-8") as f:
        json.dump(outcomes, f, ensure_ascii=False, indent=2)
    return outcomes

async def main():
    log.info(f"Started: {datetime.now().isoformat()}")
    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=5)
    R = {}
    try:
        R["units"] = await task2_ruling_units(pool)
        R["chains"] = await task2_reasoning_chains(pool)
        R["outcomes"] = await task3_defense_outcomes(pool)
        report = {"timestamp":datetime.now().isoformat(),"ruling_units":R["units"],"chains":R["chains"],
                  "defense_outcomes":{k:{"rate":v["rate"],"total":v["total"]} for k,v in R["outcomes"].items()}}
        with open(f"{OUT}/report.json","w",encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        log.info(f"\nREPORT: units={R['units']} chains={R['chains']}")
    except Exception as e:
        log.error(f"Error: {e}", exc_info=True)
    finally:
        await pool.close()
    log.info(f"Finished: {datetime.now().isoformat()}")

if __name__ == "__main__":
    asyncio.run(main())
