#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_zh.py — 中文写作规则检查器（纯标准库，零依赖）。

规则出处：
  - 华为 DKBA1313—2003.12《产品手册中文写作规范》（见 rules/华为产品手册中文写作规范-要点.md）
  - ruanyf/document-style-guide（docs/text.md、marks.md、number.md、paragraph.md、structure.md）
  - 本仓库 rules/AI中文怪中文-常见病句清单.md（AI 生成中文的高频病句）

用法：
  python tools/check_zh.py <文件或目录>...            # 检查，输出问题清单
  python tools/check_zh.py <路径> --rules              # 打印全部规则及出处
  python tools/check_zh.py <路径> --json               # 机器可读输出
  python tools/check_zh.py <路径> --level warn         # 只看 warn 及以上（error/warn/hint）
  python tools/check_zh.py <路径> --gate               # 有 error 时退出码 1（默认就是 1）
  python tools/check_zh.py <路径> --no-gate            # 无论结果退出码都是 0

退出码：发现 error 级问题 → 1；否则 0。warn/hint 不影响退出码。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from fnmatch import fnmatch
from pathlib import Path

CJK = "\u4e00-\u9fff\u3400-\u4dbf"
FW = "\u3000-\u303f\uff00-\uffef\u2018-\u201d\u2026"
CJKT = CJK + FW

# ---------------------------------------------------------------- 词表

FUZZY = [  # 华为 2.15：避免程度、强调、模糊量词
    "显著", "极大地", "极大程度", "大幅度", "大幅提升", "明显提升", "非常", "大量",
    "一些", "少许", "部分", "基本地", "基本上", "完全地", "充分", "有效地",
    "完美", "无缝", "强大", "完善", "丰富", "领先", "卓越", "极致", "众多",
    "海量", "无限", "赋能", "抓手", "闭环", "生态化", "底层逻辑", "颗粒度",
    "心智", "深度地", "全面地", "更好地", "更高效地",
]
BOILER = [  # AI 高频套话
    "综上所述", "总而言之", "总的来说", "综上", "值得注意的是", "需要指出的是",
    "需要强调的是", "不难发现", "由此可见", "众所周知", "毋庸置疑", "不言而喻",
    "让我们", "一言以蔽之", "在一定程度上", "从某种意义上", "在快速发展的",
    "在当今", "随着科技的进步", "随着人工智能的发展",
]
VAGUE_ACT = r"(?:进行|实现|提供|支持|作出|做出)(?:了|过)?(?:对)?"
BEI = r"被(?:认为|视为|称为|用于|设计|定义|实现|采用|要求|称为|设置|分配)"
MISTYPES = {  # 常见错别字/异形词（现代规范推荐写法）
    "其它": "其他", "帐户": "账户", "帐号": "账号", "做为": "作为",
    "既使": "即使", "布署": "部署", "按装": "安装",
}

# ---------------------------------------------------------------- 规则

def _alt(words):
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))

