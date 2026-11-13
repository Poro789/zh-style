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
BEI_RE = re.compile(BEI)
MISTYPES = {  # 常见错别字/异形词（现代规范推荐写法）
    "其它": "其他", "帐户": "账户", "帐号": "账号", "做为": "作为",
    "既使": "即使", "布署": "部署", "按装": "安装",
}

# ---------------------------------------------------------------- 规则

def _alt(words):
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))

# 套话词表：单次命中只是线索（hint），同段落 ≥3 次由 boilerplate-pile 报 error。
# 口径照 qu-ai-wei 的规则结构：单次不算问题，反复出现才算（编辑实践级，非统计实证）。
BOILER_RE = re.compile(_alt(BOILER))

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
     "技术说明中少用“被”字句，改主动句（该功能被用于… → 该功能用于…）", "DSG 写作风格(1) / 华为 2.4 / 分级表 3"),
    # 白名单只覆盖 12 个高频动词，「被强调」「被整编」这类一律放过（2026-11-13 记录 A4：
    # mechanisms.md 里 24 行「被＋汉字」命中 0）。规范口径是「主动语态优先」（分级表第 3 条），
    # 属优先而非禁止，所以兜底命中降为 hint，不污染 warn 计数。与 bei-passive 同位置不重复报。
    ("bei-passive-open", "hint",
     rf"被[{CJK}]{{1,4}}",
     "「被＋动词」白名单外的形式：多数应改主动句；施事确实无关时可保留",
     "DSG 写作风格(1) / 华为 2.4 / 分级表 3"),
    ("tongguo-shi", "warn",
     rf"通过[^。；\n]{{2,40}}?使[^。；\n]{{1,25}}?(?:能够|可以|得以|得到|更加|更为|实现)",
     "“通过…使…”句式常吞掉主语，检查句子有没有施事", "华为 2.5"),
    ("de-chain", "warn",
     rf"[{CJK}]的[{CJK}]{{1,6}}的[{CJK}]{{1,6}}的",
     "连续三层“的”定语，读起来是翻译腔，拆句或改并列", "ruanyf text.md"),
    ("boilerplate", "hint",
     _alt(BOILER),
     "AI 高频套话：单次出现只是线索，同段落 ≥3 次由 boilerplate-pile 报 error",
     "qu-ai-wei pattern-catalog 预判标签族（编辑实践）+ 本仓库清单 C·套话"),
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
    # ——2026-11-13 检查记录入库的新规则（B3、B5、B6；B1 在 check_text 尾部按整文件判定）——
    ("heading-sentence", "hint",
      rf"^#{{1,6}}\s+.*[。！？{chr(0xff1f)}]",
      "标题应为名词性短语，不带句末标点；整句放正文", "华为 2.3（标题不带标点）延伸"),
    ("dialog-residue", "hint",
      r"^\s*(?:#{1,6}\s+)?(?:以下是|下面是|下面将)",
      "对话残留开头：「以下是……」是对话接缝，不该进档案正文，删掉或改直接陈述", "rules/AI怪中文-常见病句清单与修法.md（本仓库补充）"),
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
    ("boilerplate-pile", "error", "C·套话",
     "qu-ai-wei pattern-catalog 预判标签族（编辑实践）+ 本仓库清单 C·套话",
     "同一段落内套话 ≥3 次：套话在承重，改结构而不是逐词删"),
]

# 文件级规则：每文件至多一条，在 check_text 尾部专门判定，不进逐字符正则循环。
FILE_RULES = [
    ("truncated-file", "hint", "", "本库判断（截断文件读都会发现，规则只是显式化）",
     "文件结尾无句末标点，疑似截断"),
    ("date-format-mixed", "warn", "", "本库归档口径 + AGENTS.md「同一篇只用一种」类比迁移",
     "同一文档 ≥2 种日期写法（2026-02-15 / 2026/2/15 / 20260222 / 2026年2月15日），统一为 YYYY-MM-DD"),
    ("percent-form-mixed", "hint", "", "ruanyf text.md（半角的百分号，视同阿拉伯数字）",
     "同一文档混用全角％与半角%，统一为半角%"),
    # 默认关（2026-11-13 research 库检查记录 B1）。出处查到了，是华为 2.11，不是记录里猜的 2.1：
    # 「正文中第一次出现的缩略语，必须进行解释」，6.1 重申；格式 VPN（Virtual Private Network）。
    # 实测误报比撑不起默认闸门：kit 侧 11 条候选 2 条真命中，research 侧 122 条几乎全是该库自造的
    # 命题代号（CP、UJB、VRP）与厂商名（SVS、UMIK），白名单补不完。华为 2.11 的前提是产品手册配
    # 缩略语表，台账与工程文档不满足。所以规则照加、默认关，写交付手册时 --enable 打开。
    ("acronym-unexplained", "hint", "E·术语", "华为 2.11（6.1 重申）",
     "ASCII 缩略语首次出现未就地解释：写 `VPN（Virtual Private Network）` 或 `OCR（光学字符识别）`"),
]

