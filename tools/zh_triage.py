"""中文写作读数的聚合层：把逐条发现压成可直接读的 top 表。

为什么要有它：全量语料上 check_zh.py 每文件产出近 48 条读数，
逐条看不可行，读数会变成没人处理的背景噪声。

用法：
    python tools/zh_triage.py .                  # 当前目录，按规则聚合
    python tools/zh_triage.py docs/ --top 10     # 只看前 10 条
    python tools/zh_triage.py . --level error    # 只看阻断级
    python tools/zh_triage.py . --files          # 附上读数最响的 5 个文件

退出码：有 error 时返回 1，可直接当 CI 闸门。
纯标准库，与 check_zh.py 同源同口径。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_zh  # noqa: E402

ORDER = {"error": 0, "warn": 1, "hint": 2}


def collect(targets, level):
    min_level = check_zh.LEVELS[level]
    exts = {".md", ".markdown", ".txt"}
    excludes = check_zh.DEFAULT_EXCLUDES
    findings = []
    files = set()
    for f in check_zh.iter_files(targets, exts, excludes, 1048576):
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = f.read_text(encoding="utf-8", errors="ignore")
        files.add(str(f))
        findings += check_zh.check_text(str(f), text, min_level)
    return findings, files


def main(argv=None):
    ap = argparse.ArgumentParser(description="中文写作读数的聚合层（top 表）")
    ap.add_argument("targets", nargs="*", default=["."])
    ap.add_argument("--top", type=int, default=20, help="最多列多少条规则（默认 20）")
    ap.add_argument("--level", choices=["error", "warn", "hint"], default="error",
                    help="汇总哪个级别起（默认 error）")
    ap.add_argument("--files", action="store_true", help="附上读数最响的 5 个文件")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    findings, files = collect(a.targets or ["."], a.level)

    buckets = {}
    for x in findings:
        b = buckets.setdefault(x["rule"], {"level": x["level"], "count": 0,
                                           "files": set(), "ref": x.get("ref", ""),
                                           "message": x["message"]})
        b["count"] += 1
        b["files"].add(x["file"])

    rows = sorted(buckets.items(),
                  key=lambda kv: (ORDER[kv[1]["level"]], -kv[1]["count"]))[:a.top]

    if a.json:
        print(json.dumps({"scanned": len(files),
                          "rows": [{"rule": r, "level": b["level"], "count": b["count"],
                                    "files": len(b["files"]), "ref": b["ref"]}
                                   for r, b in rows]}, ensure_ascii=False, indent=2))
        return 1 if any(b["level"] == "error" for _, b in rows) else 0

    total = {"error": 0, "warn": 0, "hint": 0}
    for x in findings:
        total[x["level"]] = total.get(x["level"], 0) + 1

    print(f"扫描 {len(files)} 个文件（{a.level} 级起）｜error {total['error']}、warn {total['warn']}、"
          f"hint {total['hint']}｜列前 {len(rows)} 条规则")
    print(f"{'级别':6} {'条数':>6} {'文件':>5}  {'规则':22} 出处")
    for rid, b in rows:
        print(f"{b['level']:6} {b['count']:6d} {len(b['files']):5d}  {rid:22} {b['ref']}")
    if len(buckets) > a.top:
        print(f"…另有 {len(buckets) - a.top} 条规则未列（--top 调整）")

    if a.files:
        per_file = {}
        for x in findings:
            per_file[x["file"]] = per_file.get(x["file"], 0) + 1
        print("\n读数最响的文件：")
        for path, n in sorted(per_file.items(), key=lambda kv: -kv[1])[:5]:
            print(f"  {n:5d}  {path}")

    return 1 if total["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
