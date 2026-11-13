#!/usr/bin/env python3
"""从 HTML 交付物中提取中文散文，供 check_zh.py 过检。

用法:
    python tools/extract_html_clean.py <文件.html …> -o 输出目录
    python tools/extract_html_clean.py <html 所在目录>   # 只取该目录下直接的 .html，不递归

背景（rules/11-13-check-record.md · D2/A5）:
- <style> 整块跳过。
- <script> 不取代码，只取引号串（' " `）中 ≥4 字符且含汉字的片段。
- 过滤含 ${ 的行（JS 模板拼接，三元运算会把引号规则打成误报）
  和含 HTML 标签的行（模板里内嵌的 <div>/<svg> 会触发 range-dash 等误报）。
- 输出 输出目录/<文件名>_zh.txt，UTF-8、LF。行号与原文件不可互引，只用于过检。

纯标准库，无第三依赖。
"""
import argparse
import os
import re
import sys
from html.parser import HTMLParser

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
STR_RE = re.compile(r"(['\"`])((?:(?!\1)[^\\\n]|\\.)*?)(?=\1)", re.S)
TAG_LINE_RE = re.compile(r"<[A-Za-z][^>]*>")


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.scripts = []
        self._in_script = False
        self._in_style = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self._in_script = True
            self._buf = []
            return
        if tag == "style":
            self._in_style = True
            return
        if tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "tr", "br",
                   "section", "article", "label", "option", "button", "table"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "script" and self._in_script:
            self.scripts.append("".join(self._buf))
            self._in_script = False
        elif tag == "style" and self._in_style:
            self._in_style = False

    def handle_data(self, data):
        if self._in_script:
            self._buf.append(data)
        elif not self._in_style and data.strip():
            self.parts.append(data)


def _js_strings(script):
    out = []
    for m in STR_RE.finditer(script):
        s = m.group(2).replace("\\n", "\n").replace("\\t", " ")
        if len(s) >= 4 and CJK_RE.search(s):
            out.append(s)
    return out


def extract_one(src, out_dir):
    with open(src, encoding="utf-8", errors="replace") as f:
        p = _Extractor()
        p.feed(f.read())

    lines = []
    for ln in "".join(p.parts).splitlines():
        if ln.strip() and not TAG_LINE_RE.search(ln) and "${" not in ln:
            lines.append(ln.rstrip())
    for sc in p.scripts:
        for s in _js_strings(sc):
            for ln in s.splitlines():
                ln = ln.strip()
                if ln and CJK_RE.search(ln) and not TAG_LINE_RE.search(ln) and "${" not in ln:
                    lines.append(ln)
    text = "\n".join(lines).strip() + "\n"

    base = os.path.splitext(os.path.basename(src))[0]
    out_path = os.path.join(out_dir, base + "_zh.txt")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return out_path, len(text)


def main(argv=None):
    ap = argparse.ArgumentParser(description="提取 HTML 中文散文供 check_zh.py 使用")
    ap.add_argument("paths", nargs="+", help=".html 文件或包含 .html 的目录（目录不递归）")
    ap.add_argument("-o", "--outdir", default=".", help="输出目录，默认当前目录")
    args = ap.parse_args(argv)
    os.makedirs(args.outdir, exist_ok=True)

    files = []
    for p in args.paths:
        if os.path.isdir(p):
            for name in sorted(os.listdir(p)):
                if name.lower().endswith(".html"):
                    files.append(os.path.join(p, name))
        elif os.path.isfile(p):
            files.append(p)
        else:
            print(f"跳过（不存在）: {p}", file=sys.stderr)
    for src in files:
        out_path, n = extract_one(src, args.outdir)
        print(f"{src} -> {out_path}  ({n} 字)")
    print(f"共 {len(files)} 个文件；用 python tools/check_zh.py 逐个或按目录过检。")
    return 0


if __name__ == "__main__":
    sys.exit(main())