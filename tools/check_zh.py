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
# 正文级规则（段落长、句长、构件长）只适用于散文文件。.md/.txt 之外多是配置或代码：
# 结构行会冒充段落，英文行会被套上中文阈值（2026-11-05 修订，见 README 口径节）。
PROSE_EXTS = {".md", ".markdown", ".txt"}

# ---------------------------------------------------------------- 词表

FUZZY = [  # 华为 2.15：避免程度、强调、模糊量词
    "显著", "极大地", "极大程度", "大幅度", "大幅提升", "明显提升", "非常", "大量",
    "一些", "少许", "部分", "基本地", "基本上", "完全地", "充分", "有效地",
    "完美", "无缝", "强大", "完善", "丰富", "领先", "卓越", "极致", "众多",
    "海量", "无限", "赋能", "抓手", "闭环", "生态化", "底层逻辑", "颗粒度",
    "心智", "深度地", "全面地", "更好地", "更高效地",
    # 华为 2.15 三份清单里原先漏掉的词（2026-11-10 补全）
    "较多", "较好", "决定性的", "最后的", "仅仅", "事实上", "值得注意的",
    "当然", "然而", "有些",
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
    ("fullwidth-digit", "error",
     r"[\uff10-\uff19]",
     "阿拉伯数字必须用半角形式（１０００ → 1000）", "ruanyf number.md 半角数字"),
    ("exclaim-pile", "error",
     r"[！]{2,}|[！!]![！!]",
     "不得连用感叹号（！！、!!!）；陈述语气用句号收尾", "ruanyf marks.md 感叹号(2)"),
    ("exclaim-soft", "hint",
     r"[！]",
     "技术说明用陈述语气，正文尽量不用感叹号", "华为 2.4 / ruanyf paragraph.md 原则"),
]

# 词法表之外的规则：并列逗号和标题结构靠整行扫描判定，不进 COMPILED，但要在 --rules 里可见。
LINE_RULES = [
    ("dunhao-comma", "error", "R-enum", "ruanyf marks.md 顿号(1)",
     "中文正文里用了半角逗号：并列词改顿号（腾讯, 阿里 → 腾讯、阿里），分句改全角逗号"),
    ("latin-enum-comma", "warn", "R-enum", "ruanyf marks.md 顿号(1)",
     "中文句子里的并列项用半角逗号分隔，应改顿号（Google, Facebook → Google、Facebook）"),
]

STRUCTURE_RULES = [
    ("long-sentence", "warn", "R-comma", "华为 2.5", "整句 >100 字（正文 3 行），拆简单句或改项目列表"),
    ("clause-long", "error", "R-comma", "DSG 文本·句子(1)",
     "逗号之间的构件 >40 字报 error、30～39 字报 warn（正文级，仅 .md/.txt 的中文行）"),
    ("clause-enum", "hint", "", "华为 2.6", "≥4 个并列项挤在一句，改项目列表"),
    ("paragraph-long", "warn", "", "华为 2.4 / DSG 段落·原则", "段落 >7 行或 >400 字"),
    ("heading-skip", "warn", "R-heading", "DSG 标题·原则(1) / 华为 2.3 样式",
     "标题跳级（如 h2 直接到 h4），补齐中间层级"),
    ("heading-orphan", "warn", "R-heading", "DSG 标题·原则(2) / 华为 2.3 样式",
     "上级标题下只有一个次级标题，并入上级或补出兄弟标题"),
]

# --rules 的「清单」列：对应 rules/AI怪中文-常见病句清单与修法.md 的 R-xx 编号。
# 空串 = 该条在清单里没有编号（需人判的条目，或本仓库补充项）。
RNO = {
    "halfwidth-punct": "R-punct", "straight-quote": "R-quote", "ellipsis-form": "R-ellipsis",
    "dash-single": "R-dash", "double-hyphen": "R-dash", "range-unit": "R-range",
    "range-dash": "R-range", "unit-symbol": "R-unit", "unit-prose": "R-unit",
    "multiply-sign": "", "times-decrease": "R-mult", "jinxing-nominal": "R-jinxing",
    "bei-passive": "R-bei", "tongguo-shi": "R-tongguo", "de-chain": "R-de",
    "boilerplate": "C·套话", "fuzzy-word": "B·模糊词", "misprint": "R-word",
    "login-word": "R-word", "colon-pile": "R-colon", "figure-colon": "R-figure",
    "click-word": "E·界面用语", "table-same-as-above": "", "cjk-latin-space": "R-space",
    "fullwidth-digit": "R-digit", "exclaim-pile": "R-exclaim", "exclaim-soft": "R-exclaim",
}

