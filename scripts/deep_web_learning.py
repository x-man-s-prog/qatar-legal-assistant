#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/deep_web_learning.py — تعلّم شامل من الإنترنت (8 مسارات)
يعمل محلياً. القاعدة الحديدية: فقط قطر — صفر خلط.
"""
import os, json, re, time, logging, ssl, subprocess, sys
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.parse import quote

OUT = "scripts/deep_web_learning"
for d in ["raw","extracted"]: os.makedirs(f"{OUT}/{d}", exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(f"{OUT}/learning.log", encoding="utf-8", mode="w")])
log = logging.getLogger("dwl")
try:
    _sh = logging.StreamHandler(open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False))
    _sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(_sh)
except: pass

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
BL = ["القانون المصري","القانون الكويتي","القانون الإماراتي","القانون السعودي",
      "محكمة النقض المصرية","محكمة التمييز الكويتية","جمهورية مصر","دولة الكويت",
      "قانون العقوبات المصري","قانون المرافعات المصري"]
QM = ["قطر","القطري","القطرية","الدوحة","Qatar","Qatari","almeezan"]

def fetch(url, timeout=20):
    for _ in range(2):
        try:
            ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
            raw = urlopen(Request(url, headers={"User-Agent":UA,"Accept-Language":"ar,en"}), context=ctx, timeout=timeout).read()
            for e in ["utf-8","windows-1256","iso-8859-6"]:
                try: return raw.decode(e)
                except: pass
            return raw.decode("utf-8", errors="ignore")
        except: time.sleep(1)
    return None

def clean(html):
    if not html: return ""
    t = re.sub(r'<(script|style)[^>]*>.*?</\1>','',html,flags=re.DOTALL)
    t = re.sub(r'<[^>]+>',' ',t)
    return re.sub(r'\s+',' ',re.sub(r'&\w+;',' ',t)).strip()

def is_qatar(text):
    if not text: return False
    return any(m in text for m in QM) and sum(1 for m in QM if m in text) >= sum(1 for b in BL if b in text)

def purify(text):
    return ". ".join(s.strip() for s in re.split(r'[.\n]',text) if not any(b in s for b in BL) and len(s.strip())>15)

def search(query, n=5):
    for eng in [f"https://www.google.com/search?q={quote(query)}&hl=ar&num={n}",
                f"https://html.duckduckgo.com/html/?q={quote(query)}"]:
        html = fetch(eng, 12)
        if html:
            links = re.findall(r'href="(https?://[^"]{20,})"', html)
            links = [l for l in links if not any(x in l for x in ['google','bing','duckduckgo','youtube','facebook'])]
            if links: return list(dict.fromkeys(links))[:n]
        time.sleep(1)
    return []

# ═══ 8 مسارات ═══
def path1():
    log.info("=== Path 1: Direct sources ===")
    c=[]
    for url in ["https://www.almeezan.qa/LawPage.aspx?id=1&language=ar",
                "https://www.moj.gov.qa/ar/Pages/default.aspx",
                "https://www.tamimi.com/law-update-modules/?country=qatar"]:
        html=fetch(url)
        if html:
            t=clean(html)
            if len(t)>300 and is_qatar(t):
                c.append({"url":url,"text":purify(t)[:8000],"source":"direct"})
                log.info(f"  OK: {url[:50]}")
        time.sleep(3)
    return c

def path2():
    log.info("=== Path 2: Search engines ===")
    c=[]
    for q in ["شرح قانون العمل القطري","تعديلات القوانين القطرية 2024",
              "إجراءات رفع دعوى في قطر","Qatar labor law guide 2024",
              "Qatar employment termination rights","محكمة التمييز القطرية مبادئ"]:
        log.info(f"  {q[:35]}")
        for url in search(q)[:2]:
            html=fetch(url)
            if html:
                t=clean(html)
                if len(t)>400 and is_qatar(t):
                    c.append({"url":url,"text":purify(t)[:8000],"source":"search","query":q})
                    log.info(f"    OK: {url[:50]}")
            time.sleep(2)
        time.sleep(3)
    return c

def path3():
    log.info("=== Path 3: Social/forums ===")
    c=[]
    for q in ["site:reddit.com Qatar law","site:quora.com Qatar worker rights",
              "تجربتي مع المحاكم في قطر"]:
        for url in search(q)[:2]:
            html=fetch(url)
            if html:
                t=clean(html)
                if len(t)>200 and is_qatar(t):
                    c.append({"url":url,"text":purify(t)[:5000],"source":"social"})
                    log.info(f"    OK: {url[:50]}")
            time.sleep(2)
        time.sleep(3)
    return c

def path4():
    log.info("=== Path 4: Academic ===")
    c=[]
    for q in ["Qatar legal system research","النظام القانوني القطري بحث"]:
        for url in search(q)[:2]:
            if url.endswith('.pdf'): continue
            html=fetch(url)
            if html:
                t=clean(html)
                if len(t)>300 and is_qatar(t):
                    c.append({"url":url,"text":purify(t)[:8000],"source":"academic"})
                    log.info(f"    OK: {url[:50]}")
            time.sleep(2)
        time.sleep(3)
    return c

def path5():
    log.info("=== Path 5: Real cases ===")
    c=[]
    for q in ["قضية حقيقية قطر حكم محكمة","Qatar court case analysis",
              "سوابق قضائية قطرية 2024"]:
        for url in search(q)[:2]:
            html=fetch(url)
            if html:
                t=clean(html)
                if len(t)>300 and is_qatar(t) and any(w in t for w in ["حكم","قضية","محكمة","court"]):
                    c.append({"url":url,"text":purify(t)[:8000],"source":"case"})
                    log.info(f"    OK: {url[:50]}")
            time.sleep(2)
        time.sleep(3)
    return c

def path6():
    log.info("=== Path 6: Loopholes ===")
    c=[]
    for q in ["ثغرات قانونية في قطر","Qatar law challenges criticism"]:
        for url in search(q)[:2]:
            html=fetch(url)
            if html:
                t=clean(html)
                if len(t)>300 and is_qatar(t):
                    c.append({"url":url,"text":purify(t)[:5000],"source":"loophole"})
                    log.info(f"    OK: {url[:50]}")
            time.sleep(2)
        time.sleep(3)
    return c

def path7():
    log.info("=== Path 7: Lawyer style ===")
    c=[]
    for q in ["فن المرافعة القانونية","أسلوب المحامي الناجح","legal reasoning skills"]:
        for url in search(q)[:2]:
            html=fetch(url)
            if html:
                t=clean(html)
                if len(t)>300:
                    c.append({"url":url,"text":purify(t)[:5000],"source":"style"})
                    log.info(f"    OK: {url[:50]}")
            time.sleep(2)
        time.sleep(3)
    return c

def path8_builtin():
    log.info("=== Path 8: Builtin knowledge ===")
    return {
        "cases": [
            {"topic":"فصل تعسفي","pattern":"عامل فُصل بعد رفض استقالة مزورة → تعويض 3 أشهر + مكافأة + بدل إشعار","lesson":"رفض التوقيع على استقالة مزورة حق قانوني"},
            {"topic":"شيك ضمان","pattern":"المتهم أثبت بمراسلات أن الشيك ضمان → براءة لانتفاء القصد","lesson":"إثبات طبيعة الشيك كضمان يحتاج دليل كتابي"},
            {"topic":"بطلان تفتيش","pattern":"إذن تفتيش للمسكن → فتّش السيارة → بطلان الدليل","lesson":"تجاوز حدود الإذن يبطل الدليل"},
            {"topic":"دفاع شرعي","pattern":"ضرب معتدي → قبول الدفاع (خطر حال + ضرورة + تناسب)","lesson":"3 شروط للدفاع الشرعي"},
            {"topic":"تقادم","pattern":"دعوى تعويض بعد 4 سنوات → سقوط (3 سنوات من العلم)","lesson":"التقادم يبدأ من العلم بالضرر"},
            {"topic":"حضانة","pattern":"أم تزوجت → أب طلب نقل → المحكمة أبقت الحضانة (مصلحة الطفل)","lesson":"زواج الأم لا يسقط حضانتها تلقائياً"},
            {"topic":"عيب خفي","pattern":"عيب اكتُشف بعد 8 أشهر → البائع أخفاه عمداً → سقط حق التمسك بالمهلة","lesson":"الغش يسقط كل الدفوع"},
            {"topic":"شرط جزائي","pattern":"تأخر 6 أشهر → شرط 10% → المحكمة خفّضته","lesson":"المحكمة تخفّض الشرط المبالغ فيه (م.265)"},
        ],
        "reasoning": [
            {"name":"القياس","desc":"تطبيق حكم على حالة مشابهة","example":"أخذ بنية الإرجاع ≠ سرقة"},
            {"name":"التفسير الضيق","desc":"النصوص الجنائية لا تتوسع","example":"الشك لصالح المتهم"},
            {"name":"الموازنة","desc":"عند تعارض حقين","example":"حق الإدارة vs حق الاستقرار"},
            {"name":"تحليل الأركان","desc":"انتفاء ركن = لا جريمة","example":"اعتقاد أنه ملكه = لا سرقة"},
            {"name":"السببية","desc":"هل الفعل سبب مباشر","example":"تجاوز إشارة + مشاة من مكان ممنوع"},
            {"name":"المسؤولية المزدوجة","desc":"جنائي ≠ مدني — يمكن الجمع","example":"التصالح جنائياً لا يسقط الحق المدني"},
        ],
        "loopholes": [
            {"issue":"غموض 'الإخلال الجسيم' م.61 عمل","use":"يُفسّر لصالح العامل"},
            {"issue":"الشيك بين الوفاء والضمان","use":"استشهد بأحكام قبلت دفع الضمان"},
            {"issue":"حجز جواز رغم التجريم","use":"دليل على سوء نية صاحب العمل"},
            {"issue":"تعارض اختصاص المحاكم","use":"دفع شكلي بعدم الاختصاص"},
        ],
        "style": [
            "ومن المسلّمات القانونية التي لا تحتاج إلى تدليل أن...",
            "والقاعدة أن الأحكام الجنائية تُبنى على الجزم واليقين لا على الظن والاحتمال",
            "ومتى انتفى الركن المعنوي للجريمة فلا قيام لها حتى لو توافر الركن المادي",
            "والمقرر في قضاء هذه المحكمة أن عبء الإثبات يقع على من يدّعي خلاف الأصل",
            "ولا محل للقول بأن... إذ إن هذا القول يتنافى مع صحيح القانون",
            "ومن المستقر عليه أن الحكم يجب أن يُحيط بأدلة الدعوى ويعرض لها عرضاً كافياً",
            "والشك يُفسّر لمصلحة المتهم، وهو من المبادئ الراسخة في القانون الجنائي",
            "ولا يسع المحكمة إلا أن تلتفت عن هذا الدفع لعدم استناده إلى سند",
            "ومن نافلة القول — لكن للأمانة القانونية — نشير إلى أن...",
            "والمحكمة — وهي بصدد تقييم أدلة الاتهام — تلاحظ أن...",
        ],
    }

def extract_and_store(all_content, builtin):
    log.info("=== Extract & Store ===")
    knowledge = {"procedures":[],"deadlines":[],"updates":[],"tips":[],"penalties":[],"interpretations":[],
                 "cases":builtin["cases"],"reasoning":builtin["reasoning"],"loopholes":builtin["loopholes"],"style":builtin["style"]}
    pats = {"procedures":[r'(?:يجب|يتعين|للتقدم)\s+[^.]{20,300}\.'],
            "deadlines":[r'(?:خلال|مدة|أجل)\s+\d+\s+(?:يوم|شهر|سنة)[^.]{10,200}\.'],
            "updates":[r'(?:تعديل|صدر)[^.]*202[3-6][^.]{10,300}\.'],
            "tips":[r'(?:يُنصح|يُوصى|من\s+الأفضل)[^.]{20,300}\.'],
            "penalties":[r'(?:يُعاقب|عقوبة|الحبس)\s+[^.]{20,300}\.'],
            "interpretations":[r'(?:يُقصد\s+بـ|المقصود|بمعنى\s+أن)[^.]{20,300}\.']}
    for c in all_content:
        for cat, ps in pats.items():
            for p in ps:
                for m in re.finditer(p, c.get("text",""), re.UNICODE):
                    t=m.group(0).strip()
                    if not any(b in t for b in BL) and 30<len(t)<400:
                        knowledge[cat].append({"text":t,"source":c.get("source","")})
    # Deduplicate
    for k in knowledge:
        if isinstance(knowledge[k],list):
            seen=set(); u=[]
            for i in knowledge[k]:
                if isinstance(i,dict):
                    key = (i.get("text","") or i.get("pattern","") or i.get("name","") or i.get("issue","") or str(i))[:60]
                else:
                    key = str(i)[:60]
                if key not in seen: seen.add(key); u.append(i)
            knowledge[k]=u
    # Verify
    all_json = json.dumps(knowledge, ensure_ascii=False)
    viol = sum(1 for b in BL if b in all_json)
    if viol:
        for k in knowledge:
            if isinstance(knowledge[k],list):
                knowledge[k]=[i for i in knowledge[k] if not any(b in json.dumps(i,ensure_ascii=False) for b in BL)]
    # Save
    with open(f"{OUT}/comprehensive_knowledge.json","w",encoding="utf-8") as f:
        json.dump(knowledge, f, ensure_ascii=False, indent=2)
    total = sum(len(v) for v in knowledge.values() if isinstance(v,list))
    report = {"timestamp":datetime.now().isoformat(),"pages":len(all_content),"total":total,
              "by_cat":{k:len(v) if isinstance(v,list) else 0 for k,v in knowledge.items()},"violations":0}
    with open(f"{OUT}/report.json","w",encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    try:
        subprocess.run(["docker","cp",OUT,"legal_app:/app/scripts/deep_web_learning"],capture_output=True,timeout=15)
        log.info("  Copied to Docker")
    except: pass
    log.info(f"\nRESULT: {len(all_content)} pages -> {total} items | 0 violations")
    for k,v in knowledge.items():
        if isinstance(v,list) and v:
            log.info(f"  {k}: {len(v)}")
    return report

def main():
    log.info(f"Started: {datetime.now().isoformat()}")
    c = []
    c.extend(path1()); c.extend(path2()); c.extend(path3())
    c.extend(path4()); c.extend(path5()); c.extend(path6()); c.extend(path7())
    builtin = path8_builtin()
    log.info(f"\nInternet pages: {len(c)}")
    extract_and_store(c, builtin)
    log.info(f"Finished: {datetime.now().isoformat()}")

if __name__ == "__main__":
    main()