# --rules 的「清单」列：对应 rules/AI怪中文-常见病句清单与修法.md 的 R-xx 编号。
# 空串 = 该条在清单里没有编号（需人判的条目，或本仓库补充项）。
RNO = {
    "halfwidth-punct": "R-punct", "straight-quote": "R-quote", "ellipsis-form": "R-ellipsis",
    "dash-single": "R-dash", "double-hyphen": "R-dash", "range-unit": "R-range",
    "range-dash": "R-range", "unit-symbol": "R-unit", "unit-prose": "R-unit",
    "multiply-sign": "", "times-decrease": "R-mult", "jinxing-nominal": "R-jinxing",
    "bei-passive": "R-bei", "bei-passive-open": "R-bei", "tongguo-shi": "R-tongguo", "de-chain": "R-de",
    "boilerplate": "C·套话", "fuzzy-word": "B·模糊词", "misprint": "R-word",
    "login-word": "R-word", "colon-pile": "R-colon", "figure-colon": "R-figure",
    "click-word": "E·界面用语", "table-same-as-above": "", "cjk-latin-space": "R-space",
    "fullwidth-digit": "R-digit", "exclaim-pile": "R-exclaim", "exclaim-soft": "R-exclaim",
    "heading-sentence": "", "dialog-residue": "",
}

# 只在散文文件（.md/.markdown/.txt）里跑的规则：代码与配置里的感叹号多是数据或语法。
PROSE_ONLY = {"exclaim-soft", "latin-enum-comma"}

RNO_MAP = dict(RNO)
REFS = {}
LMSG = {}
for _rid, _lvl, _rno, _ref, _msg in LINE_RULES + STRUCTURE_RULES + FILE_RULES:
    RNO_MAP.setdefault(_rid, _rno)
    REFS[_rid] = _ref
    LMSG[_rid] = _msg

HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
# JS 模板行：含 ${ 插值或以 HTML 标签起行的，是代码不是正文，整行跳过词法规则
# （2026-11-13 检查记录 A5；提取器已在提取侧过滤，但正文直传不走提取器，这里独立兜底）。
JS_TEMPLATE = re.compile(r"\$\{|^\s*</?[A-Za-z]")
# 时间点（08:30、09:11:47）里的冒号是时间格式，不是标点连排（2026-11-13 检查记录 A3）。
TIMEISH = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")


def mask_time_colons(m: str) -> str:
    """把 08:30、09:11:47 这类时间串内部的冒号换成空格，使 colon-pile 不再把时间点当连排冒号。"""
    out = list(m)
    for mm in TIMEISH.finditer(m):
        for j in range(mm.start(), mm.end()):
            if out[j] == ":":
                out[j] = " "
    return "".join(out)

# rx 为空串的规则走 check_text 里的专门判定（文件级），不进逐字符正则循环。
COMPILED = [(rid, lvl, re.compile(rx), msg, ref, RNO.get(rid, ""), rid in PROSE_ONLY)
            for rid, lvl, rx, msg, ref in RULES if rx]
LEVELS = {"error": 3, "warn": 2, "hint": 1}
# 默认关闭的规则：中英文之间的空格交给 zhlint 这类排版工具前置处理，
# 本检查器不接管（2026-11-13 决定，全量 1,683 条 hint 全是这一条）。
DEFAULT_OFF = {"cjk-latin-space", "acronym-unexplained"}
_ENABLED_OFF = set()
EXCLAIM_PILE = re.compile(r"[！]{2,}|[！!]![！!]")
# 提交哈希、十六进制串：unit-symbol 里的 cc/db 等字样不是单位（2026-11-13 审计 A1）。
HEX_RUN = re.compile(r"(?<![0-9A-Za-z])[0-9a-f]{7,}(?![0-9A-Za-z])")