# 只在散文文件（.md/.markdown/.txt）里跑的规则：代码与配置里的感叹号多是数据或语法。
PROSE_ONLY = {"exclaim-soft", "latin-enum-comma"}

RNO_MAP = dict(RNO)
REFS = {}
LMSG = {}
for _rid, _lvl, _rno, _ref, _msg in LINE_RULES + STRUCTURE_RULES:
    RNO_MAP.setdefault(_rid, _rno)
    REFS[_rid] = _ref
    LMSG[_rid] = _msg

HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")

COMPILED = [(rid, lvl, re.compile(rx), msg, ref, RNO.get(rid, ""), rid in PROSE_ONLY)
            for rid, lvl, rx, msg, ref in RULES]
LEVELS = {"error": 3, "warn": 2, "hint": 1}
EXCLAIM_PILE = re.compile(r"[！]{2,}|[！!]![！!]")

# 检查器判不了的类别。跑完就打印：未覆盖的条款不产生任何信号，
# 「0 error」与「全量校验过」在输出上无法区分，绿色读数会被当成交付凭证。
RESIDUAL = """检查器判不了的 8 类，逐条自查（改法见 rules/AI怪中文-常见病句清单与修法.md）：
  1 段落一个中心句、放在段首；并列信息改项目列表，别用「同时」「而」串成长句
  2 列表项彼此不重叠、合起来穷尽；需要兜底就补「其他」并说明含义
  3 指代唯一：其、该、此、这 可能指两个对象时，改回名词
  4 定语与名词不堆叠：配置管理界面 → 用于配置管理的界面（华为 2.5 歧义三型）
  5 简单句优先；不用双重否定；「对于…来说」「在…的情况下」删冗余
  6 开头直接进入事实，结尾只给新信息；删「综上所述」「值得注意的是」「首先其次最后」
  7 术语与动词全文统一（单击／选择／输入）；缩略语首次出现就解释
  8 举例合规：私网 IP、0755-12345678、A 市、王先生，不用真实人名地名
两个自查测试：
  删修饰：删掉全部程度词与套话，信息量不变，那些词就是噪声。
  回译：能逐词译成英文、中文却读着别扭，是翻译腔，改句子结构而不是换词。"""

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

# ---------------------------------------------------------------- 并列逗号

_LEFT_TOK = re.compile(r"(?:[\u4e00-\u9fff]{1,12}|[A-Za-z]{1,12})\s*$")
_RIGHT_TOK = re.compile(r"[\u4e00-\u9fff]{1,12}|[A-Za-z]{1,12}")
_GAP_TOK = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9_]+")
_CJK1 = re.compile(r"[\u4e00-\u9fff]")
_STOP_PUNCT = "。；！？：…"


def _prev_nonspace(s, pos):
    while pos >= 0 and s[pos] == " ":
        pos -= 1
    return s[pos] if pos >= 0 else ""


def _next_nonspace(s, pos):
    while pos < len(s) and s[pos] == " ":
        pos += 1
    return s[pos] if pos < len(s) else ""