RULES = [
    # id, level, regex, message, 出处
    ("halfwidth-punct", "error",
     rf"(?<=[{CJK}])[,.;:?!]|[,.;:?!](?=[{CJK}])",
     "中文句子中使用了半角标点，应改为全角（，。；：？！）", "GB/T 15834 / ruanyf marks.md"),
    ("straight-quote", "warn",
     rf"(?<=[{CJK}])[\"']|[\"'](?=[{CJK}])",
     "中文引语建议使用全角引号（“”‘’）或「」，不要用英文直引号", "ruanyf marks.md"),
    ("ellipsis-form", "warn",
     r"\.{3,}|。{2,}|(?<!…)…(?!…)",
     "省略号应为“……”（两个 U+2026），不要用 ... 或 。。。", "GB/T 15834 / 华为 3.11"),
    ("dash-single", "warn",
     rf"(?<=[{CJK}])—(?!—)|(?<=[{CJK}])–(?!-)",
     "注释/说明用破折号“——”（占两字）；单个 —/– 是连接号，用途不同", "华为 3.8 / 3.10"),
    ("double-hyphen", "warn",
     r"[^-]-{2}(?!-)|(?<!-)--(?!-)",
     "出现了 ASCII 双连字符，中文里应写破折号“——”", "华为 3.10"),
    ("range-unit", "error",
     rf"(\d+(?:\.\d+)?)\s*[-~–—]\s*(\d+(?:\.\d+)?)\s*(kg|km|mm|cm|mL|ml|L|kV|V|A|W|Hz|MHz|GHz|%|℃|kΩ|MB|GB|ms|min|h)\b",
     "数值范围用“～”，且两个数字都要带单位（如 132kg～234kg，不是 132～234kg）", "华为 2.13.3"),
    ("range-dash", "warn",
     rf"(?<![\w.])\d+(?:\.\d+)?\s*[-~]\s*\d+(?:\.\d+)?(?=[{CJKT}]|\s|$)",
     "数量范围建议用“～”（1～3），不用 - 或 ~", "华为 2.13.3"),
    ("unit-symbol", "error",
     rf"(?<![A-Za-z])(KM|KMS|MM|KG|Kg|kilog|DB|Db|db|HZ|hz|cc|c\.c\.|sec|hr|yr|cum|sq|m/m|/sec|KΩ|rpm)(?![A-Za-z])|公分|公尺|千公尺|平米|立升|公升|秒米|周秒|赫芝|烛光|支光",
     "单位/词头写法错误，见华为规范表 7（KM→km、db→dB、HZ→Hz、rpm→r/min、公分→cm、平米→m²）", "华为 4.3"),
    ("unit-prose", "hint",
     r"\d+\s*(分贝|欧姆|赫兹|毫米|厘米|公斤|平方米)(?![\u4e00-\u9fff])",
     "物理量建议用单位符号而不是汉字（35 分贝 → 35dB、15 欧姆 → 15Ω）", "华为 4.2"),
    ("multiply-sign", "hint",
     r"\d\s+x\s+\d",
     "相乘建议用“×”而不是字母 x（480mm × 440mm）", "ruanyf number.md"),
    ("times-decrease", "error",
     r"(?:降低|减少|缩小|节省)(?:了|到)?\s*\d+(?:\.\d+)?\s*倍",
     "禁止“降低/减少 N 倍”，应改用百分数（降低了 20%）", "华为 2.13.4"),
    ("jinxing-nominal", "warn",
     VAGUE_ACT + rf"[{CJK}]{{0,4}}(检查|测试|分析|设置|配置|处理|优化|说明|讨论|验证|评估|统计|计算|控制|管理|查询|加载|安装|卸载)",
     "“进行＋动词”冗余，直接用动词（对系统进行检查 → 检查系统）", "ruanyf text.md / 华为 2.5"),
    ("bei-passive", "warn",
     BEI,
     "技术说明中少用“被”字句，改主动句（该功能被用于… → 该功能用于…）", "ruanyf text.md"),
    ("tongguo-shi", "warn",
     rf"通过[^。；\n]{{2,40}}?使[^。；\n]{{1,25}}?(?:能够|可以|得以|得到|更加|更为|实现)",
     "“通过…使…”句式常吞掉主语，检查句子有没有施事", "华为 2.5"),
    ("de-chain", "warn",
     rf"[{CJK}]的[{CJK}]{{1,6}}的[{CJK}]{{1,6}}的",
     "连续三层“的”定语，读起来是翻译腔，拆句或改并列", "ruanyf text.md"),
    ("boilerplate", "warn",
     _alt(BOILER),
     "AI 高频套话，删掉后信息量不变就删", "rules/AI怪中文-常见病句清单与修法.md"),
    ("fuzzy-word", "hint",
     _alt(FUZZY),
     "程度/模糊量词：给出数据或具体条件，否则删掉", "华为 2.15"),
    ("misprint", "error",
     _alt([k for k in MISTYPES if k]),
     "异形词/错别字（建议写法见提示）", "ruanyf text.md / 现代汉语规范"),
    ("login-word", "warn",
     r"登陆(?!舰|作战|岛|地点|区域|部队)",
     "进入系统/账号用「登录」；「登陆」指登上陆地（登陆舰、登陆作战）", "ruanyf text.md"),
    ("colon-pile", "warn",
     r"[:：][^。！？；\n]{0,12}[:：]",
     "同一句不要连续使用冒号（计费策略：表示计费：1 → 计费策略：1 表示计费）", "华为 3.5"),
    ("figure-colon", "warn",
     rf"(?:如?图|如?表|所示)\s*[:：]\s*$",
     "正文引出图/表且说明已完整时用句号，不用冒号", "华为 3.1"),
    ("click-word", "hint",
     r"点击",
     "华为规范用“单击”“双击”，不用“点击”；同一手册保持一致", "华为 5.7"),
    ("table-same-as-above", "warn",
     r"^\s*[|>\s]*同上",
     "表格中不要用“同上”，复制内容或合并单元格", "华为 2.7"),
    ("cjk-latin-space", "hint",
     rf"(?<=[{CJK}])[\dA-Za-z_]|[\dA-Za-z_%](?=[{CJK}])",
     "中文与英文/数字之间建议加半角空格（阿里云 文档 → 阿里云 文档 视情况）", "ruanyf text.md 字间距"),
]