# 检查器判不了的类别。跑完就打印：未覆盖的条款不产生任何信号，
# 「0 error」与「全量校验过」在输出上无法区分，绿色读数会被当成交付凭证。
RESIDUAL = """检查器判不了的 8 类，逐条自查（改法见 rules/AI怪中文-常见病句清单与修法.md）：
  1 段落一个中心句、放在段首；并列信息改项目列表，别用「同时」「而」串成长句
  2 列表项彼此不重叠、合起来穷尽；需要兜底就补「其他」并说明含义
  3 指代唯一：其、该、此、这 可能指两个对象时，改回名词
  4 定语与名词不堆叠：配置管理界面 → 用于配置管理的界面（华为 2.5 歧义三型）
  5 简单句优先；不用双重否定；「对于……来说」「在……的情况下」删冗余
  6 开头直接进入事实，结尾只给新信息；删「综上所述」「值得注意的是」「首先其次最后」
  7 术语与动词全文统一（单击／选择／输入）；缩略语首次出现就解释
    （ASCII 大写串可用 --enable acronym-unexplained 代查；「O 层」这类单字母代号与中文自造代号仍靠人判）
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
    # 引号内超过 25 字的内容按引文处理：规范文档要引用上游反例，那些长句不代表本文写法
    re.compile(r"「[^」\n]{25,}」"),
    re.compile(r"https?://\S+|www\.\S+"),
    re.compile(r"(?<![\w])[\w./\\-]*\.(?:md|py|pdf|txt|json|ya?ml|js|ts|bat|sh|csv|xlsx|docx)\b"),
    re.compile(r"\]\([^)\n]*\)"),                        # markdown 链接目标
    re.compile(r"^\s{0,3}[-*+]\s+\[[ xX]\]"),
    # HTML 注释是转录件的结构标记（分页注释、豁免标记），内容不进任何规则（2026-11-13 检查记录 A1）
    re.compile(r"<!--.*?-->"),
]


# 引号内的内容是被谈论的对象，不是本文的写法。规范文本要引用它禁止的形式
# （AGENTS.md 写「英语式被动（「被认为是」）」），报告正文会引用受访者原话。
# 词法级规则不看这些区间（2026-11-13 检查记录 A1）。
# straight-quote 不在豁免集内：它的命中位置在引号边界上，不在区间里。
LEX_QUOTE = re.compile(r"「[^」\n]*」|『[^』\n]*』|[“”\"][^”\"\n]*[””\"]|'[^'\n]*'")
LEX_EXEMPT = {"bei-passive", "bei-passive-open", "boilerplate", "boilerplate-pile",
              "jinxing-nominal", "tongguo-shi", "de-chain", "colon-pile", "figure-colon",
              "fuzzy-word", "misprint", "login-word", "click-word"}

# 禁用词清单、规则表这类并列清单：行里的套话是被列举项，不是行文
# （AGENTS.md:177 一行里并列 8 个禁用词，boilerplate 计 5 次；2026-11-13 检查记录 A3）。
# 判据落在命中词本身，不落在整行形态：清单常以句号收尾，用「整行无句末标点」会漏掉。
LIST_EXEMPT = {"boilerplate", "bei-passive", "bei-passive-open", "jinxing-nominal", "fuzzy-word"}
ENUM_BEFORE = "、：:（("


def in_enum(m: str, pos: int, end: int) -> bool:
    """命中词是否处在顿号并列序列里：紧邻前一个是顿号／冒号／括号，或紧邻后一个是顿号。
    句子里独立出现的套话（「……较好。综上所述，」）不满足，照常报。"""
    i = pos - 1
    while i >= 0 and m[i] == " ":
        i -= 1
    prev = m[i] if i >= 0 else ""
    nxt = m[end] if end < len(m) else ""
    # 行首没有前一个字符，prev 是空串；`"" in ENUM_BEFORE` 恒真，会把段首与列表项开头的
    # 套话全部误判成清单项免检（套话最典型的位置正是段首）。空 prev 不算清单。
    if not prev:
        return False
    return prev in ENUM_BEFORE or nxt == "、"


TOKEN_RES = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_.\-/]+")
# 天然断点：PDF 文本层提取常把一段切成固定宽度的硬换行行，丢掉段落分隔。
# 记录口径：单行 ≤6 字（宽度）且不含逗号，视为标题行/节名行这类硬断点（2026-11-13 检查记录 A6）。
# HEXACO_测试结果.md 的「一、关于 HEXACO 模型」等节名行即靠此断开 23 行假长段。
SOFT_BREAK_MAX = 6


def soft_break(line: str) -> bool:
    if not line.strip():
        return False
    if width(line) > SOFT_BREAK_MAX:
        return False
    return not re.search(r"[，,]", line)

# 代码与配置文件里引号内的内容是数据，不是正文：规则表自己的正则和提示词会被本工具
# 的词表命中。注释仍然检查（2026-11-05 修订）。
CODE_MASK_RES = [
    re.compile(r"\"[^\"]*\"|'[^']*'"),
]

# .py 专用（2026-11-10 修订）：docstring/注释里半角括号（含花括号）的段是代码写法
# （(a, b)、[(k, v)]、{码位: 字符}），其中的半角逗号冒号不是中文标点，屏蔽到闭合括号为止。
PY_PAREN = re.compile(r"[\[({][^)\]}\n]*[)\]}]")
# --word 形式是 CLI 标志（--dry）或 CSS 自定义属性（var(--rule)），不算拿双连字符冒充破折号。
# 汉字直接跟在后面的仍然报。
DASHFLAG = re.compile(r"(?<![-\w一-鿿])-{2,3}[A-Za-z]")
# 术语连接号：PVQ-RR 这类官方二分支概念名（「自主—思想」）用 — 连接两个并列词，
# 是华为 3.8 连接号的正当用途。同一「汉字1～4字—汉字1～4字」形态全文出现 ≥3 次 → 术语名，
# dash-single 不报（2026-11-13 检查记录 A2）。
TERM_DASH = re.compile(rf"(?<![{CJK}])[{CJK}]{{1,4}}—[{CJK}]{{1,4}}(?!{CJK})")

# 日期形态（B3）：只认数字类写法，「2025 年 12 月」这类带空格的中文写法归人工。
# 词边界防止匹配进更长的数字串；8 位形态另加月/日合法性校验，降低版本号误判。
DATE_FORMS = [
    re.compile(r"(?<!\d)\d{4}-\d{1,2}-\d{1,2}(?!\d)"),
    re.compile(r"(?<!\d)\d{4}/\d{1,2}/\d{1,2}(?!\d)"),
    re.compile(r"(?<!\d)\d{4}\.\d{1,2}\.\d{1,2}(?!\d)"),
    re.compile(r"(?<![A-Za-z0-9])\d{4}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])(?![A-Za-z0-9])"),
    re.compile(r"(?<!\d)\d{4}年\d{1,2}月\d{1,2}日"),
]


def py_prose_lines(text: str):
    """把 .py 的 docstring 与注释抽成行号对齐的行列表，其余行置空。

    词法级规则只跑在这些文本上：dict 冒号、CSS 变量、元组逗号、argv 切片是代码语法，
    不是中文写法问题（2026-11-10 修订；research 库 13 个脚本实测误报率约 95%）。
    docstring 判定 = 逻辑行起点的 STRING token。tokenize 失败返回 None，退回整文件扫描。
    """
    import io
    import tokenize
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except Exception:
        return None
    lines = text.splitlines()
    buf = [[] for _ in lines]

    def put(lineno, col, s):
        if not 1 <= lineno <= len(buf):
            return
        row = buf[lineno - 1]
        if col > len(row):
            row.extend(" " * (col - len(row)))
        end = col + len(s)
        if end > len(row):
            row.extend(" " * (end - len(row)))
        row[col:end] = list(s)

    prev_sig = None  # 最近一个非注释、非行边界的 token；None = 模块开头
    for t in toks:
        if t.type == tokenize.COMMENT:
            put(t.start[0], t.start[1], t.string)
            continue
        if t.type == tokenize.NEWLINE:
            prev_sig = t
            continue
        if t.type in (tokenize.NL, tokenize.INDENT,
                      tokenize.DEDENT, tokenize.ENCODING):
            continue
        if t.type == tokenize.STRING and (prev_sig is None or prev_sig.type == tokenize.NEWLINE):
            s = t.string
            mm = re.match(r"^[A-Za-z]*(\"\"\"|'''|\"|')", s)
            if mm:
                body = s[len(mm.group(0)):]
                for q in ('"""', "'''", '"', "'"):
                    if body.endswith(q):
                        body = body[:-len(q)]
                        break
                first_col = t.start[1] + len(mm.group(0))
                for k, seg in enumerate(body.split("\n")):
                    put(t.start[0] + k, first_col if k == 0 else 0, seg)
        prev_sig = t
    return ["".join(row).rstrip() for row in buf]


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


