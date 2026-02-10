#!/usr/bin/env python3
"""Compare two baseline JSON files and report differences.

Usage:
    python tests/_compare_baselines.py                          # auto-detect latest two
    python tests/_compare_baselines.py tests/baseline_v0.7.2.json tests/baseline_v0.8.0.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


# ANSI colors
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def load_baselines(args: list[str]) -> tuple[dict, dict]:
    """Load old and new baseline files from args or auto-detect."""
    if len(args) == 2:
        old = json.loads(Path(args[0]).read_text())
        new = json.loads(Path(args[1]).read_text())
        return old, new

    # Auto-detect: find all baseline_v*.json files, pick the two most recent by version
    test_dir = Path(__file__).parent
    files = sorted(test_dir.glob("baseline_v*.json"))
    if len(files) < 2:
        print("Need at least two baseline files to compare.", file=sys.stderr)
        sys.exit(1)

    old = json.loads(files[-2].read_text())
    new = json.loads(files[-1].read_text())
    print(f"{DIM}Comparing: {files[-2].name} -> {files[-1].name}{RESET}\n")
    return old, new


def pct_change(old_val: float, new_val: float) -> float | None:
    if old_val == 0:
        return None
    return ((new_val - old_val) / abs(old_val)) * 100


def format_delta(old_val, new_val, lower_is_better: bool = False, is_timing: bool = False) -> str:
    """Format a value comparison with colored delta."""
    if old_val == new_val:
        return f"{DIM}(unchanged){RESET}"

    pct = pct_change(float(old_val), float(new_val))
    if pct is None:
        direction = "new" if new_val != 0 else "removed"
        return f"{YELLOW}{direction}{RESET}"

    sign = "+" if pct > 0 else ""
    # For timing metrics, higher is worse; for counts, depends on context
    if is_timing:
        color = RED if pct > 5 else GREEN if pct < -5 else DIM
    elif lower_is_better:
        color = GREEN if pct < 0 else RED if pct > 0 else DIM
    else:
        color = DIM  # neutral for non-directional metrics

    return f"{color}{sign}{pct:.1f}%{RESET}"


def compare_section(title: str, old: dict, new: dict, meta: dict[str, dict]) -> list[str]:
    """Compare a section of the baseline. Returns list of formatted lines.

    meta maps key -> {"label": str, "lower_is_better": bool, "timing": bool, "unit": str}
    """
    lines = []
    lines.append(f"\n{BOLD}{title}{RESET}")
    lines.append(f"  {'Metric':<35s} {'v' + old.get('version', '?'):>12s} {'v' + new.get('version', '?'):>12s}   Delta")
    lines.append(f"  {'─' * 35} {'─' * 12} {'─' * 12}   {'─' * 10}")

    all_keys = list(dict.fromkeys(list(old.keys()) + list(new.keys())))
    for key in all_keys:
        if key not in meta:
            continue
        m = meta[key]
        old_val = old.get(key, "—")
        new_val = new.get(key, "—")

        if old_val == "—" or new_val == "—":
            delta = f"{YELLOW}{'added' if old_val == '—' else 'removed'}{RESET}"
        else:
            delta = format_delta(
                old_val, new_val,
                lower_is_better=m.get("lower_is_better", False),
                is_timing=m.get("timing", False),
            )

        unit = m.get("unit", "")
        label = m.get("label", key)

        # Format values
        def fmt(v):
            if v == "—":
                return "—"
            if isinstance(v, float):
                if m.get("timing"):
                    return f"{v:.4f}{unit}"
                return f"{v:.4f}{unit}" if v < 100 else f"{v:,.0f}{unit}"
            return f"{v:,}{unit}" if isinstance(v, int) else str(v)

        lines.append(f"  {label:<35s} {fmt(old_val):>12s} {fmt(new_val):>12s}   {delta}")

    return lines


def main():
    old, new = load_baselines(sys.argv[1:])

    old_ver = old.get("version", "?")
    new_ver = new.get("version", "?")

    print(f"{BOLD}Baseline Comparison: v{old_ver} → v{new_ver}{RESET}")
    print(f"Python: {old.get('python', '?')} → {new.get('python', '?')}")

    all_lines: list[str] = []

    # --- Chunking ---
    old_c = old.get("chunking", {})
    new_c = new.get("chunking", {})
    # inject version for header
    old_c["version"] = old_ver
    new_c["version"] = new_ver
    all_lines.extend(compare_section("Chunking", old_c, new_c, {
        "l1_chapters":          {"label": "L1 chapters"},
        "l2_sections":          {"label": "L2 sections"},
        "l3_passages":          {"label": "L3 passages"},
        "total_l3_tokens":      {"label": "Total L3 tokens"},
        "l3_token_min":         {"label": "L3 token min"},
        "l3_token_max":         {"label": "L3 token max"},
        "l3_token_median":      {"label": "L3 token median"},
        "l3_token_mean":        {"label": "L3 token mean"},
        "median_time_s":        {"label": "Chunking time (median)", "timing": True, "lower_is_better": True, "unit": "s"},
        "throughput_chars_per_s": {"label": "Throughput", "unit": " ch/s"},
    }))

    # --- Token Counting ---
    old_t = old.get("token_counting", {})
    new_t = new.get("token_counting", {})
    old_t["version"] = old_ver
    new_t["version"] = new_ver
    all_lines.extend(compare_section("Token Counting", old_t, new_t, {
        "text_chars":           {"label": "Text chars"},
        "token_count":          {"label": "Token count"},
        "median_per_call_ms":   {"label": "Per-call time (median)", "timing": True, "lower_is_better": True, "unit": "ms"},
    }))

    # --- Storage ---
    old_s = old.get("storage_roundtrip", {})
    new_s = new.get("storage_roundtrip", {})
    old_s["version"] = old_ver
    new_s["version"] = new_ver
    all_lines.extend(compare_section("Storage Round-Trip", old_s, new_s, {
        "save_median_s":  {"label": "Save (median)", "timing": True, "lower_is_better": True, "unit": "s"},
        "load_median_s":  {"label": "Load (median)", "timing": True, "lower_is_better": True, "unit": "s"},
    }))

    # --- Content Coverage ---
    old_cc = old.get("content_coverage", {})
    new_cc = new.get("content_coverage", {})
    old_cc["version"] = old_ver
    new_cc["version"] = new_ver
    all_lines.extend(compare_section("Content Coverage", old_cc, new_cc, {
        "input_leaf_chars":  {"label": "Input leaf chars"},
        "l3_output_chars":   {"label": "L3 output chars"},
        "coverage_ratio":    {"label": "Coverage ratio"},
    }))

    # --- Hierarchy Linkage ---
    old_hl = old.get("hierarchy_linkage", {})
    new_hl = new.get("hierarchy_linkage", {})
    old_hl["version"] = old_ver
    new_hl["version"] = new_ver
    all_lines.extend(compare_section("Hierarchy Linkage", old_hl, new_hl, {
        "l3_orphan_count": {"label": "L3 orphans", "lower_is_better": True},
        "l2_orphan_count": {"label": "L2 orphans", "lower_is_better": True},
    }))

    # --- Disk Footprint ---
    old_df = old.get("disk_footprint", {})
    new_df = new.get("disk_footprint", {})
    old_df["version"] = old_ver
    new_df["version"] = new_ver
    all_lines.extend(compare_section("Disk Footprint", old_df, new_df, {
        "total_bytes": {"label": "Total bytes", "unit": "B"},
        "file_count":  {"label": "File count"},
    }))

    # --- Search Index Counts ---
    old_si = old.get("search_index_counts", {})
    new_si = new.get("search_index_counts", {})
    old_si["version"] = old_ver
    new_si["version"] = new_ver
    all_lines.extend(compare_section("Search Indexes", old_si, new_si, {
        "bm25_doc_count":          {"label": "BM25 documents"},
        "concept_index_term_count": {"label": "Concept index terms"},
    }))

    # --- Overlap ---
    old_ov = old.get("overlap_verification", {})
    new_ov = new.get("overlap_verification", {})
    old_ov["version"] = old_ver
    new_ov["version"] = new_ver
    all_lines.extend(compare_section("Overlap Verification", old_ov, new_ov, {
        "overlap_pairs_total":               {"label": "Consecutive pairs"},
        "overlap_pairs_with_shared_content":  {"label": "Pairs with overlap"},
    }))

    # --- Multi-Format Parsing (v0.8.0+) ---
    old_mf = old.get("multiformat_parsing", {})
    new_mf = new.get("multiformat_parsing", {})
    if old_mf or new_mf:
        all_lines.append(f"\n{BOLD}Multi-Format Parsing{RESET}")
        old_fmts = set(old_mf.get("supported_formats", []))
        new_fmts = set(new_mf.get("supported_formats", []))
        if not old_fmts and new_fmts:
            all_lines.append(f"  {GREEN}NEW in v{new_ver}: supports {', '.join(sorted(new_fmts))}{RESET}")
        elif old_fmts != new_fmts:
            added = new_fmts - old_fmts
            removed = old_fmts - new_fmts
            if added:
                all_lines.append(f"  {GREEN}Added formats: {', '.join(sorted(added))}{RESET}")
            if removed:
                all_lines.append(f"  {RED}Removed formats: {', '.join(sorted(removed))}{RESET}")
        else:
            all_lines.append(f"  Supported formats: {', '.join(sorted(new_fmts))}")

        # Per-format results
        old_res = old_mf.get("results", {})
        new_res = new_mf.get("results", {})
        all_formats = sorted(set(list(old_res.keys()) + list(new_res.keys())))
        if all_formats:
            all_lines.append(f"  {'Format':<8s} {'Title':<35s} {'TOC':>4s} {'Chars':>7s} {'Tokens':>7s} {'Table':>6s}")
            all_lines.append(f"  {'─' * 8} {'─' * 35} {'─' * 4} {'─' * 7} {'─' * 7} {'─' * 6}")
            for fmt in all_formats:
                r = new_res.get(fmt, old_res.get(fmt, {}))
                is_new = fmt not in old_res and fmt in new_res
                tag = f" {GREEN}NEW{RESET}" if is_new else ""
                title = r.get("title_detected", "?")[:35]
                all_lines.append(
                    f"  {fmt:<8s} {title:<35s} {r.get('toc_entries', 0):>4d} "
                    f"{r.get('content_chars', 0):>7,d} {r.get('content_tokens', 0):>7,d} "
                    f"{'yes' if r.get('has_table') else 'no':>6s}{tag}"
                )

    # --- Semantic Chunking (v0.8.0+) ---
    old_sc = old.get("semantic_chunking", {})
    new_sc = new.get("semantic_chunking", {})
    if old_sc or new_sc:
        sc = new_sc or old_sc
        all_lines.append(f"\n{BOLD}Semantic Chunking{RESET}")
        if not old_sc and new_sc:
            all_lines.append(f"  {GREEN}NEW in v{new_ver}{RESET}")
        all_lines.append(f"  Input: {sc.get('input_chars', 0):,} chars, {sc.get('input_tokens', 0)} tokens, {sc.get('input_topics', '?')} topics")

        sem = sc.get("semantic", {})
        para = sc.get("paragraph", {})
        all_lines.append(f"  {'':35s} {'Semantic':>12s} {'Paragraph':>12s}")
        all_lines.append(f"  {'─' * 35} {'─' * 12} {'─' * 12}")
        for key, label in [
            ("l3_passages", "L3 passages"),
            ("total_tokens", "Total tokens"),
            ("token_min", "Token min"),
            ("token_max", "Token max"),
            ("token_mean", "Token mean"),
            ("time_s", "Time"),
        ]:
            sv = sem.get(key, "—")
            pv = para.get(key, "—")
            sfmt = f"{sv:.4f}s" if key == "time_s" and sv != "—" else (f"{sv:,}" if isinstance(sv, int) else str(sv))
            pfmt = f"{pv:.4f}s" if key == "time_s" and pv != "—" else (f"{pv:,}" if isinstance(pv, int) else str(pv))
            all_lines.append(f"  {label:<35s} {sfmt:>12s} {pfmt:>12s}")

    for line in all_lines:
        print(line)

    # --- Summary ---
    print(f"\n{BOLD}Summary{RESET}")
    # Count changed vs unchanged non-timing metrics
    sections = [
        (old.get("chunking", {}), new.get("chunking", {}),
         ["l1_chapters", "l2_sections", "l3_passages", "total_l3_tokens",
          "l3_token_min", "l3_token_max", "l3_token_median", "l3_token_mean"]),
        (old.get("content_coverage", {}), new.get("content_coverage", {}),
         ["coverage_ratio"]),
        (old.get("hierarchy_linkage", {}), new.get("hierarchy_linkage", {}),
         ["l3_orphan_count", "l2_orphan_count"]),
        (old.get("disk_footprint", {}), new.get("disk_footprint", {}),
         ["total_bytes", "file_count"]),
        (old.get("search_index_counts", {}), new.get("search_index_counts", {}),
         ["bm25_doc_count", "concept_index_term_count"]),
        (old.get("overlap_verification", {}), new.get("overlap_verification", {}),
         ["overlap_pairs_total", "overlap_pairs_with_shared_content"]),
    ]

    changed = 0
    total = 0
    for o, n, keys in sections:
        for k in keys:
            total += 1
            if o.get(k) != n.get(k):
                changed += 1

    if changed == 0:
        print(f"  {GREEN}All {total} functional metrics identical — zero behavioral drift.{RESET}")
    else:
        print(f"  {YELLOW}{changed}/{total} functional metrics changed.{RESET}")

    # Timing summary
    timing_keys = [
        ("chunking", "median_time_s"),
        ("token_counting", "median_per_call_ms"),
        ("storage_roundtrip", "save_median_s"),
        ("storage_roundtrip", "load_median_s"),
    ]
    regressions = []
    for section, key in timing_keys:
        ov = old.get(section, {}).get(key)
        nv = new.get(section, {}).get(key)
        if ov and nv:
            pct = pct_change(ov, nv)
            if pct is not None and pct > 10:
                regressions.append((f"{section}.{key}", pct))

    if regressions:
        print(f"  {RED}Timing regressions (>10%):{RESET}")
        for name, pct in regressions:
            print(f"    {name}: +{pct:.1f}%")
    else:
        print(f"  {GREEN}No timing regressions (all within 10% of previous).{RESET}")

    # New capabilities
    new_caps = []
    if not old.get("multiformat_parsing") and new.get("multiformat_parsing"):
        fmts = new["multiformat_parsing"].get("formats_tested", [])
        new_caps.append(f"Multi-format parsing ({', '.join(fmts)})")
    if not old.get("semantic_chunking") and new.get("semantic_chunking"):
        new_caps.append("Semantic chunking")
    if new_caps:
        print(f"  {GREEN}New capabilities: {'; '.join(new_caps)}{RESET}")

    print()


if __name__ == "__main__":
    main()
