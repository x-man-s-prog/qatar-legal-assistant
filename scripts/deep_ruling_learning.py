#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/deep_ruling_learning.py — تعلّم عميق من أحكام التمييز (6 أنواع)
"""
import asyncio, asyncpg, json, re, os, sys, logging
from datetime import datetime
from collections import defaultdict

DB_URL = f"postgresql://raguser:RAGsecret2024!@{os.environ.get('DB_HOST','db')}:5432/ragdb"
OUT = "scripts/ruling_deep_learning"
os.makedirs(OUT, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(f"{OUT}/learning.log", encoding="utf-8", mode="w")])
log = logging.getLogger("rl")
try:
    _sh = logging.StreamHandler(open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False))
    _sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(_sh)
except: pass

def dedup(items, key_len=80, max_items=50):
    seen=set(); u=[]
    for i in items:
        k=i[:key_len];
        if k not in seen: seen.add(k); u.append(i)
    return u[:max_items]


async def e1_facts(pool):
    log.info("=== 1. Fact presentation ===")
    async with pool.acquire() as c:
        chunks = await c.fetch("SELECT content FROM chunks WHERE is_active=true AND law_name LIKE '%أحكام محكمة التمييز%' AND length(content)>500 LIMIT 3000")
    pats = [
        re.compile(r'(?:تتحصل|تتلخص)\s+(?:واقعات?|وقائع)\s+[^.]{20,400}\.', re.UNICODE),
        re.compile(r'(?:اتهمت|أسندت)\s+النيابة\s+العامة\s+[^.]{20,400}\.', re.UNICODE),
        re.compile(r'(?:على\s+ما\s+يبين|الثابت)\s+من\s+(?:الأوراق|الحكم)[^.]{20,400}\.', re.UNICODE),
    ]
    found = []
    for ch in chunks:
        for p in pats:
            for m in p.finditer(ch["content"]):
                t=m.group(0).strip()
                if 30<len(t)<500: found.append(t)
    result = dedup(found)
    log.info(f"  Fact openers: {len(result)}")
    return result


async def e2_reasoning(pool):
    log.info("=== 2. Reasoning patterns (MAIN) ===")
    async with pool.acquire() as c:
        chunks = await c.fetch("SELECT content FROM chunks WHERE is_active=true AND law_name LIKE '%أحكام محكمة التمييز%' AND length(content)>500 LIMIT 5000")
    cats = {"law_to_fact":[],"logical_chains":[],"application":[],"connectors":[]}
    p1 = [re.compile(r'(?:لما\s+كان\s+)?(?:النص|نص\s+المادة)\s+(?:في|من)[^.]{10,100}\s+(?:يدل|مفاده|مؤداه)\s+(?:على\s+)?أن[^.]{20,400}\.', re.UNICODE)]
    p2 = [re.compile(r'(?:وبإنزال|وبتطبيق)\s+(?:ما\s+تقدم|هذه\s+القاعدة)\s+على\s+[^.]{20,400}\.', re.UNICODE)]
    p3 = [re.compile(r'(?:لما\s+كان\s+ذلك|ومؤدى\s+ذلك|وآية\s+ذلك|ومفاد\s+ذلك|والمستفاد|وترتيباً\s+على|وحاصل\s+القول)[^.]{20,300}\.', re.UNICODE)]
    for ch in chunks:
        ct = ch["content"]
        for p in p1:
            for m in p.finditer(ct):
                t=m.group(0).strip()
                if 40<len(t)<600: cats["law_to_fact"].append(t)
        for p in p2:
            for m in p.finditer(ct):
                t=m.group(0).strip()
                if 40<len(t)<500: cats["application"].append(t)
        for p in p3:
            for m in p.finditer(ct):
                t=m.group(0).strip()
                if 30<len(t)<400: cats["connectors"].append(t)
    for k in cats: cats[k] = dedup(cats[k], max_items=100)
    for k,v in cats.items(): log.info(f"  {k}: {len(v)}")
    return cats


async def e3_evidence(pool):
    log.info("=== 3. Evidence evaluation ===")
    async with pool.acquire() as c:
        chunks = await c.fetch("SELECT content FROM chunks WHERE is_active=true AND law_name LIKE '%أحكام محكمة التمييز%' AND (content LIKE '%دليل%' OR content LIKE '%شهادة%' OR content LIKE '%إثبات%') AND length(content)>400 LIMIT 3000")
    cats = {"accept":[],"reject":[],"discretion":[]}
    pa = [re.compile(r'(?:تطمئن|اطمأنت)\s+(?:المحكمة|إليه)[^.]{20,300}\.', re.UNICODE),
          re.compile(r'(?:ثابت|ثبت)\s+(?:بما\s+لا\s+يدع|بيقين|من\s+الأوراق)[^.]{20,300}\.', re.UNICODE)]
    pr = [re.compile(r'(?:لا\s+يصلح|لا\s+يُعوَّل|لا\s+تطمئن)[^.]{20,300}\.', re.UNICODE),
          re.compile(r'(?:خلت|أخلت)\s+(?:الأوراق|الدعوى)\s+(?:من|مما)[^.]{20,300}\.', re.UNICODE)]
    pd = [re.compile(r'(?:تقدير|وزن)\s+(?:الأدلة|أقوال\s+الشهود)\s+(?:من\s+)?(?:إطلاقات|سلطة)[^.]{20,300}\.', re.UNICODE)]
    for ch in chunks:
        ct = ch["content"]
        for p in pa:
            for m in p.finditer(ct):
                t=m.group(0).strip()
                if 30<len(t)<400: cats["accept"].append(t)
        for p in pr:
            for m in p.finditer(ct):
                t=m.group(0).strip()
                if 30<len(t)<400: cats["reject"].append(t)
        for p in pd:
            for m in p.finditer(ct):
                t=m.group(0).strip()
                if 30<len(t)<400: cats["discretion"].append(t)
    for k in cats: cats[k] = dedup(cats[k])
    for k,v in cats.items(): log.info(f"  {k}: {len(v)}")
    return cats


async def e4_defenses(pool):
    log.info("=== 4. Defense responses ===")
    async with pool.acquire() as c:
        chunks = await c.fetch("SELECT content FROM chunks WHERE is_active=true AND law_name LIKE '%أحكام محكمة التمييز%' AND (content LIKE '%الدفع%' OR content LIKE '%النعي%') AND length(content)>400 LIMIT 3000")
    cats = {"reject":[],"accept":[],"refute":[]}
    prj = [re.compile(r'(?:هذا\s+)?(?:الدفع|النعي)\s+(?:غير\s+سديد|مردود|في\s+غير\s+محله)[^.]{10,300}\.', re.UNICODE),
           re.compile(r'(?:ما\s+ينعاه|ما\s+يثيره)\s+الطاعن[^.]{10,100}(?:غير\s+سديد|مردود)[^.]{10,200}\.', re.UNICODE)]
    pac = [re.compile(r'(?:هذا\s+)?(?:الدفع|النعي)\s+(?:سديد|في\s+محله|صحيح)[^.]{10,300}\.', re.UNICODE)]
    prf = [re.compile(r'(?:ولا\s+محل\s+لـ?لقول|ولا\s+وجه\s+لـ?لقول|ولا\s+حجة\s+في\s+القول)[^.]{20,300}\.', re.UNICODE)]
    for ch in chunks:
        ct = ch["content"]
        for p in prj:
            for m in p.finditer(ct):
                t=m.group(0).strip()
                if 30<len(t)<500: cats["reject"].append(t)
        for p in pac:
            for m in p.finditer(ct):
                t=m.group(0).strip()
                if 30<len(t)<500: cats["accept"].append(t)
        for p in prf:
            for m in p.finditer(ct):
                t=m.group(0).strip()
                if 30<len(t)<500: cats["refute"].append(t)
    for k in cats: cats[k] = dedup(cats[k])
    for k,v in cats.items(): log.info(f"  {k}: {len(v)}")
    return cats


async def e5_verdicts(pool):
    log.info("=== 5. Verdict patterns ===")
    async with pool.acquire() as c:
        chunks = await c.fetch("SELECT content FROM chunks WHERE is_active=true AND law_name LIKE '%أحكام محكمة التمييز%' AND (content LIKE '%حكمت المحكمة%' OR content LIKE '%فلهذه الأسباب%') AND length(content)>200 LIMIT 2000")
    cats = {"accept_appeal":[],"reject_appeal":[],"cassation":[]}
    for ch in chunks:
        ct = ch["content"]
        if re.search(r'(?:حكمت|قضت)\s+المحكمة\s+بقبول', ct):
            m = re.search(r'(?:حكمت|قضت)\s+المحكمة\s+بقبول[^.]{10,200}\.', ct)
            if m: cats["accept_appeal"].append(m.group(0).strip())
        if re.search(r'(?:حكمت|قضت)\s+المحكمة\s+برفض', ct):
            m = re.search(r'(?:حكمت|قضت)\s+المحكمة\s+برفض[^.]{10,200}\.', ct)
            if m: cats["reject_appeal"].append(m.group(0).strip())
        if re.search(r'بنقض\s+الحكم', ct):
            m = re.search(r'(?:حكمت|قضت)\s+المحكمة\s+بنقض[^.]{10,200}\.', ct)
            if m: cats["cassation"].append(m.group(0).strip())
    for k in cats: cats[k] = dedup(cats[k], max_items=30)
    for k,v in cats.items(): log.info(f"  {k}: {len(v)}")
    return cats


async def e6_unique(pool):
    log.info("=== 6. Unique phrases ===")
    async with pool.acquire() as c:
        chunks = await c.fetch("SELECT content FROM chunks WHERE is_active=true AND law_name LIKE '%أحكام محكمة التمييز%' AND length(content)>500 LIMIT 4000")
    pats = [
        re.compile(r'(?:والأصل|والقاعدة|والمبدأ)\s+(?:أن|في\s+القانون)[^.]{20,300}\.', re.UNICODE),
        re.compile(r'(?:ولا\s+يسوغ|ولا\s+يجدي|ولا\s+يجوز\s+القول)\s+[^.]{20,300}\.', re.UNICODE),
        re.compile(r'(?:وغني\s+عن\s+البيان|ومما\s+لا\s+ريب)\s+[^.]{20,300}\.', re.UNICODE),
        re.compile(r'(?:إعمالاً|تطبيقاً|إنفاذاً)\s+لـ?[^.]{20,300}\.', re.UNICODE),
    ]
    found = []
    for ch in chunks:
        for p in pats:
            for m in p.finditer(ch["content"]):
                t=m.group(0).strip()
                if 30<len(t)<400: found.append(t)
    result = dedup(found, max_items=100)
    log.info(f"  Unique phrases: {len(result)}")
    return result


async def main():
    log.info(f"Started: {datetime.now().isoformat()}")
    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=5)
    R = {}
    try:
        R["facts"] = await e1_facts(pool)
        R["reasoning"] = await e2_reasoning(pool)
        R["evidence"] = await e3_evidence(pool)
        R["defenses"] = await e4_defenses(pool)
        R["verdicts"] = await e5_verdicts(pool)
        R["phrases"] = await e6_unique(pool)

        total = 0
        report_cats = {}
        for k, v in R.items():
            if isinstance(v, dict):
                cnt = sum(len(x) for x in v.values() if isinstance(x, list))
            elif isinstance(v, list):
                cnt = len(v)
            else: cnt = 0
            total += cnt; report_cats[k] = cnt

        with open(f"{OUT}/ruling_patterns_deep.json","w",encoding="utf-8") as f:
            json.dump(R, f, ensure_ascii=False, indent=2)
        report = {"timestamp":datetime.now().isoformat(),"total":total,"by_cat":report_cats}
        with open(f"{OUT}/report.json","w",encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        log.info(f"\nTOTAL: {total} items")
        for k,v in report_cats.items(): log.info(f"  {k}: {v}")

        try:
            import subprocess
            subprocess.run(["docker","cp",OUT,"legal_app:/app/scripts/ruling_deep_learning"],capture_output=True,timeout=15)
            log.info("  Copied to Docker")
        except: pass
    except Exception as e:
        log.error(f"Error: {e}", exc_info=True)
    finally:
        await pool.close()
    log.info(f"Finished: {datetime.now().isoformat()}")

if __name__ == "__main__":
    asyncio.run(main())