COMPILED = [(rid, lvl, re.compile(rx), msg, ref) for rid, lvl, rx, msg, ref in RULES]
LEVELS = {"error": 3, "warn": 2, "hint": 1}

REF_CTX = re.compile(
    r"(?:表|图|式|章节|章|节|页|附录|版本|型号|步骤|款|序号|编号|标准|代号|"
    r"GB/T|GB|ISO|IEC|RFC|YD|DOI)\s*$")
DATEISH = re.compile(r"^\d{4}[-~.]\d{1,2}([-~.]\d{1,2})?$")


def skip_range(masked: str, hit) -> bool:
    """交叉引用编号（表 3-1）、标准号（GB 03100-1993）、日期不是数值范围。"""
    before, after = masked[:hit.start()], masked[hit.end():]
    if REF_CTX.search(before) or DATEISH.match(hit.group(0)):
        return True
    if after[:1] in ("年", "月", "日") or re.search(r"\d{4}[-~.]\d{1,2}[-~.]\d{1,2}", before[-12:] + hit.group(0) + after[:12]):
        return True
    # 只是长编号的一段：紧邻前后还是数字或分隔符
    return bool(re.search(r"[\d.\-~]$", before) or re.match(r"[\d.\-~]", after))

# ---------------------------------------------------------------- 屏蔽区

MASK_RES = [
    re.compile(r"^```.*$|^~~~.*$"),                      # 由 fence 状态处理
    re.compile(r"`[^`\n]*`"),                            # 行内代码
    re.compile(r"https?://\S+|www\.\S+"),
    re.compile(r"(?<![\w])[\w./\\-]*\.(?:md|py|pdf|txt|json|ya?ml|js|ts|bat|sh|csv|xlsx|docx)\b"),
    re.compile(r"\]\([^)\n]*\)"),                        # markdown 链接目标
    re.compile(r"^\s{0,3}[-*+]\s+\[[ xX]\]"),
]


def mask_line(line: str) -> str:
    """把代码/URL/文件名等区域替换为等长空格，保持列号不变。"""
    out = list(line)
    for rx in MASK_RES[1:]:
        for m in rx.finditer(line):
            for i in range(m.start(), m.end()):
                out[i] = " "
    return "".join(out)


# ---------------------------------------------------------------- 检查

def check_text(path: str, text: str, min_level: int):
    findings = []

    def add(lvl, rid, lineno, col, msg, snippet, ref):
        if LEVELS[lvl] < min_level:
            return
        findings.append({"file": path, "line": lineno, "col": col, "level": lvl,
                         "rule": rid, "message": msg, "snippet": snippet.strip()[:80], "ref": ref})

    lines = text.splitlines()
    in_fence = False
    sentences = []  # (lineno, col, 句子文本)
    para_start, para_lines, para_chars = None, 0, 0
    def listish(line):
        """列表项、表格行、标题、引用块——不按段落计数。"""
        s = line.lstrip()
        if s[:1] in ("-", "*", "+", "|", "#", ">", "\t"):
            return True
        return bool(re.match(r"^\d+[.)]\s", s))

    def flush_para(at):
        nonlocal para_start, para_lines, para_chars
        if para_start is not None and (para_lines > 7 or para_chars > 400):
            add("warn", "paragraph-long", para_start, 1,
                f"段落 {para_lines} 行 / {para_chars} 字：一个段落只讲一个中心句，建议 ≤4 行、不超过 7 行",
                lines[para_start - 1], "华为 2.4")
        para_start, para_lines, para_chars = None, 0, 0

    for i, raw in enumerate(lines, 1):
        if re.match(r"^\s*(```|~~~)", raw):
            in_fence = not in_fence
            flush_para(i)
            continue
        if in_fence:
            continue
        m = mask_line(raw)
        if raw.strip():
            if listish(raw):            # 列表、表格、标题、引用块不按段落计数
                flush_para(i)
            else:
                if para_start is None:
                    para_start = i
                para_lines += 1
                para_chars += len(raw.strip())
        else:
            flush_para(i)

        for rid, lvl, rx, msg, ref in COMPILED:
            for hit in rx.finditer(m):
                if rid == "range-dash" and skip_range(m, hit):
                    continue
                note = f"{msg}：{hit.group(0)} → {MISTYPES[hit.group(0)]}" if (
                    rid == "misprint" and hit.group(0) in MISTYPES) else msg
                add(lvl, rid, i, hit.start() + 1, note, raw, ref)

        # 句子级规则
        col = 0
        for sent in re.split(rf"(?<=[。！？；{chr(0xff1b)}])", m):
            if sent:
                sentences.append((i, col, sent))
            col += len(sent)

    if para_start is not None and (para_lines > 7 or para_chars > 400):
        add("warn", "paragraph-long", para_start, 1,
            f"段落 {para_lines} 行 / {para_chars} 字：建议 ≤4 行、不超过 7 行",
            lines[para_start - 1], "华为 2.4")

    for lineno, col, sent in sentences:
        n = len(re.sub(r"\s", "", sent))
        if n > 100:
            add("warn", "long-sentence", lineno, col + 1,
                f"句子 {n} 字（建议 ≤100 字 / 3 行），拆成简单句或改项目列表", sent, "华为 2.5")
        commas = sent.count("，")
        if commas >= 5:
            add("warn", "comma-chain", lineno, col + 1,
                f"一句里 {commas} 个逗号（一逗到底），按语义断句", sent, "华为 3.2")

    return findings


