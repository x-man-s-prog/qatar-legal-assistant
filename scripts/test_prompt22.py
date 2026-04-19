# -*- coding: utf-8 -*-
"""Test Prompt 22 — Real conversation problems"""
import requests
import json
import time

API = "http://localhost:80/api/v1/query/"
HEADERS = {
    "Content-Type": "application/json",
    "X-API-Key": "820757e90e8755cafbe48b858b6e5a2f3b5a4e710448a2b414aa902c83851394",
}

SID = "test22_conv"

def ask(q, sid=SID):
    r = requests.post(API, json={"query": q, "model": "openai", "session_id": sid}, headers=HEADERS, timeout=120)
    return r.json()

results = []

# Q1: تحية
print("Q1: سلام عليكم...", end=" ", flush=True)
d = ask("سلام عليكم")
results.append({"q": "سلام عليكم", "answer": d.get("answer","")[:300], "conf": d.get("confidence"), "sources": len(d.get("sources",[])), "domain": d.get("domain")})
print(f"OK conf={d.get('confidence')} sources={len(d.get('sources',[]))}")
time.sleep(2)

# Q2: قدرات
print("Q2: وش المهام...", end=" ", flush=True)
d = ask("وش المهام الي تقدر تسويها", sid="test22_q2")
results.append({"q": "وش المهام الي تقدر تسويها", "answer": d.get("answer","")[:400], "conf": d.get("confidence"), "sources": len(d.get("sources",[])), "domain": d.get("domain")})
print(f"OK conf={d.get('confidence')} domain={d.get('domain')}")
time.sleep(2)

# Q3: سحر
print("Q3: سحر...", end=" ", flush=True)
d = ask("وش يقول القانون عن السحر في قطر", sid="test22_q3")
results.append({"q": "وش يقول القانون عن السحر", "answer": d.get("answer","")[:500], "conf": d.get("confidence"), "sources": len(d.get("sources",[])), "domain": d.get("domain")})
has_299 = "299" in d.get("answer","")
print(f"OK conf={d.get('confidence')} has_299={has_299}")
time.sleep(2)

# Q4: شيك بدون رصيد — مذكرة
print("Q4: مذكرة شيك...", end=" ", flush=True)
d = ask("أنا متهم بشيك بدون رصيد الشيك ضمان بس مافي شي يثبت — صيغ لي مذكرة", sid="test22_cheque")
a = d.get("answer","")
has_blanks = "[رقم" in a or "[اسم" in a or "[___]" in a
has_357 = "357" in a
results.append({"q": "مذكرة شيك بدون رصيد", "answer": a[:500], "conf": d.get("confidence"), "blanks": has_blanks, "has_357": has_357, "domain": d.get("domain")})
print(f"OK conf={d.get('confidence')} blanks={has_blanks} has_357={has_357}")
time.sleep(2)

# Q5: تحليل مخدرات
print("Q5: تحليل مخدرات...", end=" ", flush=True)
d = ask("يحق لهم ياخذون مني تحليل مخدرات بعد ما فتشوني وما لقوا شي؟", sid="test22_q5")
a = d.get("answer","")
has_evasion = "أنصحك بالتواصل مع محامٍ" in a and len(a) < 200
results.append({"q": "تحليل مخدرات", "answer": a[:500], "conf": d.get("confidence"), "evasive": has_evasion, "domain": d.get("domain")})
print(f"OK conf={d.get('confidence')} evasive={has_evasion}")
time.sleep(2)

# Q6: متابعة بعد الشيك
print("Q6: متابعة...", end=" ", flush=True)
d = ask("طيب بعد المذكرة وش أسوي", sid="test22_cheque")  # same session as Q4
a = d.get("answer","")
about_cheque = any(w in a for w in ["شيك", "بدون رصيد", "المحكمة", "القضية", "المذكرة", "دفاع"])
results.append({"q": "طيب بعد المذكرة وش أسوي", "answer": a[:500], "conf": d.get("confidence"), "on_topic": about_cheque, "domain": d.get("domain")})
print(f"OK conf={d.get('confidence')} on_topic={about_cheque}")

# Save and display
with open("scripts/test22_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("\n" + "="*60)
print("RESULTS:")
print("="*60)
for i, r in enumerate(results, 1):
    print(f"\nQ{i}: {r['q']}")
    print(f"  conf={r.get('conf')} domain={r.get('domain')}")
    if 'blanks' in r: print(f"  blanks={r['blanks']} has_357={r.get('has_357')}")
    if 'evasive' in r: print(f"  evasive={r['evasive']}")
    if 'on_topic' in r: print(f"  on_topic={r['on_topic']}")
    if r.get('sources', 0) > 0: print(f"  WARNING: {r['sources']} sources in greeting!")

print("\nResults saved to scripts/test22_results.json")