def enum_commas(masked: str):
    """找出被当成顿号用的半角逗号（ruanyf marks.md 顿号(1)）。

    先把整行的半角逗号逐个判定左右构件，再把「相邻逗号之间只有短构件、且没有句末标点」的
    逗号串成一条并列链。链上的逗号分两类报：
      cjk  —— 左右都是汉字：中文正文里的半角逗号，报 error。
      wide —— 至少一侧是拉丁词：要求链上 ≥3 个构件、本行含中文，并且链里出现过汉字构件
              或整条链被中文包夹。不满足就当英文整句里的普通逗号放过（DSG 顿号(2) 允许
              英文用半角逗号）。
    千分位（10,200）与缩写后的逗号（e.g., foo）不是并列构件。
    """
    recs = []  # None 表示这里断开并列链
    for i, ch in enumerate(masked):
        if ch != ",":
            continue
        pj, k = i - 1, i + 1
        while pj >= 0 and masked[pj] == " ":
            pj -= 1
        while k < len(masked) and masked[k] == " ":
            k += 1
        if pj < 0 or k >= len(masked) or masked[pj] == ".":
            recs.append(None)
            continue
        left, right = _LEFT_TOK.search(masked[:pj + 1]), _RIGHT_TOK.match(masked[k:])
        if not (left and right):
            recs.append(None)
            continue
        ltxt = left.group(0).rstrip()
        recs.append({"col": i, "l_cjk": bool(_CJK1.match(ltxt[-1])),
                     "r_cjk": bool(_CJK1.match(right.group(0)[0])),
                     "lstart": pj + 1 - len(ltxt), "rend": k + len(right.group(0))})

    chains, cur = [], []
    for r in recs:
        if r is None:
            chains.append(cur)
            cur = []
            continue
        if cur:
            gap = masked[cur[-1]["col"] + 1:r["col"]]
            if any(c in _STOP_PUNCT for c in gap) or len(_GAP_TOK.findall(gap)) > 3:
                chains.append(cur)
                cur = []
        cur.append(r)
    chains.append(cur)

    cjk, wide = [], []
    for chain in chains:
        if not chain:
            continue
        has_cjk_item = any(r["l_cjk"] or r["r_cjk"] for r in chain)
        bounded = bool(_CJK1.match(_prev_nonspace(masked, chain[0]["lstart"] - 1) or "\0")) or \
            bool(_CJK1.match(_next_nonspace(masked, chain[-1]["rend"]) or "\0"))
        for r in chain:
            if r["l_cjk"] and r["r_cjk"]:
                cjk.append(r["col"])
            elif len(chain) >= 2 and _CJK1.search(masked) and (has_cjk_item or bounded):
                wide.append(r["col"])
    return cjk, wide


# ---------------------------------------------------------------- 屏蔽区

MASK_RES = [
    re.compile(r"^```.*$|^~~~.*$"),                      # 由 fence 状态处理
    re.compile(r"`[^`\n]*`"),                            # 行内代码
    # 「…」内超过 25 字的内容按引文处理：规范文档要引用上游反例，那些长句不代表本文写法
    re.compile(r"「[^」\n]{25,}」"),
    re.compile(r"https?://\S+|www\.\S+"),
    re.compile(r"(?<![\w])[\w./\\-]*\.(?:md|py|pdf|txt|json|ya?ml|js|ts|bat|sh|csv|xlsx|docx)\b"),
    re.compile(r"\]\([^)\n]*\)"),                        # markdown 链接目标
    re.compile(r"^\s{0,3}[-*+]\s+\[[ xX]\]"),
]


TOKEN_RES = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_.\-/]+")

# 代码与配置文件里引号内的内容是数据，不是正文：规则表自己的正则和提示词会被本工具
# 的词表命中。注释仍然检查（2026-11-05 修订）。
CODE_MASK_RES = [
    re.compile(r"\"[^\"]*\"|'[^']*'"),
]


def width(s: str) -> int:
    """句长口径：汉字按字计，连续的拉丁字母/数字串按 1 计，标点不计。
    DSG 与华为的阈值（20 字／100 字）说的是中文正文；混排文本按字符数会虚高。"""
    return len(TOKEN_RES.findall(s))


def mask_line(line: str, extra=()) -> str:
    """把代码/URL/文件名等区域替换为等长空格，保持列号不变。"""
    out = list(line)
    for rx in MASK_RES[1:] + list(extra):
        for m in rx.finditer(line):
            for i in range(m.start(), m.end()):
                out[i] = " "
    return "".join(out)


# ---------------------------------------------------------------- 检查

