# ═══════════════════════════════════════════════════════════════
# سكريبت نشر المساعد القانوني على GitHub بأمان
# ═══════════════════════════════════════════════════════════════
# التاريخ: 2026-04-19
# المستودع: legal-assistant-qa (Public)
# ═══════════════════════════════════════════════════════════════

$ErrorActionPreference = "Stop"
Set-Location "C:\Users\sa2005599\Desktop\المساعد القانوني\الكود"

Write-Host "`n══════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  نشر المساعد القانوني على GitHub" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════`n" -ForegroundColor Cyan

# ─────────────────────────────────────
# خطوة 1: التحقق من الأدوات المطلوبة
# ─────────────────────────────────────
Write-Host "[1/10] التحقق من الأدوات..." -ForegroundColor Yellow

$gitVer = git --version 2>$null
if (-not $gitVer) {
    Write-Host "  Git غير موجود. نصّبه من: https://git-scm.com" -ForegroundColor Red
    exit 1
}
Write-Host "  $gitVer" -ForegroundColor Green

$ghVer = gh --version 2>$null | Select-Object -First 1
if (-not $ghVer) {
    Write-Host "  GitHub CLI غير موجود. نصّبه من: https://cli.github.com" -ForegroundColor Red
    exit 1
}
Write-Host "  $ghVer" -ForegroundColor Green

# ─────────────────────────────────────
# خطوة 2: التحقق من تسجيل الدخول
# ─────────────────────────────────────
Write-Host "`n[2/10] التحقق من تسجيل الدخول لـ GitHub..." -ForegroundColor Yellow

$authStatus = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  لم تسجّل دخولك بعد. سيُفتح المتصفح..." -ForegroundColor Yellow
    gh auth login --hostname github.com --git-protocol https --web
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  فشل تسجيل الدخول. أعد المحاولة." -ForegroundColor Red
        exit 1
    }
}
Write-Host "  تسجيل الدخول: OK" -ForegroundColor Green

# ─────────────────────────────────────
# خطوة 3: إعدادات Git (الاسم والبريد)
# ─────────────────────────────────────
Write-Host "`n[3/10] إعدادات Git..." -ForegroundColor Yellow

$gitUser = git config user.name 2>$null
$gitEmail = git config user.email 2>$null

if (-not $gitUser) {
    $name = Read-Host "  اكتب اسمك لـ Git (مثال: Saleh)"
    git config --global user.name "$name"
    Write-Host "  user.name = $name" -ForegroundColor Green
} else {
    Write-Host "  user.name = $gitUser" -ForegroundColor Green
}

if (-not $gitEmail) {
    $email = Read-Host "  اكتب بريدك لـ GitHub"
    git config --global user.email "$email"
    Write-Host "  user.email = $email" -ForegroundColor Green
} else {
    Write-Host "  user.email = $gitEmail" -ForegroundColor Green
}

# ─────────────────────────────────────
# خطوة 4: بداية نظيفة (حذف .git القديم)
# ─────────────────────────────────────
Write-Host "`n[4/10] تهيئة Git (بداية نظيفة)..." -ForegroundColor Yellow

if (Test-Path ".git") {
    Write-Host "  حذف .git القديم..." -ForegroundColor DarkYellow
    Remove-Item -Recurse -Force ".git"
}
git init -b main 2>$null
Write-Host "  git init -b main: OK" -ForegroundColor Green

# ─────────────────────────────────────
# خطوة 5: فحص أمني
# ─────────────────────────────────────
Write-Host "`n[5/10] فحص أمني (البحث عن مفاتيح مكشوفة)..." -ForegroundColor Yellow

$leakCheck = Get-ChildItem -Recurse -File -Exclude "*.log","*.backup*","*.pyc" |
    Where-Object {
        $_.FullName -notmatch "\\\.git\\" -and
        $_.FullName -notmatch "\\node_modules\\" -and
        $_.FullName -notmatch "\\__pycache__\\" -and
        $_.Name -ne ".env" -and
        $_.Name -notmatch "^\.env\."
    } |
    Select-String -Pattern "sk-proj-[A-Za-z0-9_-]{30,}" -List

if ($leakCheck) {
    Write-Host "`n  !! تم العثور على مفاتيح API حقيقية مكشوفة:" -ForegroundColor Red
    $leakCheck | ForEach-Object {
        Write-Host "     $($_.Path):$($_.LineNumber)" -ForegroundColor Yellow
    }
    Write-Host "`n  توقف! يجب إزالة هذه المفاتيح قبل النشر." -ForegroundColor Red
    Write-Host "  لا تنشر أي شيء حتى تُصلح هذه المشكلة." -ForegroundColor Red
    exit 1
}
Write-Host "  لا مفاتيح مكشوفة" -ForegroundColor Green

# التحقق أن .env محمي
$envIgnored = git check-ignore .env 2>$null
if ($envIgnored) {
    Write-Host "  .env محمي بـ .gitignore" -ForegroundColor Green
} else {
    Write-Host "  تحذير: .env غير محمي! تحقق من .gitignore" -ForegroundColor Red
    exit 1
}

