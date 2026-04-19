# -*- coding: utf-8 -*-
"""
إعادة فهرسة شاملة لجميع التشريعات قيد التطبيق من موقع الميزان
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
الميزات:
  • يجمع جميع 8,515 قانون قيد التطبيق
  • يجلب كل مادة حرفاً حرفاً من الموقع الرسمي
  • يستخرج الجداول HTML داخل المواد بتنسيق احترافي
  • يستخدم LawView.aspx للقوانين التي لا تظهر مواد مباشرة
  • يقارن مع محتوى DB ويصحح الأخطاء
  • قابل للاستئناف عند الانقطاع
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import re, ssl, sys, time, json, os, io, logging, traceback, hashlib
import requests, psycopg2, urllib3
from bs4 import BeautifulSoup, NavigableString
from requests.adapters import HTTPAdapter
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ─── Logging ───────────────────────────────────────────
log_handlers = [
    logging.FileHandler("full_reindex.log", encoding="utf-8"),
    logging.StreamHandler(sys.stdout),
]
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    handlers=log_handlers)
log = logging.getLogger(__name__)

# ─── إعدادات ───────────────────────────────────────────
BASE_URL      = "https://www.almeezan.qa"
DB_CONN       = "host=127.0.0.1 port=5432 dbname=ragdb user=raguser password=RAGsecret2024!"
OLLAMA_URL    = "http://localhost:11434/api/embeddings"
PROGRESS_FILE = "full_reindex_progress.json"
STATUS_ACTIVE = "2445"   # قيد التطبيق

UNICODE_JUNK = ['\u202a','\u202b','\u202c','\u202d','\u202e',
                '\u200e','\u200f','\u200b','\u200c','\u200d',
                '\ufeff','\x0c','\u00ad','\x00']

# كلمات تدل على محتوى تنقل (UI navigation) يجب رفضه
NAV_JUNK_KEYWORDS = [
    'إبحث في مواد التشريع',
    'البوابة القانونية القطرية',
    'تحميل PDF',
    'تحميل WORD',
    'تحميل صوتي',
    'الجريدة الرسمية\n',
    'إنشاء  مجموعة جديدة',
    'سنة الإصدار\n',
    'ادخل اسم المجموعة',
    'Login with Facebook',
    'Login with Google',
    'Login with',
]

STATS = {"processed": 0, "new_articles": 0, "updated": 0,
         "tables_extracted": 0, "errors": 0, "skipped": 0}

# ─── HTTP Session ──────────────────────────────────────
class TLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.set_ciphers('DEFAULT@SECLEVEL=1')
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)

SESSION = requests.Session()
SESSION.verify = False
_adapter = TLSAdapter(max_retries=urllib3.Retry(total=4, backoff_factor=2))
SESSION.mount("https://", _adapter)
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
    "Accept-Language": "ar,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})

def fetch(url, params=None, timeout=12):
    for attempt in range(4):
        try:
            r = SESSION.get(url, params=params, timeout=timeout, verify=False)
            if r.status_code == 200:
                return r
            time.sleep(2 ** attempt)
        except Exception as e:
            log.debug(f"fetch attempt {attempt+1} {url}: {e}")
            time.sleep(2 * (attempt + 1))
    return None

# ─── تنظيف النص ───────────────────────────────────────
def clean(text):
    if not text:
        return ""
    for c in UNICODE_JUNK:
        text = text.replace(c, '')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def is_junk_content(text):
    """يتحقق أن المحتوى ليس HTML navigation أو UI elements"""
    if not text or len(text) < 15:
        return True
    for kw in NAV_JUNK_KEYWORDS:
        if kw in text:
            return True
    # كشف قوائم السنوات (dropdown filter) - 5 أرقام متتالية كل منها في سطر
    if re.search(r'\b20\d\d\n20\d\d\n20\d\d\n20\d\d\n', text):
        return True
    if re.search(r'\b19\d\d\n19\d\d\n19\d\d\n', text):
        return True
    return False

def filter_nav_lines(text):
    """يُصفّي أسطر التنقل من النص ويحتفظ فقط بالمحتوى القانوني"""
    lines = text.split('\n')
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        # تخطى الأسطر الفارغة المتكررة
        if not stripped:
            if clean_lines and clean_lines[-1] != '':
                clean_lines.append('')
            continue
        # تخطى أسطر السنوات (مثل: 2024, 2023, ...)
        if re.fullmatch(r'\d{4}', stripped):
            continue
        # تخطى أسطر navigation keywords
        if any(kw.strip() in stripped for kw in NAV_JUNK_KEYWORDS if kw.strip()):
            continue
        # تخطى أسطر مثل "الكل" أو "طباعة" وحدها
        if stripped in ('الكل', 'طباعة', 'رؤية', 'التحميل'):
            continue
        clean_lines.append(line)
    return '\n'.join(clean_lines).strip()

def strip_nav_elements(soup_element):
    """يزيل عناصر التنقل من HTML قبل استخراج النص"""
    for tag in soup_element.find_all(['script','style','nav','header','footer']):
        tag.decompose()
    # أزل divs التي تحتوي حصرياً على كلمات navigation
    for div in soup_element.find_all(['div','span','ul','li']):
        txt = div.get_text(strip=True)
        if txt and len(txt) < 200:
            if any(kw.strip() in txt for kw in NAV_JUNK_KEYWORDS if kw.strip()):
                div.decompose()
    return soup_element

# ─── استخراج الجداول بشكل احترافي ────────────────────
def extract_tables_from_soup(soup_element):
    """
    يستخرج جميع جداول HTML ويحوّلها إلى نص منسق احترافياً.
    مثال:
      | الجريمة | العقوبة | المادة |
      | سرقة | السجن سنة | 324 |
    """
    tables_text = []
    for table in soup_element.find_all('table'):
        rows_text = []
        # استخرج العناوين (thead أو أول صف)
        headers = []
        thead = table.find('thead')
        if thead:
            for th in thead.find_all(['th', 'td']):
                headers.append(th.get_text(strip=True))

        # استخرج الصفوف
        tbody = table.find('tbody') or table
        for row in tbody.find_all('tr'):
            cells = []
            for cell in row.find_all(['td', 'th']):
                # دمج النص الداخلي بما في ذلك القوائم الفرعية
                cell_text = ' '.join(cell.get_text(' ', strip=True).split())
                cells.append(cell_text)
            if cells and any(c for c in cells):
                rows_text.append(' | '.join(cells))

        if rows_text:
            table_str = ""
            if headers:
                table_str = '| ' + ' | '.join(headers) + ' |\n'
                table_str += '|' + '---|' * len(headers) + '\n'
            table_str += '\n'.join('| ' + r + ' |' for r in rows_text)
            tables_text.append(table_str)
            STATS["tables_extracted"] += 1

    return tables_text

def extract_content_with_tables(soup_element):
    """
    يستخرج النص الكامل مع الجداول المنسقة من عنصر HTML.
    يحافظ على ترتيب النص والجداول كما وردت في الأصل.
    """
    parts = []
    for child in soup_element.descendants:
        if isinstance(child, NavigableString):
            txt = str(child).strip()
            if txt and not all(c in ' \t\n\r' for c in txt):
                parts.append(txt)
        elif child.name == 'table':
            # تحويل الجدول إلى نص
            rows = []
            for row in child.find_all('tr'):
                cells = [c.get_text(strip=True) for c in row.find_all(['td','th'])]
                if any(cells):
                    rows.append(' | '.join(cells))
            if rows:
                parts.append('\n[جدول]\n' + '\n'.join(rows) + '\n')
            # لا نكرر محتوى الجدول من خلال الـ descendants
            for tag in child.find_all(True):
                tag.decompose()
        elif child.name in ('br', 'p', 'div', 'li', 'h1','h2','h3','h4'):
            if parts and not parts[-1].endswith('\n'):
                parts.append('\n')

    return clean(' '.join(parts))

# ─── Embedding ─────────────────────────────────────────
def get_embedding(text):
    try:
        r = requests.post(OLLAMA_URL,
                         json={"model": "nomic-embed-text", "prompt": text[:1500]},
                         timeout=60)
        if r.status_code == 200:
            return r.json().get("embedding")
    except:
        pass
    return None

# ─── جلب مواد القانون عبر صفحة القانون ───────────────
def get_article_ids_from_page(law_id):
    """يجلب معرفات مواد القانون من صفحة LawPage.aspx"""
    r = fetch(f"{BASE_URL}/LawPage.aspx", params={"id": law_id, "language": "ar"})
    if not r:
        return [], {}

    soup = BeautifulSoup(r.text, "html.parser")

    # استخراج بيانات القانون من بطاقة التشريع
    meta = {}
    full_text = soup.get_text()
    nm = re.search(r'رقم[^\d]*(\d+)[^\d]*لسنة[^\d]*(\d+)', full_text)
    if nm:
        meta["number"] = nm.group(1)
        meta["year"]   = nm.group(2)

    # استخراج العنوان الرسمي
    h = soup.find('h2') or soup.find('h1') or soup.find(id=re.compile('title|label', re.I))
    if h:
        meta["official_name"] = re.sub(r'\s+', ' ', h.get_text()).strip()

    tab = soup.find(id="ContentPlaceHolder1_tablesection")
    if not tab:
        for div in soup.find_all(["div","ul","table"]):
            if re.search(r'LawArticleID=\d+|LawTreeSectionID=\d+', str(div)):
                tab = div
                break

    if not tab:
        return [], meta

    html_tab   = str(tab)
    direct_ids = list(dict.fromkeys(re.findall(r'LawArticleID=(\d+)', html_tab)))
    tree_ids   = list(dict.fromkeys(re.findall(r'LawTreeSectionID=(\d+)', html_tab)))

    all_art_ids = list(direct_ids)

    if tree_ids and not direct_ids:
        for sec_id in tree_ids:
            time.sleep(0.2)
            r2 = fetch(f"{BASE_URL}/LawArticles.aspx", params={
                "LawTreeSectionID": sec_id, "lawId": law_id, "language": "ar"
            })
            if r2:
                for a in re.findall(r'LawArticleID=(\d+)', r2.text):
                    if a not in all_art_ids:
                        all_art_ids.append(a)

    return all_art_ids, meta

def get_article_text_and_tables(article_id, law_id):
    """
    يجلب نص المادة الكاملة مع استخراج الجداول بتنسيق احترافي.
    يُعيد: (نص_كامل، له_جداول)
    """
    for attempt in range(3):
        r = fetch(f"{BASE_URL}/LawArticles.aspx", params={
            "LawArticleID": article_id, "LawId": law_id, "language": "ar"
        })
        if r:
            soup = BeautifulSoup(r.text, "html.parser")
            cd = soup.find(id="ContentPlaceHolder1_ContentDiv")
            if cd:
                has_tables = bool(cd.find('table'))
                if has_tables:
                    # استخرج النص مع الجداول المنسقة
                    text = extract_content_with_tables(cd)
                else:
                    text = clean(cd.get_text('\n', strip=False))
                return text, has_tables
        time.sleep(2)
    return "", False

# ─── استخراج القانون كاملاً من LawView ────────────────
def get_law_via_lawview(law_id, law_name):
    """
    يجلب القانون كاملاً من LawView.aspx.
    يُستخدم للقوانين التي لا تظهر مواد مباشرة في LawPage.
    يُعيد: قائمة من {art_num, content}
    """
    r = fetch(f"{BASE_URL}/LawView.aspx",
              params={"opt": "", "LawID": law_id, "language": "ar"})
    if not r:
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    # ابحث عن محتوى القانون (يستخدم ContentPlaceHolder12)
    content_div = (
        soup.find(id="ContentPlaceHolder12_divTreeDetails") or
        soup.find(id="ContentPlaceHolder12_NotesHolders") or
        soup.find(id=re.compile(r'ContentPlaceHolder\d+_div', re.I)) or
        soup.find(id=re.compile(r'Content.*Tree|Content.*Law', re.I))
    )

    if not content_div:
        return []

    # أزل عناصر التنقل قبل استخراج النص
    content_div = strip_nav_elements(content_div)

    articles = []

    # حاول تقسيم المحتوى حسب المواد
    full_text = content_div.get_text('\n', strip=False)
    full_text = clean(full_text)
    full_text = filter_nav_lines(full_text)  # أزل أسطر التنقل

    if not full_text or len(full_text) < 20:
        return []

    # قسّم على أساس "المادة رقم"
    parts = re.split(r'(المادة\s+\d+(?:\s*مكرر\s*\d*)?)', full_text)

    if len(parts) > 2:
        # تقسيم نجح - كل جزء هو مادة
        i = 0
        while i < len(parts) - 1:
            if re.match(r'المادة\s+\d+', parts[i]):
                art_header = parts[i].strip()
                art_body = parts[i+1].strip() if i+1 < len(parts) else ""
                art_num_m = re.search(r'(\d+(?:\s*مكرر\s*\d*)?)', art_header)
                art_num = art_num_m.group(1).strip() if art_num_m else str(len(articles)+1)
                content = f"{art_header}\n{art_body}"
                if len(content) > 15:
                    articles.append({"art_num": art_num, "content": content})
                i += 2
            else:
                i += 1

    if not articles:
        # لم ينجح التقسيم - أضف كل النص كمقطع واحد
        articles.append({"art_num": "نص_كامل", "content": full_text[:2000]})

    # استخراج الجداول كعناصر منفصلة
    for table in content_div.find_all('table'):
        rows = []
        for row in table.find_all('tr'):
            cells = [c.get_text(strip=True) for c in row.find_all(['td','th'])]
            if any(cells):
                rows.append(' | '.join(cells))
        if rows:
            table_text = '[جدول قانوني]\n' + '\n'.join(rows)
            articles.append({"art_num": f"جدول-{len(articles)+1}", "content": table_text})
            STATS["tables_extracted"] += 1

    return articles

# ─── قراءة التقدم المحفوظ ─────────────────────────────
def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"done_ids": [], "all_laws": [], "laws_collected": False}

def save_progress(progress):
    tmp = PROGRESS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PROGRESS_FILE)

# ─── جمع كل قوانين قيد التطبيق ─────────────────────────
def collect_all_laws():
    log.info("=" * 65)
    log.info("جمع جميع قوانين قيد التطبيق من الميزان...")
    laws = []
    seen_ids = set()
    page = 1

    while True:
        params = {"status": STATUS_ACTIVE, "kind": "0",
                  "pageNumber": str(page), "language": "ar"}
        r = fetch(f"{BASE_URL}/LawsByYear.aspx", params=params)
        if not r:
            log.error(f"فشل جلب الصفحة {page}")
            break

        soup = BeautifulSoup(r.text, "html.parser")
        page_laws = 0

        for a in soup.find_all("a", href=True):
            m = re.search(r'LawPage\.aspx\?.*?id=(\d+)', a["href"], re.I)
            if m:
                lid = m.group(1)
                if lid in seen_ids:
                    continue
                seen_ids.add(lid)
                title = re.sub(r'\s+', ' ', a.get_text()).strip()
                if len(title) < 5:
                    continue
                nm = re.search(r'رقم[^\d]*(\d+)[^\d]*لسنة[^\d]*(\d+)', title)
                num  = nm.group(1) if nm else "0"
                year = nm.group(2) if nm else "0"
                laws.append({"id": lid, "name": title[:200], "number": num, "year": year})
                page_laws += 1

        # تحقق من وجود صفحة تالية
        next_link = soup.find("a", string=re.compile("التالية|Next", re.I))
        has_next = next_link and "pageNumber" in str(next_link.get("href", ""))

        if page % 20 == 0:
            log.info(f"  >>> صفحة {page}: إجمالي {len(laws)} قانون حتى الآن")

        if not has_next or page_laws == 0:
            log.info(f"  صفحة {page}: {page_laws} جديد — توقف")
            break

        page += 1
        time.sleep(0.4)

    log.info(f"إجمالي القوانين المجموعة: {len(laws)}")
    return laws

# ─── الفهرسة في قاعدة البيانات ────────────────────────
def upsert_article(cur, law_name, law_number, law_year, art_num, content,
                   existing_map):
    """يضيف أو يحدّث مادة في DB. يُعيد ('new'|'updated'|'skip')"""
    full_content = clean(f"[{law_name}]\nالمادة {art_num}\n{content}"[:2000])
    if len(full_content) < 15:
        return 'skip'
    # رفض محتوى navigation HTML
    if is_junk_content(full_content):
        return 'skip'
    # رفض law_name فارغ
    if not law_name or not law_name.strip():
        return 'skip'

    # ─── فحص التطابق أولاً — لا نحسب embedding إذا لم يتغير المحتوى ───
    if art_num in existing_map:
        old_norm = re.sub(r'\s+', '', existing_map[art_num])
        new_norm = re.sub(r'\s+', '', full_content)
        if old_norm == new_norm:
            return 'skip'   # متطابق — لا شيء يحتاج تحديث

    # ─── احسب embedding فقط للمحتوى الجديد أو المتغير ───
    emb = get_embedding(full_content)
    emb_str = "[" + ",".join(f"{x:.8f}" for x in emb) + "]" if emb else None

    if art_num in existing_map:
        # المحتوى تغيّر — حدّث (يستخدم law_name لتفادي تعديل قانون آخر بنفس الرقم/السنة)
        if emb_str:
            cur.execute("""
                UPDATE chunks SET content=%s, embedding=%s::vector
                WHERE law_name=%s AND law_number=%s AND law_year=%s
                  AND article_number=%s AND source='almeezan'
            """, (full_content, emb_str, law_name, law_number, law_year, art_num))
        else:
            cur.execute("""
                UPDATE chunks SET content=%s
                WHERE law_name=%s AND law_number=%s AND law_year=%s
                  AND article_number=%s AND source='almeezan'
            """, (full_content, law_name, law_number, law_year, art_num))
        return 'updated'
    else:
        # مادة جديدة — أضف
        if emb_str:
            cur.execute("""
                INSERT INTO chunks
                (law_name,law_number,law_year,article_number,content,embedding,source)
                VALUES(%s,%s,%s,%s,%s,%s::vector,'almeezan')
                ON CONFLICT (law_name,law_number,law_year,article_number)
                WHERE source='almeezan'
                DO UPDATE SET content=EXCLUDED.content, embedding=EXCLUDED.embedding
            """, (law_name, law_number, law_year, art_num, full_content, emb_str))
        else:
            cur.execute("""
                INSERT INTO chunks
                (law_name,law_number,law_year,article_number,content,source)
                VALUES(%s,%s,%s,%s,%s,'almeezan')
                ON CONFLICT (law_name,law_number,law_year,article_number)
                WHERE source='almeezan'
                DO UPDATE SET content=EXCLUDED.content
            """, (law_name, law_number, law_year, art_num, full_content))
        return 'new'

# ─── معالجة قانون واحد ────────────────────────────────
def process_law(law, conn):
    law_id   = law["id"]
    law_name = law["name"]
    law_num  = law["number"]
    law_year = law["year"]

    log.info(f"[{law_id}] {law_name[:70]}")

    # 1. جلب معرفات المواد
    art_ids, meta = get_article_ids_from_page(law_id)

    # تحديث البيانات من الصفحة إذا كانت أدق
    if meta.get("number") and meta["number"] != "0":
        law_num = meta["number"]
    if meta.get("year") and meta["year"] != "0":
        law_year = meta["year"]
    if meta.get("official_name"):
        law_name = meta["official_name"][:200]

    articles = []

    if art_ids:
        log.info(f"  {len(art_ids)} مادة — جلب تفصيلي...")
        for i, art_id in enumerate(art_ids, 1):
            text, has_tables = get_article_text_and_tables(art_id, law_id)
            if not text or len(text) < 10:
                time.sleep(0.15)
                continue

            # استخرج رقم المادة من بداية النص
            m = re.match(r'المادة\s+(\d+(?:\s*مكرر\s*\d*)?)', text.strip())
            art_num = m.group(1).strip() if m else str(i)
            articles.append({"art_num": art_num, "content": text,
                             "has_tables": has_tables})
            if has_tables:
                log.info(f"    م.{art_num}: تحتوي جداول")
            # طباعة تقدم كل 30 مادة
            if i % 30 == 0:
                log.info(f"    جلب {i}/{len(art_ids)} مادة...")
            time.sleep(0.25)

    else:
        # fallback: استخدم LawView
        log.info(f"  لا مواد مباشرة — جرب LawView...")
        articles = get_law_via_lawview(law_id, law_name)
        if articles:
            log.info(f"  LawView: {len(articles)} مقطع")

    if not articles:
        log.info(f"  [SKIP] لا محتوى — {law_id}")
        STATS["skipped"] += 1
        return 0, 0

    # 2. جلب المحتوى الموجود في DB لهذا القانون بالاسم الدقيق
    cur = conn.cursor()
    cur.execute(
        "SELECT article_number, content FROM chunks "
        "WHERE law_name=%s AND law_number=%s AND law_year=%s AND source='almeezan'",
        (law_name, law_num, law_year)
    )
    existing_map = {row[0]: row[1] for row in cur.fetchall()}

    # 3. Upsert كل مادة
    new_count = upd_count = skip_count = 0
    for art in articles:
        try:
            result = upsert_article(cur, law_name, law_num, law_year,
                                    art["art_num"], art["content"], existing_map)
            if result == 'new':
                new_count += 1
            elif result == 'updated':
                upd_count += 1
            else:
                skip_count += 1
        except Exception as e:
            log.error(f"  DB upsert error م.{art.get('art_num')}: {e}")
            conn.rollback()

    conn.commit()
    cur.close()

    tables_found = sum(1 for a in articles if a.get("has_tables"))
    log.info(f"  مواد: {len(articles)} | جديد: {new_count} | محدّث: {upd_count} "
             f"| متطابق: {skip_count} | جداول: {tables_found}")

    STATS["new_articles"] += new_count
    STATS["updated"]      += upd_count

    return len(articles), new_count + upd_count

# ─── Main ──────────────────────────────────────────────
def main():
    start_time = datetime.now()
    log.info("=" * 70)
    log.info("بدء إعادة الفهرسة الشاملة — " + start_time.strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 70)

    progress = load_progress()
    done_ids = set(progress.get("done_ids", []))

    if not progress.get("laws_collected"):
        all_laws = collect_all_laws()
        progress["all_laws"] = all_laws
        progress["laws_collected"] = True
        save_progress(progress)
        log.info(f"حُفظ {len(all_laws)} قانون")
    else:
        all_laws = progress.get("all_laws", [])
        log.info(f"استئناف: {len(all_laws)} قانون — مكتمل: {len(done_ids)}")

    conn = psycopg2.connect(DB_CONN)

    remaining = [law for law in all_laws if law["id"] not in done_ids]
    total     = len(all_laws)
    log.info(f"متبقٍ: {len(remaining)} من {total}")

    for i, law in enumerate(remaining, 1):
        try:
            arts, changes = process_law(law, conn)
            STATS["processed"] += 1
            done_ids.add(law["id"])
            progress["done_ids"] = list(done_ids)

            # حفظ بعد كل قانون (لضمان الاستئناف الصحيح)
            save_progress(progress)

            if i % 5 == 0:
                elapsed = (datetime.now() - start_time).total_seconds()
                done_so_far = len(done_ids)
                pct = done_so_far * 100 // total
                rate = i / elapsed * 3600  # قوانين/ساعة
                eta = (len(remaining) - i) / max(rate, 0.01)

                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM chunks")
                db_total = cur.fetchone()[0]
                cur.close()

                log.info(
                    f"━━━ تقدم: {done_so_far}/{total} ({pct}%) "
                    f"| إجمالي DB: {db_total:,} "
                    f"| جديد: {STATS['new_articles']:,} "
                    f"| محدّث: {STATS['updated']:,} "
                    f"| جداول: {STATS['tables_extracted']:,} "
                    f"| الوقت المتبقي: {eta:.1f}h ━━━"
                )

            time.sleep(0.2)

        except KeyboardInterrupt:
            log.info("[!] توقف — حفظ التقدم...")
            save_progress(progress)
            break
        except Exception as e:
            log.error(f"خطأ في {law.get('id')}: {e}")
            log.debug(traceback.format_exc())
            STATS["errors"] += 1
            done_ids.add(law["id"])
            progress["done_ids"] = list(done_ids)
            continue

    save_progress(progress)
    conn.close()

    # التقرير النهائي
    elapsed = (datetime.now() - start_time).total_seconds()
    log.info("\n" + "=" * 70)
    log.info("اكتملت إعادة الفهرسة")
    log.info(f"  المدة: {elapsed/3600:.2f} ساعة")
    log.info(f"  تمت معالجة: {STATS['processed']:,} قانون")
    log.info(f"  مقاطع جديدة: {STATS['new_articles']:,}")
    log.info(f"  تحديثات: {STATS['updated']:,}")
    log.info(f"  جداول مستخرجة: {STATS['tables_extracted']:,}")
    log.info(f"  مُتخطى: {STATS['skipped']:,}")
    log.info(f"  أخطاء: {STATS['errors']:,}")

    conn2 = psycopg2.connect(DB_CONN)
    cur2  = conn2.cursor()
    cur2.execute("SELECT COUNT(*) FROM chunks")
    final_count = cur2.fetchone()[0]
    log.info(f"  إجمالي DB النهائي: {final_count:,}")
    cur2.close()
    conn2.close()
    log.info("=" * 70)

if __name__ == "__main__":
    import signal
    _progress_ref = [None]

    def _signal_handler(sig, frame):
        log.info("[!] إشارة إيقاف — حفظ التقدم...")
        if _progress_ref[0]:
            save_progress(_progress_ref[0])
        sys.exit(0)

    signal.signal(signal.SIGTERM, _signal_handler)
    try:
        signal.signal(signal.SIGBREAK, _signal_handler)  # Windows Ctrl+Break
    except (AttributeError, OSError):
        pass

    # تمرير مرجع progress للـ signal handler
    import builtins
    _orig_main = main

    def main_with_signal():
        import inspect
        # نشغل main() ونلتقط progress من داخلها
        _orig_main()

    main()
