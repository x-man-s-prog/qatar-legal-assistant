# دليل النشر — الميزان القانوني القطري

## 1. متطلبات السيرفر

| المورد | الحد الأدنى | الموصى به |
|--------|-------------|-----------|
| CPU    | 4 أنوية     | 8 أنوية   |
| RAM    | 8 GB        | 16 GB     |
| Storage| 50 GB SSD  | 100 GB SSD|
| OS     | Ubuntu 22.04 | Ubuntu 22.04 LTS |
| Docker | 24.0+       | آخر إصدار  |

**ملاحظات:**
- pgvector يحتاج PostgreSQL 15+ (مُضمَّن في Docker Compose)
- Ollama (اختياري) يحتاج GPU أو 8GB RAM إضافية للنموذج المحلي
- الـ embeddings تُخزَّن في DB — أول تشغيل يحتاج ~2GB إضافية لـ nomic-embed-text

---

## 2. تثبيت Docker + Docker Compose

```bash
# Ubuntu 22.04
curl -fsSL https://get.docker.com | bash
sudo usermod -aG docker $USER
newgrp docker

# تحقق
docker --version       # Docker 24.0+
docker compose version # Docker Compose 2.20+
```

---

## 3. إعداد ملف .env

```bash
# استنساخ القالب
cp .env.production.template .env

# تعديل القيم
nano .env   # أو vi .env

# توليد مفاتيح أمان قوية
echo "API_KEY=$(openssl rand -hex 32)"
echo "JWT_SECRET=$(openssl rand -hex 32)"
# انسخ القيم إلى .env
```

**أهم ما يجب تعديله:**
```env
DB_PASSWORD=<كلمة مرور قوية>
API_KEY=<openssl rand -hex 32>
JWT_SECRET=<openssl rand -hex 32>
OPENAI_API_KEY=sk-...         # أو Gemini/Claude
ALLOWED_ORIGINS=https://yourdomain.com
```

---

## 4. أوامر الإطلاق خطوة بخطوة

### الخطوة 1: استنساخ المشروع
```bash
git clone https://github.com/your-org/legal-assistant.git
cd legal-assistant
```

### الخطوة 2: إعداد البيئة
```bash
cp .env.production.template .env
# عدّل .env بقيمك الحقيقية
```

### الخطوة 3: تشغيل Docker Compose
```bash
docker compose up -d

# تحقق من التشغيل
docker compose ps
docker compose logs -f app
```

### الخطوة 4: فحص جاهزية البيئة
```bash
docker compose exec app python scripts/check_env.py
# يجب أن يُعيد: النظام جاهز للإنتاج
```

### الخطوة 5: فهرسة تشريعات الميزان
```bash
# تأكد من وجود ملفات الـ JSON في data/
docker compose exec app python index_almeezan_v3.py

# أو إذا لديك ملفات TXT
docker compose exec app python index_txt_v3.py --dir data/laws/

# تحقق من الفهرسة
docker compose exec app python scripts/fix_chunks.py --rebuild-index
```

### الخطوة 6: اختبار التكامل
```bash
docker compose exec app pytest tests/test_integration.py -v
# يجب أن تنجح 29/29
```

### الخطوة 7: اختبار الأداء
```bash
docker compose exec app python scripts/benchmark.py --live
# هدف: avg_confidence > 70%

docker compose exec app python scripts/stress_test.py --url http://localhost:8000
# هدف: error_rate < 1%
```

---

## 5. إعداد SSL بـ Certbot

```bash
# تثبيت Certbot
sudo apt install certbot python3-certbot-nginx -y

# الحصول على شهادة
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com

# التجديد التلقائي (يُضاف تلقائياً بواسطة certbot)
sudo systemctl status certbot.timer

# تحديث ALLOWED_ORIGINS في .env
ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
```

**nginx config مقترح** (`/etc/nginx/sites-available/mizan`):
```nginx
server {
    listen 443 ssl http2;
    server_name yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection keep-alive;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_buffering    off;       # ضروري لـ SSE streaming
        proxy_read_timeout 120s;
    }
}

server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;
    return 301 https://$host$request_uri;
}
```