def check_text(path: str, text: str, min_level: int):
    findings = []
    prose = Path(path).suffix.lower() in PROSE_EXTS
    md = Path(path).suffix.lower() in (".md", ".markdown")
    cjk_rx = re.compile(rf"[{CJK}]")

    def add(lvl, rid, lineno, col, msg, snippet, ref=""):
        if LEVELS[lvl] < min_level:
            return
        findings.append({"file": path, "line": lineno, "col": col, "level": lvl,
                         "rule": rid, "message": msg, "snippet": snippet.strip()[:80],
                         "ref": ref or REFS.get(rid, ""),
                         "rno": RNO_MAP.get(rid, "")})

    lines = text.splitlines()
    in_fence = False
    in_front = False
    sentences = []  # (lineno, col, 句子文本)
    headings = []   # (级别, 标题文字, 行号) —— 只有 .md 收集
    para_start, para_lines, para_chars = None, 0, 0
    def listish(line):
        """列表项、表格行、标题、引用块——不按段落计数。"""
        s = line.lstrip()
        if s[:1] in ("-", "*", "+", "|", "#", ">", "\t"):
            return True
        return bool(re.match(r"^\d+[.)]\s", s))

    def flush_para(at):
        nonlocal para_start, para_lines, para_chars
        if prose and para_start is not None and (para_lines > 7 or para_chars > 400):
            add("warn", "paragraph-long", para_start, 1,
                f"段落 {para_lines} 行 / {para_chars} 字：一个段落只讲一个中心句，建议 ≤4 行、不超过 7 行",
                lines[para_start - 1], "华为 2.4")
        para_start, para_lines, para_chars = None, 0, 0

    for i, raw in enumerate(lines, 1):
        if i == 1 and raw.strip() == "---":
            in_front = True                      # YAML front matter：里面的 # 不是标题
        if in_front:
            if i > 1 and raw.strip() in ("---", "..."):
                in_front = False
            continue
        if re.match(r"^\s*(```|~~~)", raw):
            in_fence = not in_fence
            flush_para(i)
            continue
        if in_fence:
            continue
        m = mask_line(raw, () if prose else CODE_MASK_RES)
        if md:
            hm = HEADING.match(raw)
            if hm:
                headings.append((len(hm.group(1)), hm.group(2).rstrip("#").strip(), i))
        if raw.strip():
            if listish(raw):            # 列表、表格、标题、引用块不按段落计数
                flush_para(i)
            else:
                if para_start is None:
                    para_start = i
                para_lines += 1
                para_chars += width(m)  # 与句长同一口径：拉丁词按 1 计（2026-11-05 修订）
        else:
            flush_para(i)

        # 半角逗号当顿号用（ruanyf marks.md 顿号(1)）：这些逗号位点由下面两条规则报，
        # halfwidth-punct 不再重复报同一个逗号。感叹号连用时只报连用，不重复报单个。
        enum_cjk, enum_wide = enum_commas(m)
        enum_idx = set(enum_cjk) | set(enum_wide)
        pile_idx = {p for h in EXCLAIM_PILE.finditer(m) for p in range(h.start(), h.end())}

        for rid, lvl, rx, msg, ref, rno, prose_only in COMPILED:
            if prose_only and not prose:
                continue
            for hit in rx.finditer(m):
                if rid == "range-dash" and skip_range(m, hit):
                    continue
                if rid == "halfwidth-punct" and hit.start() in enum_idx:
                    continue
                if rid == "exclaim-soft" and hit.start() in pile_idx:
                    continue
                note = f"{msg}：{hit.group(0)} → {MISTYPES[hit.group(0)]}" if (
                    rid == "misprint" and hit.group(0) in MISTYPES) else msg
                add(lvl, rid, i, hit.start() + 1, note, raw, ref)

        for col in enum_cjk:
            add("error", "dunhao-comma", i, col + 1, LMSG["dunhao-comma"], raw)
        for col in enum_wide:
            add("warn", "latin-enum-comma", i, col + 1, LMSG["latin-enum-comma"], raw)

        # 句子级规则。表格单元格按片段写（华为 2.8：单元格 ≤6 行、不写整句），
        # 所以表格行不套用正文的句长与构件长度规则。
        # 句子级规则只收中文行：英文行套中文句长阈值是类别错误（2026-11-05 修订）。
        if prose and not re.match(r"^\s*\|", raw) and cjk_rx.search(m):
            col = 0
            for sent in re.split(rf"(?<=[。！？；{chr(0xff1b)}])", m):
                if sent:
                    sentences.append((i, col, sent))
                col += len(sent)

    if prose and para_start is not None and (para_lines > 7 or para_chars > 400):
        add("warn", "paragraph-long", para_start, 1,
            f"段落 {para_lines} 行 / {para_chars} 字：建议 ≤4 行、不超过 7 行",
            lines[para_start - 1], "华为 2.4")

    for lineno, col, sent in sentences:
        n = width(sent)
        if n > 100:
            add("warn", "long-sentence", lineno, col + 1,
                f"句子 {n} 字（建议 ≤100 字 / 3 行），拆成简单句或改项目列表", sent, "华为 2.5")
        # 构件（逗号之间的一段）长度。DSG 文本·句子(1)：≤20 字可接受，20–29 尚可，
        # 30–39 要求语义明确无歧义，>40 任何情况都不接受。
        base = col
        for part in re.split(r"[，,]", sent):
            L = width(part)
            dun = part.count("、")
            if L >= 30 and dun >= 3:
                # 并列项堆在一句里：长度不是问题，问题是没有用项目列表（华为 2.6）
                add("hint", "clause-enum", lineno, base + 1,
                    f"{dun + 1} 个并列项挤在一句（{L} 字），改项目列表", part, "华为 2.6")
            elif L > 40:
                add("error", "clause-long", lineno, base + 1,
                    f"构件 {L} 字（>40 字任何情况都不接受），按语义拆句", part, "DSG 文本·句子(1)")
            elif L >= 30:
                add("warn", "clause-long", lineno, base + 1,
                    f"构件 {L} 字（30–39 字要求语义明确、不会误解），建议拆到 20 字内", part, "DSG 文本·句子(1)")
            base += len(part) + 1

    # 标题层级（DSG 标题·原则(1)(2)、华为 2.3 样式要求）：只有 .md 有可判的层级结构。
    if md and headings:
        prev = None
        for hlevel, htitle, lineno in headings:
            if prev and hlevel > prev[0] + 1:
                add("warn", "heading-skip", lineno, 1,
                    f"标题从 h{prev[0]} 直接跳到 h{hlevel}（「{prev[1]}」→「{htitle}」），补齐中间层级",
                    lines[lineno - 1])
            prev = (hlevel, htitle, lineno)
        children = {}
        for idx, (hlevel, _, _) in enumerate(headings):
            parent = next((j for j in range(idx - 1, -1, -1) if headings[j][0] < hlevel), None)
            children.setdefault(parent, []).append(idx)
        for parent, kids in children.items():
            if parent is None or len(kids) != 1:
                continue
            plevel, ptitle, _ = headings[parent]
            clevel, ctitle, clino = headings[kids[0]]
            add("warn", "heading-orphan", clino, 1,
                f"h{clevel}「{ctitle}」是 h{plevel}「{ptitle}」下唯一的子标题，并入上级或补出兄弟标题",
                lines[clino - 1])

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
    ap.add_argument("--no-residual", action="store_true",
                    help="不打印「检查器判不了的 8 类」清单（默认打印，防止 0 error 被当成全合规）")
    a = ap.parse_args(argv)

    if a.rules:
        print(f"{'规则':22} {'级别':7} {'清单':10} {'出处':36} 说明")
        for rid, lvl, _, msg, ref, rno, prose_only in COMPILED:
            tag = f"{lvl}*" if prose_only else lvl
            print(f"{rid:22} {tag:7} {rno:10} {ref:36} {msg}")
        for rid, lvl, rno, ref, msg in LINE_RULES + STRUCTURE_RULES:
            print(f"{rid:22} {lvl:7} {rno:10} {ref:36} {msg}")
        print("\n「清单」列对应 rules/AI怪中文-常见病句清单与修法.md 的 R-xx 编号；空白 = 本仓库补充项或无对应条目。")
        print("带 * 的规则只跑散文文件（.md/.markdown/.txt）。")
        print("口径：汉字按字计、连续拉丁词按 1 计、标点不计；表格行不套用句长规则（华为 2.8 单元格按片段写）；「…」内超过 25 字按引文屏蔽")
        print("口径（2026-11-05 修订）：正文级规则（paragraph-long、long-sentence、clause-long、clause-enum）只套在 .md/.markdown/.txt 的中文行上；配置与代码文件只跑词法级规则")
        print("口径（2026-11-10 新增）：标题层级规则只跑 .md，跳过 YAML front matter 与代码块；并列逗号按整行构件判定，千分位与 e.g., 不算并列")
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
            tag = f"；清单 {x0['rno']}" if x0.get("rno") else ""
            print(f"\n[{x0['level']:5}] {rid} × {len(items)}  — {x0['message']}  (出处：{x0['ref']}{tag})")
            for x in items[:12]:
                print(f"  {x['file']}:{x['line']}:{x['col']}  {x['snippet']}")
            if len(items) > 12:
                print(f"  …另 {len(items) - 12} 处")
        print(f"\n扫描 {scanned} 个文件：error {counts['error']}、warn {counts['warn']}、hint {counts['hint']}")
        if not a.no_residual:
            print("\n" + RESIDUAL)

    return 1 if (counts["error"] and not a.no_gate) else 0


if __name__ == "__main__":
    sys.exit(main())
