#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════
# POST-DEPLOY VALIDATION — Run after deploy_clean.sh
# ═══════════════════════════════════════════════════════════
# Tests that the latest code is active and producing correct output.
# Usage: chmod +x validate_deploy.sh && ./validate_deploy.sh
# ═══════════════════════════════════════════════════════════
set -uo pipefail

BASE_URL="${1:-http://localhost:8000}"
PASS=0
FAIL=0

GREEN='\033[0;32m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

check() {
    local desc="$1"
    local result="$2"
    local expected="$3"

    if echo "$result" | grep -q "$expected"; then
        echo -e "${GREEN}  ✅ $desc${NC}"
        PASS=$((PASS + 1))
    else
        echo -e "${RED}  ❌ $desc${NC}"
        echo -e "     Expected: $expected"
        echo -e "     Got: $(echo "$result" | head -3)"
        FAIL=$((FAIL + 1))
    fi
}

check_absent() {
    local desc="$1"
    local result="$2"
    local forbidden="$3"

    if echo "$result" | grep -q "$forbidden"; then
        echo -e "${RED}  ❌ $desc — found forbidden: $forbidden${NC}"
        FAIL=$((FAIL + 1))
    else
        echo -e "${GREEN}  ✅ $desc${NC}"
        PASS=$((PASS + 1))
    fi
}

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  POST-DEPLOY VALIDATION"
echo "  Target: $BASE_URL"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ── Test 1: Code version ──
echo -e "${CYAN}Test 1: Code version endpoint${NC}"
V=$(curl -s "$BASE_URL/debug/code-version" 2>/dev/null)
check "Endpoint responds" "$V" "REFUSAL_ENGINE_ACTIVE"
check "Has refusal engine" "$V" "deterministic_refusal_engine"
check "Has grade 8-10 support" "$V" "grade_8_9_10_support"
check "Test refusal works" "$V" "العاشرة"
echo ""

# ── Test 2: Grade-specific salary query ──
echo -e "${CYAN}Test 2: كم راتب الدرجة السابعة${NC}"
R2=$(curl -s -X POST "$BASE_URL/ask" \
  -H "Content-Type: application/json" \
  -d '{"query": "كم راتب الدرجة السابعة", "session_id": "test_deploy_001"}' 2>/dev/null)
check "Returns answer" "$R2" "answer"
check "Contains السابعة" "$R2" "السابعة"
check "Marked as structured" "$R2" "from_structured_lookup"
check_absent "No 📋 marker" "$R2" "📋"
check_absent "No full table (الممتازة should NOT appear)" "$R2" "الممتازة"
echo ""

# ── Test 3: Non-existent grade → refusal ──
echo -e "${CYAN}Test 3: راتب الدرجة العاشرة (should be refusal)${NC}"
R3=$(curl -s -X POST "$BASE_URL/ask" \
  -H "Content-Type: application/json" \
  -d '{"query": "راتب الدرجة العاشرة", "session_id": "test_deploy_002"}' 2>/dev/null)
check "Returns answer" "$R3" "answer"
check "Mentions العاشرة" "$R3" "العاشرة"
check "Contains 'غير موجودة' or 'غير متوفرة'" "$R3" "غير"
check_absent "No 📋 marker" "$R3" "📋"
check_absent "No full table dump (الأولى should NOT appear)" "$R3" "الأولى"
echo ""

# ── Test 4: Full table request ──
echo -e "${CYAN}Test 4: جدول الرواتب (full table is OK here)${NC}"
R4=$(curl -s -X POST "$BASE_URL/ask" \
  -H "Content-Type: application/json" \
  -d '{"query": "جدول الرواتب", "session_id": "test_deploy_003"}' 2>/dev/null)
check "Returns answer" "$R4" "answer"
check "Marked as structured" "$R4" "from_structured_lookup"
check_absent "No 📋 marker" "$R4" "📋"
echo ""

# ── Test 5: "فقط" constraint ──
echo -e "${CYAN}Test 5: كم مربوط الدرجة السابعة فقط${NC}"
R5=$(curl -s -X POST "$BASE_URL/ask" \
  -H "Content-Type: application/json" \
  -d '{"query": "كم مربوط الدرجة السابعة فقط", "session_id": "test_deploy_004"}' 2>/dev/null)
check "Returns answer" "$R5" "answer"
check "Contains السابعة" "$R5" "السابعة"
check_absent "No 📋 marker" "$R5" "📋"
check_absent "No other grade الثانية" "$R5" "الثانية"
echo ""

# ── Summary ──
TOTAL=$((PASS + FAIL))
echo "═══════════════════════════════════════════════════════════"
if [ $FAIL -eq 0 ]; then
    echo -e "  ${GREEN}ALL $TOTAL CHECKS PASSED ✅${NC}"
else
    echo -e "  ${RED}$FAIL/$TOTAL CHECKS FAILED ❌${NC}"
    echo -e "  ${GREEN}$PASS/$TOTAL CHECKS PASSED${NC}"
fi
echo "═══════════════════════════════════════════════════════════"
exit $FAIL
