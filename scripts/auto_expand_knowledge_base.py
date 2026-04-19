# -*- coding: utf-8 -*-
"""
scripts/auto_expand_knowledge_base.py
يحلل فهرس الربط (article_ruling_compact.json) ويكتشف المواد غير المغطاة يدوياً.
"""
import json
import os
import sys

# أضف المسار الأب لاستيراد TOPIC_TO_ARTICLES
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.legal_knowledge_base import TOPIC_TO_ARTICLES


def load_index(index_path=None):
    if index_path is None:
        index_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "article_ruling_compact.json"
        )
    with open(index_path, "r", encoding="utf-8") as f:
        return json.load(f)


def analyze_coverage(index: dict):
    """يحلل التغطية: كم مادة مغطاة يدوياً وكم غير مغطاة."""

    # جمع كل المراجع المغطاة يدوياً
    covered_refs = set()
    for topic_data in TOPIC_TO_ARTICLES.values():
        for ref in topic_data["refs"]:
            # استخرج رقم المادة واسم القانون
            parts = ref.replace("م", "").split("_")
            article_num = parts[0] if parts else ""
            law_name = parts[1] if len(parts) > 1 else ""
            covered_refs.add(f"م{article_num}_{law_name}")

    # حلل الفهرس
    total_keys = len(index)
    total_rulings = sum(len(v) for v in index.values())

    # طابق مفاتيح الفهرس مع المغطاة
    covered_in_index = 0
    uncovered = {}

    for key, ruling_ids in index.items():
        matched = False
        for cref in covered_refs:
            # مطابقة مرنة: م308 + عقوبات
            parts_c = cref.split("_")
            if len(parts_c) >= 2:
                art_num = parts_c[0]  # مثل م308
                law = parts_c[1]      # مثل عقوبات
                if art_num in key and (law in key or law.lower() in key.lower()):
                    matched = True
                    break
        if matched:
            covered_in_index += 1
        else:
            uncovered[key] = len(ruling_ids)

    return {
        "total_keys": total_keys,
        "total_rulings": total_rulings,
        "covered_refs": len(covered_refs),
        "covered_in_index": covered_in_index,
        "uncovered_count": len(uncovered),
        "uncovered": uncovered,
    }


def main():
    index = load_index()
    result = analyze_coverage(index)

    print("=" * 60)
    print("تحليل تغطية القاعدة المعرفية")
    print("=" * 60)
    print(f"إجمالي مفاتيح الفهرس: {result['total_keys']}")
    print(f"إجمالي أحكام التمييز المربوطة: {result['total_rulings']}")
    print(f"مراجع مغطاة يدوياً (TOPIC_TO_ARTICLES): {result['covered_refs']}")
    print(f"مواد في الفهرس مغطاة: {result['covered_in_index']}")
    print(f"مواد في الفهرس غير مغطاة: {result['uncovered_count']}")
    print()
    print("-" * 60)
    print("أكثر 30 مادة غير مغطاة ذُكرت في أحكام التمييز:")
    print("-" * 60)

    sorted_uncovered = sorted(
        result["uncovered"].items(),
        key=lambda x: x[1],
        reverse=True,
    )

    for i, (key, count) in enumerate(sorted_uncovered[:30], 1):
        print(f"  {i:2d}. {key} — {count} حكم تمييز")

    print()
    print("=" * 60)
    print("توصية: أضف المواد الأكثر ذكراً في الأحكام إلى TOPIC_TO_ARTICLES")
    print("=" * 60)

    return result


if __name__ == "__main__":
    main()
