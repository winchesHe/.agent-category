#!/usr/bin/env bash
# Jira Skill Benchmark — verifies all scripts against live Jira API
# Usage: source ~/.zshrc_secrets && bash evals/run-benchmark.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)/scripts"

PASS=0
FAIL=0
TOTAL=0

pass() { PASS=$((PASS + 1)); TOTAL=$((TOTAL + 1)); echo "  ✅ PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); TOTAL=$((TOTAL + 1)); echo "  ❌ FAIL: $1 — $2"; }

assert_exit_zero() { if [ "$1" -eq 0 ]; then pass "$2"; else fail "$2" "exit code $1"; fi; }
assert_exit_nonzero() { if [ "$1" -ne 0 ]; then pass "$2"; else fail "$2" "expected non-zero exit"; fi; }
assert_contains() {
    if echo "$1" | grep -q "$2" 2>/dev/null; then pass "$3"; else fail "$3" "missing '$2'"; fi
}
assert_not_contains() {
    if echo "$1" | grep -q "$2" 2>/dev/null; then fail "$3" "found unexpected '$2'"; else pass "$3"; fi
}
assert_regex() {
    if echo "$1" | grep -qE "$2" 2>/dev/null; then pass "$3"; else fail "$3" "regex '$2' not matched"; fi
}
assert_stderr_contains() {
    if echo "$1" | grep -q "$2" 2>/dev/null; then pass "$3"; else fail "$3" "stderr missing '$2'"; fi
}

echo "============================================================"
echo "Jira Skill Benchmark"
echo "============================================================"
echo ""

# ============================================================
# 1. fetch-known-cs-ticket (CS-43404)
# ============================================================
echo "--- [1/10] jira-fetch-issue: known ticket CS-43404 ---"
OUT=$(python3 "$SCRIPT_DIR/jira-fetch-issue.py" CS-43404 2>/dev/null)
RC=$?
assert_exit_zero $RC "exit code 0"
assert_contains "$OUT" "## 基本信息" "has basic info section"
assert_contains "$OUT" "FinTech" "squad=FinTech"
assert_contains "$OUT" "P1-Critical" "priority=P1-Critical"
assert_contains "$OUT" "Confirmed" "status=Confirmed"
assert_contains "$OUT" "## Issue Description" "has ADF description"
assert_contains "$OUT" "## 关联单" "has related issues"
assert_contains "$OUT" "## 评论" "has comments"
assert_contains "$OUT" "DES-761" "related issue DES-761"
assert_contains "$OUT" "FIN-6100" "related issue FIN-6100"
assert_contains "$OUT" "## 客户信息" "has customer info"
assert_contains "$OUT" "## 附件" "has attachments"

# ============================================================
# 2. fetch — ADF extraction quality
# ============================================================
echo ""
echo "--- [2/10] jira-fetch-issue: ADF extraction quality ---"
assert_contains "$OUT" "## Bug Description" "has bug description section"
assert_contains "$OUT" "## Cause and Solution" "has cause and solution"
# Verify ADF is extracted to plain text, not raw JSON
assert_not_contains "$OUT" '"type":"doc"' "no raw ADF JSON in output"
assert_not_contains "$OUT" '"type": "doc"' "no raw ADF JSON (spaced) in output"

# ============================================================
# 3. fetch — customer info fields
# ============================================================
echo ""
echo "--- [3/10] jira-fetch-issue: customer info fields ---"
assert_contains "$OUT" "User Tier" "has user tier"
assert_contains "$OUT" "Assignee" "has assignee"
assert_contains "$OUT" "Reporter" "has reporter"

# ============================================================
# 4. search-by-keyword
# ============================================================
echo ""
echo "--- [4/10] jira-search: keyword 'debit card' ---"
OUT4=$(python3 "$SCRIPT_DIR/jira-search.py" 'project = CS AND summary ~ "debit card"' 2>/dev/null)
RC=$?
assert_exit_zero $RC "exit code 0"
assert_contains "$OUT4" "CS-43404" "contains target ticket CS-43404"
assert_regex "$OUT4" "\\[IC:" "results contain Issue Cause tag"
assert_regex "$OUT4" "返回 [0-9]+ 条结果" "header shows result count"

# ============================================================
# 5. search-by-squad-filter
# ============================================================
echo ""
echo "--- [5/10] jira-search: squad=FinTech, limit 5 ---"
OUT5=$(python3 "$SCRIPT_DIR/jira-search.py" 'project = CS AND cf[10089] = FinTech ORDER BY created DESC' --limit 5 2>/dev/null)
RC=$?
assert_exit_zero $RC "exit code 0"
assert_regex "$OUT5" "返回 5 条结果" "exactly 5 results"
assert_contains "$OUT5" "[FinTech]" "results contain FinTech tag"
# Verify all lines have FinTech (no missing squad [-])
RESULT_LINES=$(echo "$OUT5" | grep "^CS-" | grep -v "\[FinTech\]" | wc -l | tr -d ' ')
if [ "$RESULT_LINES" -eq 0 ]; then pass "all results are FinTech"; else fail "all results are FinTech" "$RESULT_LINES non-FinTech lines"; fi

# ============================================================
# 6. search — pagination indicator
# ============================================================
echo ""
echo "--- [6/10] jira-search: pagination (limit 2) ---"
OUT6=$(python3 "$SCRIPT_DIR/jira-search.py" 'project = CS ORDER BY created DESC' --limit 2 2>/dev/null)
RC=$?
assert_exit_zero $RC "exit code 0"
assert_regex "$OUT6" "返回 2 条结果" "exactly 2 results"
assert_contains "$OUT6" "还有更多结果" "pagination indicator present"

# ============================================================
# 7. search — closed with root cause
# ============================================================
echo ""
echo "--- [7/10] jira-search: closed tickets with root cause ---"
OUT7=$(python3 "$SCRIPT_DIR/jira-search.py" 'project = CS AND summary ~ "overdue" AND status = Closed ORDER BY created DESC' --limit 5 2>/dev/null)
RC=$?
assert_exit_zero $RC "exit code 0"
assert_regex "$OUT7" "\\[IC:" "closed tickets contain Issue Cause tag"
assert_contains "$OUT7" "[Closed]" "results show Closed status"

# ============================================================
# 8. search — linked issues query
# ============================================================
echo ""
echo "--- [8/10] jira-search: linked issues (FIN-6100) ---"
OUT8=$(python3 "$SCRIPT_DIR/jira-search.py" 'project = CS AND issue in linkedIssues("FIN-6100") ORDER BY created DESC' --limit 5 2>/dev/null)
RC=$?
assert_exit_zero $RC "exit code 0"
assert_contains "$OUT8" "CS-43404" "CS-43404 linked to FIN-6100"

# ============================================================
# 9. error — invalid issue key
# ============================================================
echo ""
echo "--- [9/10] jira-fetch-issue: error — non-existent ticket ---"
ERR9=$(python3 "$SCRIPT_DIR/jira-fetch-issue.py" CS-99999999 2>&1)
RC=$?
assert_exit_nonzero $RC "non-zero exit code"
assert_contains "$ERR9" '"error"' "structured error JSON present"

# ============================================================
# 10. error — malformed JQL
# ============================================================
echo ""
echo "--- [10/10] jira-search: error — malformed JQL ---"
ERR10=$(python3 "$SCRIPT_DIR/jira-search.py" 'project = NONEXISTENT AND summary ~' 2>&1)
RC=$?
assert_exit_nonzero $RC "non-zero exit code"
assert_contains "$ERR10" '"error"' "structured error JSON present"

# ============================================================
# 11. update — whitelist rejection (unknown field)
# ============================================================
echo ""
echo "--- [11/14] jira-update-issue: whitelist rejection ---"
ERR11=$(python3 "$SCRIPT_DIR/jira-update-issue.py" CS-43404 --patch '{"status":"Done"}' 2>&1)
RC=$?
assert_exit_nonzero $RC "non-zero exit for unknown field"
assert_contains "$ERR11" "Unknown patch fields" "error mentions unknown fields"

# ============================================================
# 12. update — empty patch rejection
# ============================================================
echo ""
echo "--- [12/14] jira-update-issue: empty patch rejection ---"
ERR12=$(python3 "$SCRIPT_DIR/jira-update-issue.py" CS-43404 --patch '{}' 2>&1)
RC=$?
assert_exit_nonzero $RC "non-zero exit for empty patch"
assert_contains "$ERR12" "at least one supported field" "error mentions empty patch"

# ============================================================
# 13. download — host whitelist rejection
# ============================================================
echo ""
echo "--- [13/14] jira-download-attachment: host rejection ---"
OUT13=$(python3 "$SCRIPT_DIR/jira-download-attachment.py" 'https://evil.example.com/malware.png' 2>/dev/null)
RC=$?
assert_exit_nonzero $RC "non-zero exit for non-Jira host"
assert_contains "$OUT13" "host_not_allowed" "error mentions host not allowed"
assert_contains "$OUT13" '"ok": false' "result ok=false"

# ============================================================
# 14. download — invalid URL rejection
# ============================================================
echo ""
echo "--- [14/14] jira-download-attachment: invalid URL ---"
OUT14=$(python3 "$SCRIPT_DIR/jira-download-attachment.py" 'not-a-url' 2>/dev/null)
RC=$?
assert_exit_nonzero $RC "non-zero exit for invalid URL"
assert_contains "$OUT14" '"ok": false' "result ok=false for invalid URL"

# ============================================================
# Summary
# ============================================================
echo ""
echo "============================================================"
echo "RESULTS: $PASS/$TOTAL passed, $FAIL failed"
echo "============================================================"

exit $FAIL