# 缩略语（华为 2.11，默认关）：只认纯大写串，允许 / 与 - 并列（EXT/LEN/CS、PVQ-RR）。
# 大小写混排的专名（PowerShell、ToUnicode）不是缩略语，不进候选。
ACR_RX = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2,6}(?:[/-][A-Z]{1,6})*)(?![A-Za-z0-9])")
# 就地兑换：紧跟的括号里有中文说明或拉丁全称。OCR（光学字符识别）与 VPN（Virtual Private Network）都算，
# 华为 2.11 只规定「必须解释」，中文说明同样合规。
ACR_EXPLAIN = re.compile(rf"^\s*（(?:[^（）]*[{CJK}][^（）]*|[^（）]*[A-Za-z]{{2,}}[^（）]*)）")
# 不要求解释的一类：计量单位、编码与格式、标准与机构号、计算机通用名。
# 判据是「不解释也不会读错，读者按名字查得到」，不是「我觉得常见」。
# 学术会议名（EMNLP）、厂商与产品名（SVS、UMIK）不收：2.11 要求解释，照报。
ACR_STOP = {
    # 单位与量
    "KB", "MB", "GB", "TB", "PB", "MS", "HZ", "KHZ", "MHZ", "GHZ", "DB", "KM", "KG",
    "MM", "CM", "ML", "KV", "VA", "WH", "RH", "RPM", "SPL", "FM", "AM",
    # 编码、格式、协议
    "UTF", "ASCII", "GBK", "GB2312", "BIG5", "HTML", "HTTP", "HTTPS", "URL", "URI",
    "JSON", "CSV", "TSV", "XML", "YAML", "TOML", "PDF", "PNG", "JPG", "JPEG", "GIF",
    "SVG", "XLSX", "XLS", "DOCX", "PPTX", "SRT", "API", "CLI", "GUI", "UI", "CSS",
    "JS", "TS", "SQL", "IP", "DNS", "TLS", "SSL", "SSH", "FTP", "TCP", "UDP", "LAN",
    "WIFI", "USB", "HDMI", "HDR", "RGB", "CMYK", "FAQ", "README", "INDEX", "AGENTS",
    "TODO", "CHANGELOG", "LICENSE", "CACHE", "PATH", "NAME", "CODE", "DATA", "INFO",
    "LOG", "TMP", "SRC", "LIB", "BIN", "DEV", "PROD", "TEST", "DRAFT", "WIP", "OK",
    "ID", "NO", "TV", "AD", "BC", "VS", "ETC",
    # 标准与机构号
    "GB", "ISO", "IEC", "RFC", "ITU", "ANSI", "DIN", "ASTM", "DOI", "ISBN", "ISSN",
    "USC", "EU", "UN", "NGO", "GDP", "CPI",
    # 计算机通用名
    "CI", "CD", "OCR", "SDK", "IDE", "OS", "PC", "CPU", "GPU", "RAM", "ROM", "SSD",
    "HDD", "HPC", "VM", "CMD", "EXE", "DLL", "PID", "UUID", "MD5", "SHA",
    "AI", "ML", "LLM", "NLP", "TTS", "STT", "ASR",
    # 日期占位符
    "YYYY", "MM", "DD", "HH",
}