# ─────────────────────────────────────
# خطوة 6: إضافة الملفات
# ─────────────────────────────────────
Write-Host "`n[6/10] إضافة الملفات..." -ForegroundColor Yellow

git add .gitignore
git add .

# ─────────────────────────────────────
# خطوة 7: التحقق مما سيُرفع
# ─────────────────────────────────────
Write-Host "`n[7/10] التحقق النهائي قبل الـ commit..." -ForegroundColor Yellow

# تأكد أن .env ليس في القائمة
$stagedFiles = git diff --cached --name-only
$envInStage = $stagedFiles | Where-Object { $_ -match "^\.env$" }

if ($envInStage) {
    Write-Host "  !! خطر: .env على وشك أن يُرفع! إلغاء." -ForegroundColor Red
    git reset
    exit 1
}

# تأكد أن .env.backup ليس في القائمة
$backupInStage = $stagedFiles | Where-Object { $_ -match "\.env\.backup" }
if ($backupInStage) {
    Write-Host "  !! خطر: .env.backup على وشك أن يُرفع! إلغاء." -ForegroundColor Red
    git reset
    exit 1
}

# تأكد أن .claude/ ليس في القائمة
$claudeInStage = $stagedFiles | Where-Object { $_ -match "^\.claude/" }
if ($claudeInStage) {
    Write-Host "  !! خطر: .claude/ على وشك أن يُرفع! إلغاء." -ForegroundColor Red
    git reset
    exit 1
}

$fileCount = ($stagedFiles | Measure-Object).Count
Write-Host "  عدد الملفات: $fileCount ملف" -ForegroundColor Cyan
Write-Host "  .env محمي | .env.backup محمي | .claude محمي" -ForegroundColor Green

# عرض الملفات للمراجعة
Write-Host "`n  الملفات المُضافة:" -ForegroundColor DarkCyan
git diff --cached --name-only | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }

Write-Host ""
$confirm = Read-Host "  هل تريد المتابعة؟ (y/n)"
if ($confirm -ne "y") {
    Write-Host "  تم الإلغاء." -ForegroundColor Yellow
    git reset
    exit 0
}

# ─────────────────────────────────────
# خطوة 8: عمل Commit
# ─────────────────────────────────────
Write-Host "`n[8/10] عمل commit..." -ForegroundColor Yellow

git commit -m "feat: initial commit - Qatar Legal Assistant with 10-route phase0 system

- Phase 0 router with 10 intelligent routes
- Smart memo generation with runtime_v2
- DB handlers (articles, tables, calculator)
- Safety refusal + greeting + self_info routes
- OpenAI integration for general queries + continuation
- Docker Compose stack (app + db + redis + ollama)
- 21/21 routing accuracy on live tests
- Full test suite (458 tests)
- Arabic-first UI with voice input + PDF export"

Write-Host "  Commit: OK" -ForegroundColor Green

# ─────────────────────────────────────
# خطوة 9: إنشاء المستودع على GitHub
# ─────────────────────────────────────
Write-Host "`n[9/10] إنشاء المستودع على GitHub..." -ForegroundColor Yellow

gh repo create "legal-assistant-qa" `
    --public `
    --source=. `
    --remote=origin `
    --push `
    --description "Qatar Legal Assistant — AI-powered legal memo generation with 10-route intelligent dispatch (Arabic)"

if ($LASTEXITCODE -ne 0) {
    Write-Host "  فشل إنشاء المستودع. تحقق من:" -ForegroundColor Red
    Write-Host "    - هل الاسم محجوز؟" -ForegroundColor Yellow
    Write-Host "    - هل أنت مسجّل دخولك؟ (gh auth status)" -ForegroundColor Yellow
    exit 1
}
Write-Host "  المستودع أُنشئ ورُفع!" -ForegroundColor Green

# ─────────────────────────────────────
# خطوة 10: التحقق النهائي
# ─────────────────────────────────────
Write-Host "`n[10/10] التحقق النهائي..." -ForegroundColor Yellow

$repoUrl = gh repo view --json url -q ".url" 2>$null
Write-Host "`n  المستودع: $repoUrl" -ForegroundColor Cyan

# تحقق نهائي: .env ليس على GitHub
$remoteFiles = gh api "repos/{owner}/{repo}/contents" -q ".[].name" 2>$null
if ($remoteFiles -match "^\.env$") {
    Write-Host "`n  !! خطر! .env موجود على GitHub!" -ForegroundColor Red
    Write-Host "  نفّذ فوراً:" -ForegroundColor Red
    Write-Host "  git rm --cached .env && git commit -m 'remove .env' && git push" -ForegroundColor Yellow
} else {
    Write-Host "  .env: محمي (لم يُرفع)" -ForegroundColor Green
}

# إضافة README و .env.example كـ commit ثاني
Write-Host "`n  إضافة README.md و .env.example..." -ForegroundColor Yellow
git add README.md .env.example .env.production.template
git commit -m "docs: add README, .env.example, and production template"
git push

Write-Host "`n══════════════════════════════════════" -ForegroundColor Green
Write-Host "  تم بنجاح! المشروع على GitHub:" -ForegroundColor Green
Write-Host "  $repoUrl" -ForegroundColor Cyan
Write-Host "══════════════════════════════════════`n" -ForegroundColor Green