def iter_files(targets, exts, excludes):
    for t in targets:
        p = Path(t)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in exts and not is_excluded(f, excludes):
                    yield f
        elif p.is_file():
            if not is_excluded(p, excludes):
                yield p
        else:
            print(f"跳过（不存在）: {t}", file=sys.stderr)


DEFAULT_EXCLUDES = ["extracted/*", "document-style-guide/*", ".git/*"]


def is_excluded(p: Path, pats) -> bool:
    s = p.as_posix()
    for pat in pats:
        head = pat.rstrip("*").rstrip("/")
        if fnmatch(s, pat) or fnmatch(s, "*/" + pat) or (head and (s.startswith(head) or f"/{head}/" in s)):
            return True
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="中文写作规则检查器（零依赖）")
    ap.add_argument("targets", nargs="*", default=["."])
    ap.add_argument("--rules", action="store_true", help="打印规则清单与出处")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--level", choices=["error", "warn", "hint"], default="hint",
                    help="最低报告级别（默认 hint 全报）")
    ap.add_argument("--ext", default=".md,.txt", help="扫描的扩展名（默认 .md,.txt）")
    ap.add_argument("--exclude", action="append", metavar="GLOB",
                    help="排除路径（可多次）。默认已排除 extracted/ 与 document-style-guide/（上游原文）")
    ap.add_argument("--no-gate", action="store_true", help="有 error 也返回 0")
    a = ap.parse_args(argv)

    if a.rules:
        print(f"{'规则':22} {'级别':6} {'出处':34} 说明")
        for rid, lvl, _, msg, ref in COMPILED:
            print(f"{rid:22} {lvl:6} {ref:34} {msg}")
        print(f"\n句子级：long-sentence / comma-chain；段落级：paragraph-long（华为 2.4/2.5）")
        return 0

    exts = {e.strip() if e.startswith(".") else "." + e.strip() for e in a.ext.split(",")}
    min_level = LEVELS[a.level]
    all_findings = []
    scanned = 0
    excludes = DEFAULT_EXCLUDES + (a.exclude or [])
    for f in iter_files(a.targets or ["."], exts, excludes):
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = f.read_text(encoding="utf-8", errors="ignore")
        scanned += 1
        all_findings += check_text(str(f), text, min_level)

    counts = {"error": 0, "warn": 0, "hint": 0}
    for x in all_findings:
        counts[x["level"]] += 1

    if a.json:
        print(json.dumps({"files": scanned, "counts": counts, "findings": all_findings},
                         ensure_ascii=False, indent=2))
    else:
        by_rule = {}
        for x in all_findings:
            by_rule.setdefault(x["rule"], []).append(x)
        order = {"error": 0, "warn": 1, "hint": 2}
        for rid, items in sorted(by_rule.items(), key=lambda kv: (order[kv[1][0]["level"]], -len(kv[1]))):
            x0 = items[0]
            print(f"\n[{x0['level']:5}] {rid} × {len(items)}  — {x0['message']}  (出处：{x0['ref']})")
            for x in items[:12]:
                print(f"  {x['file']}:{x['line']}:{x['col']}  {x['snippet']}")
            if len(items) > 12:
                print(f"  …另 {len(items) - 12} 处")
        print(f"\n扫描 {scanned} 个文件：error {counts['error']}、warn {counts['warn']}、hint {counts['hint']}")

    return 1 if (counts["error"] and not a.no_gate) else 0


if __name__ == "__main__":
    sys.exit(main())