# ---------------------------------------------------------------- 检查

def check_text(path: str, text: str, min_level: int):
    findings = []
    prose = Path(path).suffix.lower() in PROSE_EXTS
    md = Path(path).suffix.lower() in (".md", ".markdown")
    py = Path(path).suffix.lower() == ".py"
    if py:
        extracted = py_prose_lines(text)
        if extracted is not None:
            text = "\n".join(extracted)
    cjk_rx = re.compile(rf"[{CJK}]")

    def add(lvl, rid, lineno, col, msg, snippet, ref=""):
        if rid in DEFAULT_OFF and rid not in _ENABLED_OFF:
            return
        if LEVELS[lvl] < min_level:
            return
        findings.append({"file": path, "line": lineno, "col": col, "level": lvl,
                         "rule": rid, "message": msg, "snippet": snippet.strip()[:80],
                         "ref": ref or REFS.get(rid, ""),
                         "rno": RNO_MAP.get(rid, "")})

    lines = text.splitlines()
    # 术语连接号预扫描：文档里 `汉字1～4字—汉字1～4字` 这个形状出现 ≥3 次，判为术语命名表
    # （PVQ-RR 每个价值名在结果表与对照表各印一次，共 2 次，但整表 11 个同形词，形状累计 ≫3）。
    # 命中该形状的位置，dash-single 不报（2026-11-13 检查记录 A2）。
    term_positions = []
    for ln in lines:
        for mm in TERM_DASH.finditer(ln):
            term_positions.append(mm.group(0))
    term_shape = len(term_positions) >= 3
    in_fence = False
    in_front = False
    sentences = []  # (lineno, col, 句子文本)
    headings = []   # (级别, 标题文字, 行号) —— 只有 .md 收集
    para_start, para_lines, para_chars = None, 0, 0
    pile = []  # 当前段落内套话命中：(行号, 列, 词)；段落 flush 时判定并在 ≥3 时报 error
    acr_first = {}  # 缩略语首现：token → (行, 列, 原文)；首现就兑换的记 None，后续裸用免报

    def listish(line):
        """列表项、表格行、标题、引用块——不按段落计数。"""
        s = line.lstrip()
        if s[:1] in ("-", "*", "+", "|", "#", ">", "\t"):
            return True
        return bool(re.match(r"^\d+[.)]\s", s))

    def tabular(line):
        """表格行，以及用 | 分字段的列表项——整行不是一个句子，不套句长规则。"""
        s = line.lstrip()
        if s[:1] == "|":
            return True
        return s[:1] in ("-", "*", "+") and line.count("|") >= 2

    def flush_para(at):
        nonlocal para_start, para_lines, para_chars, pile
        if prose and para_start is not None and (para_lines > 7 or para_chars > 400):
            add("warn", "paragraph-long", para_start, 1,
                f"段落 {para_lines} 行 / {para_chars} 字：一个段落只讲一个中心句，建议 ≤4 行、不超过 7 行",
                lines[para_start - 1], "华为 2.4")
        if prose and para_start is not None and len(pile) >= 3:
            words = "、".join(sorted({w for _, _, w in pile}))
            add("error", "boilerplate-pile", para_start, 1,
                f"同段套话 {len(pile)} 次（{words}）：套话在承重，改结构而不是逐词删",
                lines[para_start - 1], "qu-ai-wei pattern-catalog（编辑实践）+ 本仓库清单 C·套话")
        para_start, para_lines, para_chars = None, 0, 0
        pile = []

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
        extra = () if prose else CODE_MASK_RES + ([PY_PAREN] if py else [])
        m = mask_line(raw, extra)
        m = mask_time_colons(m)  # 时间点内部冒号不计入 colon-pile（A3）
        hex_spans = [(h.start(), h.end()) for h in HEX_RUN.finditer(raw)]
        # raw 与 m 等长（屏蔽是等长替换），所以 raw 上的位置可直接用于 m 上的命中位置。
        quote_idx = set()
        for qm in LEX_QUOTE.finditer(raw):
            quote_idx.update(range(qm.start(), qm.end()))
        bei_starts = {bm.start() for bm in BEI_RE.finditer(m)}
        if prose:  # 缩略语首现收集（华为 2.11）：判定在文件末尾，产出仍走 add 的级别与默认关过滤
            for am in ACR_RX.finditer(m):
                if am.start() in quote_idx:
                    continue  # 「UGC」这类被谈论的对象不是行文使用（与 A1 同一口径）
                tok = am.group(1)
                if tok in acr_first or tok in ACR_STOP:
                    continue
                if any(t in ACR_STOP for t in re.split(r"[/-]", tok)):
                    continue
                if ACR_EXPLAIN.match(m[am.end():am.end() + 80]):
                    acr_first[tok] = None
                else:
                    acr_first[tok] = (i, am.start() + 1, raw)
        if md:
            hm = HEADING.match(raw)
            if hm:
                headings.append((len(hm.group(1)), hm.group(2).rstrip("#").strip(), i))
        if raw.strip():
            if listish(raw) or soft_break(raw):  # 列表/表格/标题/引用块与短行断点不按段落计数
                flush_para(i)
            else:
                if para_start is None:
                    para_start = i
                para_lines += 1
                para_chars += width(m)  # 与句长同一口径：拉丁词按 1 计（2026-11-05 修订）
                for bm in BOILER_RE.finditer(m):
                    if bm.start() in quote_idx or in_enum(m, bm.start(), bm.end()):
                        continue  # 引号内与并列清单项不计套话密度（A1、A3）
                    pile.append((i, bm.start() + 1, bm.group(0)))
        else:
            flush_para(i)

        # 半角逗号当顿号用（ruanyf marks.md 顿号(1)）：这些逗号位点由下面两条规则报，
        # halfwidth-punct 不再重复报同一个逗号。感叹号连用时只报连用，不重复报单个。
        enum_cjk, enum_wide = enum_commas(m)
        enum_idx = set(enum_cjk) | set(enum_wide)
        pile_idx = {p for h in EXCLAIM_PILE.finditer(m) for p in range(h.start(), h.end())}
        flag_idx = {p for h in DASHFLAG.finditer(m) for p in range(h.start(), h.end())}
        js_line = bool(JS_TEMPLATE.search(raw))
        term_idx = set()
        if term_shape:
            for mm in TERM_DASH.finditer(m):
                term_idx.update(range(mm.start(), mm.end()))

        for rid, lvl, rx, msg, ref, rno, prose_only in COMPILED:
            if prose_only and not prose:
                continue
            if js_line:  # JS 模板行：引号、连字符、冒号都是代码语法（A5）
                continue
            for hit in rx.finditer(m):
                if rid in LEX_EXEMPT and hit.start() in quote_idx:
                    continue  # 引号内是被引用的对象，不是本文写法（2026-11-13 记录 A1）
                if rid == "colon-pile" and any(p in quote_idx for p in range(hit.start(), hit.end())):
                    continue  # 连排的两个冒号只要有一个在引号内，就是引用串内部的冒号（记录 A2）
                if rid in LIST_EXEMPT and in_enum(m, hit.start(), hit.end()):
                    continue  # 并列清单项：命中的词是被列举项（记录 A3）
                if rid == "bei-passive-open" and hit.start() in bei_starts:
                    continue  # 白名单已按 warn 报过，不再重复（记录 A4）
                if rid == "range-dash" and skip_range(m, hit):
                    continue
                if rid == "unit-symbol" and any(s0 <= hit.start() < e0 for s0, e0 in hex_spans):
                    continue  # 哈希串里的 cc/db 不是单位（2026-11-13 审计 A1）
                if rid == "halfwidth-punct" and hit.start() in enum_idx:
                    continue
                if rid == "dash-single" and hit.start() in term_idx:
                    continue  # 术语连接号（A2）
                if rid == "exclaim-soft" and hit.start() in pile_idx:
                    continue
                if rid == "double-hyphen":
                    d = hit.group(0).find("--")
                    if d >= 0 and (hit.start() + d) in flag_idx:
                        continue
                note = f"{msg}：{hit.group(0)} → {MISTYPES[hit.group(0)]}" if (
                    rid == "misprint" and hit.group(0) in MISTYPES) else msg
                add(lvl, rid, i, hit.start() + 1, note, raw, ref)

        for col in enum_cjk:
            add("error", "dunhao-comma", i, col + 1, LMSG["dunhao-comma"], raw)
        if prose:  # latin-enum-comma 在 PROSE_ONLY 里：代码行里的英文并列是语法，不是中文标点
            for col in enum_wide:
                add("warn", "latin-enum-comma", i, col + 1, LMSG["latin-enum-comma"], raw)

        # 句子级规则。表格单元格按片段写（华为 2.8：单元格 ≤6 行、不写整句），
        # 所以表格行不套用正文的句长与构件长度规则。
        # 句子级规则只收中文行：英文行套中文句长阈值是类别错误（2026-11-05 修订）。
        if prose and not tabular(raw) and cjk_rx.search(m):
            col = 0
            for sent in re.split(rf"(?<=[。！？；{chr(0xff1b)}])", m):
                if sent:
                    sentences.append((i, col, sent))
                col += len(sent)

    flush_para(len(lines) + 1)  # 文件末尾的段落也要结算：paragraph-long 与 boilerplate-pile 都在这里

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

    # 文件级规则（2026-11-13 检查记录 B1、B3、B4）：每文件至多一条，先聚合再按 min_level 过滤。
    file_hits = []
    if prose:
        nonempty = [(k, x) for k, x in enumerate(lines, 1) if x.strip()]
        if nonempty:
            k, last = nonempty[-1]
            if len(nonempty) >= 10 and not re.search(r"[。！？…」』）]|\|\s*$", last):
                file_hits.append(("hint", "truncated-file", k, 1,
                                  "文件结尾无句末标点，疑似截断；确认最后一段写完了", last))
        forms = {}
        for rx in DATE_FORMS:
            first = rx.search(text)
            if first:
                forms[rx.pattern] = first.group(0)
        if len(forms) >= 2:
            sample = "、".join(sorted(set(forms.values()))[:3])
            file_hits.append(("warn", "date-format-mixed", 1, 1,
                              f"文档内混用 {len(forms)} 种日期写法（如 {sample}），统一为 YYYY-MM-DD", lines[0]))
        if "％" in text and "%" in text:
            file_hits.append(("hint", "percent-form-mixed", 1, 1,
                              "同一文档混用全角％与半角%，统一为半角%", lines[0]))
    for lvl, rid, ln, col, msg, sn in file_hits:
        add(lvl, rid, ln, col, msg, sn)

    # 缩略语（华为 2.11，默认关）：每个未兑换的只报首现一处，后续裸用不重复报。
    for tok, v in acr_first.items():
        if not v:
            continue
        ln, col, sn = v
        add("hint", "acronym-unexplained", ln, col,
            f"缩略语「{tok}」首次出现未就地解释：写「{tok}（全称或中文说明）」", sn)

    return findings


