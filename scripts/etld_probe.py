# -*- coding: utf-8 -*-
"""
ETLD diagnostic probe — PHASE 8 repro test set.

Runs 5 canonical scenarios through the live unified pipeline, captures
the full response, reconstructs ExecutionTraces, scans for anomalies,
and emits a ROOT_CAUSES report + final VERDICT.

Invoke:
    python scripts/etld_probe.py
"""
from __future__ import annotations

import io
import logging
import os
import sys

# Repo root on sys.path so `core.*` imports resolve when run as a script
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# UTF-8 stdout (for Arabic)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Quiet the runtime logger during probe (we read structured output)
logging.getLogger("production_runtime").setLevel(logging.WARNING)

# runtime_v2 cutover — the probe now runs through the v2 adapter.
# No legacy runtime is reachable.
from core.runtime_v2.adapter import answer_json as _v2_answer_json


def answer_query_direct(query: str, session_id: str = "direct") -> dict:
    """Diagnostic shim routed through runtime_v2. Kept so probe scripts
    work without rewriting every call site."""
    return _v2_answer_json(query, session_id=session_id)


from core.conversation import get_state_engine
from core.runtime.etld import (
    build_trace_from_response, detect_anomalies,
    render_trace_report, render_root_causes_report,
)


# ═════════════════════════════════════════════════════════════════
# PHASE 8 — repro test set
# ═════════════════════════════════════════════════════════════════

REPRO_CASES = [
    (
        "partnership_vs_work_dual_memo",
        "شراكة أم عمل؟ اكتب مذكرة مزدوجة — شريكي يأخذ راتباً شهرياً ويشارك في الإدارة.",
    ),
    (
        "cheque_guarantee_no_contract",
        "اكتب مذكرة دفاع في قضية شيك بدون رصيد — الشيك كان ضماناً ولا يوجد عقد مكتوب.",
    ),
    (
        "pre_death_transfer_plus_debt",
        "مرض الموت — تنازل والدي عن قطعة أرض قبل وفاته بأسبوعين مع وجود دين قديم.",
    ),
    (
        "ip_ownership",
        "ملكية الكود البرمجي — للمطور أم الشركة؟ الكود طُوّر داخل فترة العقد.",
    ),
    (
        "cyber_defamation_draft",
        "اكتب مذكرة دفاع في قضية سب إلكتروني — الحساب المنسوب ليس حسابي.",
    ),
]


def run_probe() -> None:
    traces = []
    print("=" * 100)
    print("ETLD — Execution Trace & Leak Detector (ROOT CAUSE PROBE)")
    print("=" * 100)

    for idx, (label, query) in enumerate(REPRO_CASES, 1):
        # Clean state per test
        get_state_engine().reset(f"etld_{label}")
        response = answer_query_direct(query, f"etld_{label}")

        trace = build_trace_from_response(
            response,
            raw_query=query,
            entry_point="TEST",
            handler="scripts.etld_probe.run_probe",
        )
        detect_anomalies(trace)
        traces.append(trace)

        print()
        print(f"──[ CASE {idx}/{len(REPRO_CASES)} ]  {label}")
        print(render_trace_report(trace))

    # ── Final ROOT_CAUSES + VERDICT ──
    root_causes, verdict = render_root_causes_report(traces)

    print()
    print("=" * 100)
    print("ROOT_CAUSES  (structured)")
    print("=" * 100)
    if not root_causes:
        print("  (none)")
    else:
        for i, rc in enumerate(root_causes, 1):
            print(f"[{i}] type     = {rc.get('type')}")
            print(f"    location = {rc.get('location')}")
            print(f"    trigger  = {rc.get('trigger')}")
            print(f"    evidence = {rc.get('evidence')}")
            print(f"    impact   = {rc.get('impact')}")
            et = rc.get("evidence_trace", {}) or {}
            print(f"    trace    = mlre_req={et.get('mlre_required')} "
                  f"mlre_exec={et.get('mlre_executed')} "
                  f"dlp_req={et.get('dlp_required')} "
                  f"dlp_exec={et.get('dlp_executed')} "
                  f"survivors={et.get('survivors')} "
                  f"author={et.get('final_author')} "
                  f"composer={et.get('composer_inputs')} "
                  f"sigs={et.get('signatures')}")
            print(f"    request  = {rc.get('request_id')}")
            print(f"    query    = {rc.get('raw_query')!r}")
            print()

    print("=" * 100)
    print(verdict)
    print("=" * 100)


if __name__ == "__main__":
    run_probe()
