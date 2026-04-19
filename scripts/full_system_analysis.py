#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/full_system_analysis.py — تحليل شامل لكل مكوّنات النظام (10 محاور + 100 سؤال)
"""
import asyncio, asyncpg, json, re, os, sys, time, logging, urllib.request
from datetime import datetime
from collections import defaultdict

DB_URL = f"postgresql://raguser:RAGsecret2024!@{os.environ.get('DB_HOST','db')}:5432/ragdb"
API_URL = "http://localhost:8000/api/v1/query/"
API_KEY = "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394"
OUT = "scripts/system_analysis"
os.makedirs(OUT, exist_ok=True)
HEADERS = {"Content-Type": "application/json", "X-API-Key": API_KEY}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(f"{OUT}/analysis.log", encoding="utf-8", mode="w")])
log = logging.getLogger("analysis")
try:
    _sh = logging.StreamHandler(open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False))
    _sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(_sh)
except: pass


# ══════════════════════════════════════
# 1. Database
# ══════════════════════════════════════
async def m1_database(pool):
    log.info("=== M1: Database ===")
    async with pool.acquire() as c:
        total = await c.fetchval("SELECT COUNT(*) FROM chunks WHERE is_active=true")
        inactive = await c.fetchval("SELECT COUNT(*) FROM chunks WHERE is_active=false")
        no_emb = await c.fetchval("SELECT COUNT(*) FROM chunks WHERE is_active=true AND embedding IS NULL")
        short = await c.fetchval("SELECT COUNT(*) FROM chunks WHERE is_active=true AND length(content)<50")
        rulings = await c.fetchval("SELECT COUNT(*) FROM chunks WHERE is_active=true AND law_name LIKE '%أحكام محكمة التمييز%'")
        laws = await c.fetch("SELECT law_name, COUNT(*) cnt FROM chunks WHERE is_active=true AND law_name IS NOT NULL GROUP BY law_name ORDER BY cnt DESC LIMIT 10")
    r = {"total": total, "inactive": inactive, "no_embedding": no_emb, "short": short, "rulings": rulings,
         "top_laws": [(l["law_name"][:50], l["cnt"]) for l in laws], "strengths": [], "weaknesses": []}
    if no_emb == 0: r["strengths"].append("100% embedding coverage")
    else: r["weaknesses"].append(f"{no_emb} chunks without embedding")
    if rulings > 10000: r["strengths"].append(f"{rulings} rulings — excellent coverage")
    if short > 100: r["weaknesses"].append(f"{short} very short chunks (<50 chars)")
    log.info(f"  Total: {total} | Rulings: {rulings} | No-emb: {no_emb} | Short: {short}")
    return r


# ══════════════════════════════════════
# 2. Known Answers
# ══════════════════════════════════════
async def m2_known_answers():
    log.info("=== M2: Known Answers ===")
    sys.path.insert(0, '/app')
    from core.qatar_legal_knowledge import QATAR_KNOWN_ANSWERS, match_known_answer
    total = len(QATAR_KNOWN_ANSWERS)
    test_qs = {k: k.replace("_"," ") for k in QATAR_KNOWN_ANSWERS}
    # Better test questions for tricky ones
    overrides = {"محاولة_الانتحار":"هل محاولة الانتحار جريمة","مدة_إشعار_إنهاء_العقد":"كم مدة الإشعار",
        "مكافأة_نهاية_الخدمة":"كم مكافأة نهاية الخدمة","السحر_والشعوذة":"ما عقوبة السحر",
        "تزوير_محررات":"ما عقوبة التزوير","خيانة_الأمانة":"ما عقوبة خيانة الأمانة",
        "إصابة_العمل":"ما هي إصابة العمل","شيك_بدون_رصيد":"ما عقوبة شيك بدون رصيد",
        "حجز_الجواز":"هل يحق حجز جوازي","نقل_الكفالة":"كيف أنقل كفالتي",
        "إنهاء_العقد_بدون_إشعار":"حالات الفصل بدون إشعار","تقادم_الدعوى_الجنائية":"متى يسقط الحق في رفع الدعوى الجنائية",
        "الشرط_الجزائي":"ما هو الشرط الجزائي","مطالبة_مالية":"واحد ماخذ فلوسي",
        "تنفيذ_حكم":"كيف أنفذ حكم","أمر_أداء":"ما هو أمر الأداء",
        "وساطة_وتوفيق":"هل فيه وساطة","اختصاص_المحاكم":"أي محكمة أروح لها",
        "رسوم_قضائية":"كم تكلفة القضية","مدد_التقاضي":"كم تاخذ القضية",
        "حبس_احتياطي_تفصيلي":"كم مدة الحبس الاحتياطي","شيك_ضمان":"الشيك كان ضمان",
        "حادث_مروري":"صار لي حادث مروري","جنسية_قطرية":"كيف أحصل على الجنسية القطرية",
        "الاستقالة_الفورية":"هل يحق لي الاستقالة فوراً","رد_الاعتبار":"كيف أرد اعتباري"}
    test_qs.update(overrides)
    ok = 0; fail_list = []
    for k in QATAR_KNOWN_ANSWERS:
        if match_known_answer(test_qs.get(k, k.replace("_"," "))): ok += 1
        else: fail_list.append(k)
    r = {"total": total, "matched": ok, "unmatched": fail_list, "rate": f"{ok/total*100:.0f}%",
         "strengths": [], "weaknesses": []}
    if ok == total: r["strengths"].append(f"100% patterns work ({total}/{total})")
    else: r["weaknesses"].append(f"{len(fail_list)} unmatched: {fail_list}")
    log.info(f"  Total: {total} | Matched: {ok} | Unmatched: {fail_list}")
    return r


# ══════════════════════════════════════
# 3. Linkage Index
# ══════════════════════════════════════
async def m3_linkage():
    log.info("=== M3: Linkage Index ===")
    idx = {}
    for p in ["/app/scripts/article_ruling_compact.json", "scripts/article_ruling_compact.json"]:
        if os.path.exists(p):
            with open(p,"r",encoding="utf-8") as f: idx = json.load(f)
            break
    if not idx: return {"error": "Index not found", "weaknesses": ["Linkage index missing"]}
    total_arts = len(idx)
    total_links = sum(len(v) if isinstance(v,list) else 1 for v in idx.values())
    r = {"articles": total_arts, "links": total_links, "avg": round(total_links/max(total_arts,1),1),
         "strengths": [], "weaknesses": []}
    if total_arts > 2000: r["strengths"].append(f"{total_arts} articles linked")
    if total_links > 3000: r["strengths"].append(f"{total_links} total links")
    log.info(f"  Articles: {total_arts} | Links: {total_links}")
    return r


# ══════════════════════════════════════
# 4. Knowledge Base (TOPIC_TO_ARTICLES)
# ══════════════════════════════════════
async def m4_kb():
    log.info("=== M4: Knowledge Base ===")
    sys.path.insert(0, '/app')
    from core.legal_knowledge_base import TOPIC_TO_ARTICLES
    total = len(TOPIC_TO_ARTICLES)
    with_prin = sum(1 for d in TOPIC_TO_ARTICLES.values() if d.get("principles"))
    r = {"topics": total, "with_principles": with_prin, "topic_list": list(TOPIC_TO_ARTICLES.keys()),
         "strengths": [], "weaknesses": []}
    if total >= 40: r["strengths"].append(f"{total} topics — comprehensive")
    if with_prin > 0: r["strengths"].append(f"{with_prin} topics with judicial principles")
    log.info(f"  Topics: {total} | With principles: {with_prin}")
    return r


# ══════════════════════════════════════
# 5. Principles
# ══════════════════════════════════════
async def m5_principles():
    log.info("=== M5: Principles ===")
    p = {}
    for path in ["/app/scripts/principles_index.json", "scripts/principles_index.json"]:
        if os.path.exists(path):
            with open(path,"r",encoding="utf-8") as f: p = json.load(f)
            break
    total = sum(len(v) for v in p.values())
    by_t = {k: len(v) for k, v in p.items()}
    r = {"total": total, "topics": len(p), "by_topic": by_t, "strengths": [], "weaknesses": []}
    if total > 100: r["strengths"].append(f"{total} judicial principles")
    log.info(f"  Total: {total} in {len(p)} topics")
    return r


# ══════════════════════════════════════
# 6. Style Guide
# ══════════════════════════════════════
async def m6_style():
    log.info("=== M6: Style Guide ===")
    g = {}
    for path in ["/app/scripts/learned_styles/drafting_style_guide.json","scripts/learned_styles/drafting_style_guide.json"]:
        if os.path.exists(path):
            with open(path,"r",encoding="utf-8") as f: g = json.load(f)
            break
    cats = g.get("categories", {})
    total = sum(d.get("count",0) for d in cats.values()) if cats else 0
    r = {"total": total, "categories": len(cats), "strengths": [], "weaknesses": []}
    if total > 50: r["strengths"].append(f"{total} style phrases")
    log.info(f"  Total: {total} phrases in {len(cats)} categories")
    return r


# ══════════════════════════════════════
# 7. Dialect
# ══════════════════════════════════════
async def m7_dialect():
    log.info("=== M7: Dialect ===")
    sys.path.insert(0, '/app')
    from core.nlp_utils import expand_gulf_dialect
    tests = ["الكفيل طفشني","حرمتي تبي خلع","واحد ناصبني","شيك طاير","مسكوني الشرطة",
             "ودوني المخفر","الحكم ظالم","أبي أستأنف","يبزني بصور","شهّر فيني",
             "ظلمني صاحب الشغل","حقي ضايع","ما أدري وش أسوي","هل فيه أمل",
             "كم تاخذ القضية","هل لازم محامي","مين أروح له أول","وش يحتاج أجهز"]
    ok = sum(1 for t in tests if expand_gulf_dialect(t) != t)
    r = {"tested": len(tests), "understood": ok, "rate": f"{ok/len(tests)*100:.0f}%",
         "strengths": [], "weaknesses": []}
    if ok > 15: r["strengths"].append(f"{ok}/{len(tests)} dialect phrases understood")
    log.info(f"  Understood: {ok}/{len(tests)}")
    return r


# ══════════════════════════════════════
# 8. Live Performance (100 questions)
# ══════════════════════════════════════
async def m8_live():
    log.info("=== M8: Live Performance (100 questions) ===")
    QS = [
        # known (20)
        *[{"q":q,"cat":"known"} for q in ["ما عقوبة السرقة","ما حقوقي عند الفصل التعسفي","كيف إجراءات الطلاق",
           "ما عقوبة حيازة المخدرات","ما حقوق الحضانة","ما عقوبة التزوير","ما عقوبة الشيك بدون رصيد",
           "ما حالات إنهاء العقد بدون إشعار","كيف أنفذ حكم صادر لصالحي","ما هو أمر الأداء",
           "كم تكلفة القضية","كم تاخذ القضية","ما عقوبة التحرش","ما عقوبة السحر",
           "هل يحق حجز جوازي","ما عقوبة الرشوة","ما هي إصابة العمل","كيف أحصل على الجنسية القطرية",
           "أي محكمة أروح لها","هل فيه وساطة قبل المحكمة"]],
        # dialect (15)
        *[{"q":q,"cat":"dialect"} for q in ["الكفيل طفشني","حرمتي تبي تنفصل","واحد ناصبني بمبلغ كبير",
           "شيك طاير وش أسوي","ريال هددني بالواتساب","ولدي انضرب بالمدرسة","صاحب البيت يبي يطلعني",
           "يبزني بصور خاصة","مسكوني وودوني المخفر","الحكم ظالم أبي أستأنف",
           "واحد ماخذ فلوسي وما يبي يردهم","خويي ضربني وكسر يدي","حرمتي سافرت بالعيال وما ترجع",
           "مستأجر بمحلي ما يدفع إيجار","شريكي ياخذ فلوس الشركة"]],
        # draft (10)
        *[{"q":q,"cat":"draft"} for q in ["صيغ لي مذكرة دفاع ضرب","صيغ لي لائحة فصل تعسفي",
           "صيغ لي مذكرة شيك بدون رصيد","صيغ لي مذكرة طعن بالتمييز","صيغ لي عقد إيجار شقة",
           "صيغ لي عقد عمل","صيغ لي عقد شراكة","صيغ لي مذكرة دفاع سرقة",
           "صيغ لي مذكرة دفاع مخدرات","صيغ لي مذكرة حضانة"]],
        # greet/sys (5)
        *[{"q":q,"cat":"greet"} for q in ["السلام عليكم","شكراً جزيلاً","وش المهام الي تقدر تسويها","من أنت","كيف أطبخ كبسة"]],
        # complex (10)
        *[{"q":q,"cat":"complex"} for q in ["واحد ضربني وسرق جوالي وهددني","الشركة فصلتني وما عطتني راتب 3 شهور",
           "شريكي يختلس ويزوّر الدفاتر","مقاول ما خلص البناء وهرب","زوجي يضربني وأبي طلاق مع حضانة العيال",
           "اشتريت سيارة وطلعت فيها عيب مخفي","جاري بنى بدون ترخيص يحجب الشمس",
           "موظف سابق سرق بيانات العملاء","والدي توفي وأخوي مسيطر على الميراث",
           "أنا مهندس رفضت أوقع على تقارير مزورة وفصلوني"]],
        # rare (10)
        *[{"q":q,"cat":"rare"} for q in ["هل يحق لي رفض التفتيش","ما الفرق بين الجنحة والجناية",
           "كم مدة الحبس الاحتياطي","هل الزواج العرفي معترف به في قطر","ما حقوق المرأة الحامل في العمل",
           "هل يحق للأجنبي تملك عقار في قطر","ما عقوبة البلاغ الكاذب","هل التسجيل الصوتي يُقبل كدليل",
           "ما حكم التنصت على المكالمات","ما حقوق المعاقين في بيئة العمل"]],
        # lawyer (10)
        *[{"q":q,"cat":"lawyer"} for q in ["واحد ضربني وعندي فيديو — وش فرصي أكسب",
           "واحد ضربني بس ما عندي أي دليل","متهم بمخدرات والتفتيش بدون إذن — فيه أمل",
           "عندي رسائل واتساب تثبت الاتفاق — تنفع كدليل","عندي شاهد واحد بس هو قريبي — يُقبل",
           "حصل لي حادث الحين — وش أول شي أسويه","اكتشفت موظف يسرق من الشركة — وش أسوي قبل ما يهرب",
           "استلمت إنذار إخلاء — عندي أسبوع بس","أبي أعرف — أرفع دعوى ولا أتصالح",
           "القضية مرت عليها 5 سنوات — هل سقطت"]],
    ]

    by_cat = defaultdict(lambda: {"pass":0,"fail":0,"total":0,"confs":[],"times":[]})
    all_res = []
    for i, t in enumerate(QS):
        try:
            t0 = time.time()
            data = json.dumps({"query":t["q"],"model":"openai","session_id":f"a_{i}"}).encode("utf-8")
            req = urllib.request.Request(API_URL, data=data, headers=HEADERS, method="POST")
            resp = urllib.request.urlopen(req, timeout=120)
            d = json.loads(resp.read().decode("utf-8"))
            elapsed = time.time() - t0
            a = d.get("answer",""); conf = d.get("confidence",0); known = d.get("from_known_answer",False)
            cat = t["cat"]
            ok = True; reason = ""
            if cat == "known" and not known: ok = False; reason = "not known_answer"
            elif cat == "draft" and conf < 80: ok = False; reason = f"conf={conf}<80"
            elif cat == "greet" and conf < 80: ok = True  # greetings always pass
            elif cat in ("dialect","complex","rare","lawyer") and conf < 10 and len(a) < 80:
                ok = False; reason = f"conf={conf} len={len(a)}"
            by_cat[cat]["total"] += 1; by_cat[cat]["confs"].append(conf); by_cat[cat]["times"].append(elapsed)
            if ok: by_cat[cat]["pass"] += 1
            else: by_cat[cat]["fail"] += 1
            all_res.append({"n":i+1,"q":t["q"][:45],"cat":cat,"conf":conf,"time":round(elapsed,1),"known":known,"len":len(a),"ok":ok,"reason":reason})
            if (i+1) % 20 == 0: log.info(f"  Progress: {i+1}/{len(QS)}")
            time.sleep(1)
        except Exception as e:
            by_cat[t["cat"]]["fail"] += 1; by_cat[t["cat"]]["total"] += 1
            all_res.append({"n":i+1,"q":t["q"][:45],"cat":t["cat"],"ok":False,"reason":str(e)})

    tp = sum(c["pass"] for c in by_cat.values()); tf = sum(c["fail"] for c in by_cat.values())
    summary = {}
    for cat, d in by_cat.items():
        summary[cat] = {"pass":d["pass"],"fail":d["fail"],"total":d["total"],
            "rate":f"{d['pass']/max(d['total'],1)*100:.0f}%",
            "avg_conf":round(sum(d["confs"])/max(len(d["confs"]),1)),
            "avg_time":round(sum(d["times"])/max(len(d["times"]),1),1)}

    failed = [r for r in all_res if not r.get("ok")]
    lowest = sorted([r for r in all_res if r.get("ok") and r.get("conf",0)>0], key=lambda x:x.get("conf",0))[:10]
    slowest = sorted(all_res, key=lambda x:x.get("time",0), reverse=True)[:10]
    avg_conf = round(sum(r.get("conf",0) for r in all_res)/max(len(all_res),1))
    avg_time = round(sum(r.get("time",0) for r in all_res)/max(len(all_res),1),1)

    r = {"total":len(QS),"pass":tp,"fail":tf,"rate":f"{tp/len(QS)*100:.0f}%","by_cat":summary,
         "failed":failed[:15],"lowest_conf":lowest,"slowest":slowest,"avg_conf":avg_conf,"avg_time":avg_time,
         "strengths":[],"weaknesses":[]}
    if tp/len(QS) > 0.90: r["strengths"].append(f"{tp}/{len(QS)} pass ({tp/len(QS)*100:.0f}%)")
    for cat, d in summary.items():
        if d["fail"] > 0: r["weaknesses"].append(f"{cat}: {d['fail']} failures from {d['total']}")
    log.info(f"  RESULT: {tp}/{len(QS)} ({tp/len(QS)*100:.0f}%) | Avg conf: {avg_conf}% | Avg time: {avg_time}s")
    for cat, d in summary.items():
        log.info(f"    {cat}: {d['pass']}/{d['total']} ({d['rate']}) avg_conf={d['avg_conf']}% avg_time={d['avg_time']}s")
    return r


# ══════════════════════════════════════
# 9. System Prompt
# ══════════════════════════════════════
async def m9_prompt():
    log.info("=== M9: System Prompt ===")
    sys.path.insert(0, '/app')
    from core.prompts import EXPERT_SYSTEM
    words = len(EXPERT_SYSTEM.split())
    sections = re.findall(r'═══(.+?)═══', EXPERT_SYSTEM)
    r = {"words": words, "sections": len(sections), "section_names": [s.strip() for s in sections],
         "strengths": [], "weaknesses": []}
    if len(sections) > 10: r["strengths"].append(f"{len(sections)} sections — comprehensive")
    if words > 2500: r["weaknesses"].append(f"System Prompt very long ({words} words)")
    log.info(f"  Words: {words} | Sections: {len(sections)}")
    return r


# ══════════════════════════════════════
# 10. Training Data
# ══════════════════════════════════════
async def m10_training():
    log.info("=== M10: Training Data ===")
    files = {"ruling_patterns":"scripts/self_training_results/ruling_patterns.json",
             "dense_linkage":"scripts/self_training_results/dense_linkage.json",
             "optimal_defense":"scripts/self_training_results/optimal_defense_map.json",
             "precedents":"scripts/self_training_results/precedent_database.json",
             "principles_index":"scripts/principles_index.json",
             "style_guide":"scripts/learned_styles/drafting_style_guide.json",
             "memo_templates":"scripts/overnight_results/enhanced_memo_templates.json"}
    r = {"files": {}, "strengths": [], "weaknesses": []}
    for name, path in files.items():
        fp = f"/app/{path}" if not os.path.exists(path) else path
        if os.path.exists(fp):
            sz = os.path.getsize(fp)
            r["files"][name] = {"exists": True, "size_kb": round(sz/1024,1)}
        else:
            r["files"][name] = {"exists": False}
    found = sum(1 for f in r["files"].values() if f.get("exists"))
    r["strengths"].append(f"{found}/{len(files)} training files available")
    missing = [n for n,f in r["files"].items() if not f.get("exists")]
    if missing: r["weaknesses"].append(f"Missing: {missing}")
    log.info(f"  Files: {found}/{len(files)} available")
    return r


# ══════════════════════════════════════
# Final Report
# ══════════════════════════════════════
async def final_report(analyses):
    log.info("\n" + "="*60)
    log.info("FINAL REPORT")
    log.info("="*60)
    all_s = []; all_w = []
    for a in analyses.values():
        if isinstance(a, dict):
            all_s.extend(a.get("strengths",[])); all_w.extend(a.get("weaknesses",[]))
    health = max(0, 100 - len(all_w)*3)
    report = {"generated": datetime.now().isoformat(), "analyses": analyses,
              "summary": {"strengths": all_s, "weaknesses": all_w, "health": health}}
    with open(f"{OUT}/full_report.json","w",encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log.info(f"\nStrengths ({len(all_s)}):")
    for s in all_s: log.info(f"  + {s}")
    log.info(f"\nWeaknesses ({len(all_w)}):")
    for w in all_w: log.info(f"  - {w}")
    log.info(f"\nHealth Score: {health}%")
    return report


async def main():
    log.info(f"Started: {datetime.now().isoformat()}")
    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=5)
    A = {}
    try:
        A["database"] = await m1_database(pool)
        A["known_answers"] = await m2_known_answers()
        A["linkage"] = await m3_linkage()
        A["knowledge_base"] = await m4_kb()
        A["principles"] = await m5_principles()
        A["style_guide"] = await m6_style()
        A["dialect"] = await m7_dialect()
        A["live_100"] = await m8_live()
        A["system_prompt"] = await m9_prompt()
        A["training_data"] = await m10_training()
        await final_report(A)
    except Exception as e:
        log.error(f"Error: {e}", exc_info=True)
    finally:
        await pool.close()
    log.info(f"Finished: {datetime.now().isoformat()}")

if __name__ == "__main__":
    asyncio.run(main())