def iter_files(targets, exts, excludes, max_size=None):
    for t in targets:
        p = Path(t)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in exts and not is_excluded(f, excludes):
                    if max_size and f.stat().st_size > max_size:
                        print(f"跳过（超 {max_size} 字节，--max-file-size 可调）: {f}", file=sys.stderr)
                        continue
                    yield f
        elif p.is_file():
            if not is_excluded(p, excludes):
                if max_size and p.stat().st_size > max_size:
                    print(f"跳过（超 {max_size} 字节，--max-file-size 可调）: {p}", file=sys.stderr)
                    continue
                yield p
        else:
            print(f"跳过（不存在）: {t}", file=sys.stderr)


DEFAULT_EXCLUDES = ["extracted/*", "document-style-guide/*", ".git/*", "feedback/*"]


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
                    help="排除路径（可多次）。默认已排除 extracted/、document-style-guide/（上游原文）与 feedback/（检查记录引用原文）")
    ap.add_argument("--enable", action="append", default=[], metavar="RULE",
                    help="打开默认关闭的规则（默认关：cjk-latin-space、acronym-unexplained）")
    ap.add_argument("--no-gate", action="store_true", help="有 error 也返回 0")
    ap.add_argument("--no-residual", action="store_true",
                    help="不打印「检查器判不了的 8 类」清单（默认打印，防止 0 error 被当成全合规）")
    ap.add_argument("--max-file-size", type=int, default=1048576, metavar="BYTES",
                    help="单文件体积闸门：超过此字节数跳过（默认 1 MB；0 为不限）。大 txt 数据文件会拖死目录模式（2026-11-13 检查事故）")
    a = ap.parse_args(argv)
    global _ENABLED_OFF
    _ENABLED_OFF = set(a.enable)

    if a.rules:
        print(f"{'规则':22} {'级别':7} {'清单':10} {'出处':36} 说明")
        for rid, lvl, _, msg, ref, rno, prose_only in COMPILED:
            tag = f"{lvl}*" if prose_only else lvl
            if rid in DEFAULT_OFF:
                tag += "（默认关）"
            print(f"{rid:22} {tag:7} {rno:10} {ref:36} {msg}")
        for rid, lvl, rno, ref, msg in LINE_RULES + STRUCTURE_RULES + FILE_RULES:
            print(f"{rid:22} {lvl:7} {rno:10} {ref:36} {msg}")
        print("\n「清单」列对应 rules/AI怪中文-常见病句清单与修法.md 的 R-xx 编号；空白 = 本仓库补充项或无对应条目。")
        print("带 * 的规则只跑散文文件（.md/.markdown/.txt）。")
        print("口径：汉字按字计、连续拉丁词按 1 计、标点不计；表格行不套用句长规则（华为 2.8 单元格按片段写）；「…」内超过 25 字按引文屏蔽")
        print("口径（2026-11-05 修订）：正文级规则（paragraph-long、long-sentence、clause-long、clause-enum）只套在 .md/.markdown/.txt 的中文行上；配置与代码文件只跑词法级规则")
        print("口径（2026-11-10 新增）：标题层级规则只跑 .md，跳过 YAML front matter 与代码块；并列逗号按整行构件判定，千分位与 e.g., 不算并列")
        print("口径（2026-11-10 新增）：.py 用 tokenize 抽出 docstring 与注释后只查这些文本；docstring 里半角括号段按代码写法屏蔽；--word 形式的双连字符（CLI 标志、CSS 变量）不算破折号误用")
        print("口径（2026-11-13 新增，来自 11-13 检查记录，原文存仓外不入库）：HTML 注释整块屏蔽；「汉字1～4字—汉字1～4字」同形 ≥3 次视为术语连接号不报 dash-single；纯时间点冒号不报 colon-pile；含 ${ 或 HTML 标签起行的 JS 模板行跳过词法规则；≤6 字无逗号短行视为断段点；单文件默认 >1MB 跳过（--max-file-size）")
        print("口径（2026-11-13 第二批，来自 research 库检查记录）：「」『』“”与直引号内的内容不参与词法级规则（规范文本会引用它禁止的形式）；顿号 ≥3 且无句末标点的行视为列举清单，boilerplate／bei-passive／jinxing-nominal／fuzzy-word 不计；白名单外的「被＋汉字」由 bei-passive-open 兜底报 hint，与 bei-passive 同位置不重复报")
        print("口径（2026-11-13 第三批，同一记录 B1）：缩略语首现未解释的出处核到华为 2.11（6.1 重申），不是记录里猜的 2.1；实测误报比撑不起默认闸门（本仓库 11 条候选 2 条真命中，research 库 122 条几乎全是该库自造的命题代号），所以规则照加、默认关，写交付手册时用 --enable acronym-unexplained 打开")
        return 0

    exts = {e.strip() if e.startswith(".") else "." + e.strip() for e in a.ext.split(",")}
    min_level = LEVELS[a.level]
    all_findings = []
    scanned = 0
    excludes = DEFAULT_EXCLUDES + (a.exclude or [])
    for f in iter_files(a.targets or ["."], exts, excludes, a.max_file_size):
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
        hint_top = {}
        for x in all_findings:
            if x["level"] == "hint":
                hint_top[x["rule"]] = hint_top.get(x["rule"], 0) + 1
        print(json.dumps({"files": scanned, "counts": counts,
                          "hintTopN": dict(sorted(hint_top.items(), key=lambda kv: -kv[1])),
                          "findings": all_findings},
                         ensure_ascii=False, indent=2))
    else:
        by_rule = {}
        for x in all_findings:
            by_rule.setdefault((x["rule"], x["level"]), []).append(x)
        order = {"error": 0, "warn": 1, "hint": 2}
        for (rid, lvl), items in sorted(by_rule.items(),
                                        key=lambda kv: (order[kv[0][1]], -len(kv[1]))):
            x0 = items[0]
            tag = f"；清单 {x0['rno']}" if x0.get("rno") else ""
            print(f"\n[{x0['level']:5}] {rid} × {len(items)}  — {x0['message']}  (出处：{x0['ref']}{tag})")
            for x in items[:12]:
                print(f"  {x['file']}:{x['line']}:{x['col']}  {x['snippet']}")
            if len(items) > 12:
                print(f"  …另 {len(items) - 12} 处")
        print(f"\n扫描 {scanned} 个文件：error {counts['error']}、warn {counts['warn']}、hint {counts['hint']}")
        print(f"本轮覆盖：只读 {'、'.join(sorted(exts))}；.py 不在目录模式内，要逐个传参"
              f"（--ext .py,.md 可并入）。读数只说明这些文件里没查出问题，不说明全库合规。")
        if not a.no_residual:
            print("\n" + RESIDUAL)

    return 1 if (counts["error"] and not a.no_gate) else 0


if __name__ == "__main__":
    sys.exit(main())