---

## 6. استراتيجية النسخ الاحتياطي (PostgreSQL)

### النسخ اليومي التلقائي
```bash
# أنشئ سكريبت النسخ
cat > /usr/local/bin/backup-mizan.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/backups/mizan"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR

# نسخ DB
docker compose exec -T db pg_dump \
  -U raguser -d legal_rag \
  --no-password \
  -Fc -Z9 \
  > "$BACKUP_DIR/legal_rag_$DATE.dump"

# احتفظ بآخر 30 نسخة فقط
ls -t $BACKUP_DIR/*.dump | tail -n +31 | xargs rm -f
echo "Backup completed: legal_rag_$DATE.dump"
EOF
chmod +x /usr/local/bin/backup-mizan.sh

# إضافة Cron يومي (2 صباحاً)
echo "0 2 * * * root /usr/local/bin/backup-mizan.sh >> /var/log/mizan-backup.log 2>&1" \
  >> /etc/crontab
```

### الاستعادة من نسخة احتياطية
```bash
# استعادة DB
docker compose exec -T db pg_restore \
  -U raguser -d legal_rag \
  --no-password \
  -c < /backups/mizan/legal_rag_20260101_020000.dump
```

---

## 7. المراقبة — متى تعرف أن شيئاً انكسر؟

### مؤشرات تعني مشكلة حرجة
| المؤشر | الحد | الإجراء |
|--------|------|---------|
| `/api/v1/health` status != ok/healthy | فوري | تحقق من logs |
| `chunks_count` = 0 | فوري | أعِد الفهرسة |
| error_rate > 5% (stress_test) | < 5 دقائق | تحقق من DB/LLM |
| استجابة > 10 ثوانٍ | < 10 دقائق | أعِد تشغيل app |

### أوامر المراقبة اليومية
```bash
# صحة السيرفر
curl -s http://localhost:8000/api/v1/health | python3 -m json.tool

# أداء الـ pipeline
curl -s http://localhost:8000/api/v1/performance | python3 -m json.tool

# سجلات التطبيق (آخر 100 سطر)
docker compose logs --tail=100 app

# استخدام الموارد
docker stats --no-stream

# اختبار الاستجابة السريع
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query":"ما قانون العمل؟","model":"ollama"}' \
  | python3 -m json.tool
```

### إعداد تنبيه بريد إلكتروني (اختياري)
```bash
# تثبيت healthchecks.io أو استخدام cron مع curl
cat > /usr/local/bin/check-mizan-health.sh << 'EOF'
#!/bin/bash
STATUS=$(curl -s http://localhost:8000/api/v1/health | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(d.get('status','error'))
")
if [ "$STATUS" != "ok" ] && [ "$STATUS" != "healthy" ]; then
  echo "ALERT: Mizan health=$STATUS" | mail -s "Mizan Down!" admin@yourdomain.com
fi
EOF
chmod +x /usr/local/bin/check-mizan-health.sh

# كل 5 دقائق
echo "*/5 * * * * root /usr/local/bin/check-mizan-health.sh" >> /etc/crontab
```

---

## 8. تحديث التطبيق (Zero Downtime)

```bash
# سحب آخر تحديث
git pull origin main

# إعادة بناء الـ image بدون توقف
docker compose build app
docker compose up -d --no-deps app

# تحقق من النجاح
sleep 5 && curl -s http://localhost:8000/api/v1/health
```

---

## 9. قائمة التحقق قبل الإطلاق

- [ ] `python scripts/check_env.py` يُعيد "جاهز للإنتاج"
- [ ] `pytest tests/test_integration.py` — 29/29
- [ ] `python scripts/benchmark.py --live` — avg_confidence > 70%
- [ ] SSL شهادة مثبتة ومفعّلة
- [ ] النسخ الاحتياطي اليومي مُجدوَل
- [ ] `DB_PASSWORD` و `API_KEY` و `JWT_SECRET` قيم قوية وليست افتراضية
- [ ] `ALLOWED_ORIGINS` لا يحتوي localhost
- [ ] Docker Compose يعيد التشغيل تلقائياً: `restart: unless-stopped`
