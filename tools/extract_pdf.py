#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_pdf.py — 把 PDF 提取成 UTF-8 文本，自动挑选可用工具。

优先级：pdftotext（poppler，最快最准）→ pypdf（纯 Python）→ pdf2text.py（纯标准库后备）。

用法：
    python tools/extract_pdf.py "references/xxx.pdf" [-o extracted/xxx.txt] [--force pdftotext|pypdf|stdlib]

不带 -o 时，输出写到 extracted/<同名>.<工具后缀>.txt，避免覆盖别的工具的结果。
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

# winget 装的 poppler 不保证在继承来的 PATH 里，按位置兜底找一次
POPPLER_GLOBS = [
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\*Poppler*\*\Library\bin\pdftotext.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\pdftotext.exe"),
    r"C:\Program Files\poppler*\bin\pdftotext.exe",
]


def find_pdftotext() -> str | None:
    exe = shutil.which("pdftotext")
    if exe:
        return exe
    hits: list[str] = []
    for pattern in POPPLER_GLOBS:
        hits += glob.glob(pattern)
    return sorted(hits)[-1] if hits else None


def has_pypdf() -> bool:
    try:
        import pypdf  # noqa: F401
    except ImportError:
        return False
    return True


def run_pdftotext(exe: str, pdf: Path, out: Path) -> str:
    subprocess.run([exe, "-enc", "UTF-8", str(pdf), str(out)], check=True)
    return out.read_text(encoding="utf-8", errors="replace")


def run_pypdf(pdf: Path, out: Path) -> str:
    import pypdf

    reader = pypdf.PdfReader(str(pdf))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    out.write_text(text, encoding="utf-8")
    return text


def run_stdlib(pdf: Path, out: Path) -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import pdf2text

    pdf2text.extract(str(pdf), str(out))  # 自己写文件并打印统计
    return out.read_text(encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="PDF 转 UTF-8 文本，自动选择工具")
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", help="输出文件；缺省写 extracted/<名>.<工具>.txt")
    ap.add_argument("--force", choices=["pdftotext", "pypdf", "stdlib"],
                    help="跳过自动选择，指定工具")
    args = ap.parse_args()

    pdf = Path(args.pdf)
    if not pdf.is_file():
        print(f"找不到文件：{pdf}", file=sys.stderr)
        return 2

    tools: list[tuple[str, object]] = []
    exe = find_pdftotext()
    if exe:
        tools.append(("pdftotext", lambda p, o: run_pdftotext(exe, p, o)))
    if has_pypdf():
        tools.append(("pypdf", run_pypdf))
    tools.append(("stdlib", run_stdlib))  # pdf2text.py 永远可用

    chosen = args.force or tools[0][0]
    for name, fn in tools:
        if name != chosen:
            continue
        # 默认写到 extracted/，不污染 references/（上游原文目录按只读处理）
        default_dir = Path(__file__).resolve().parent.parent / "extracted"
        out = Path(args.out) if args.out else default_dir / f"{pdf.stem}.{chosen}.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        text = fn(pdf, out)
        print(f"{name}: {len(text)} 字符 → {out}")
        if name != tools[0][0]:
            print(f"（首选其实是 {tools[0][0]}；用 --force {name} 固定了这一选择）",
                  file=sys.stderr)
        return 0

    print(f"未选择到工具，可用：{[n for n, _ in tools]}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
