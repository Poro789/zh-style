"""PDF -> 纯文本（仅标准库：re + zlib）。

适用：带 ToUnicode CMap 的 CID 字体（Identity-H + subset TrueType），Word 导出的中文 PDF 基本都属这一类。
用法：
    python tools/pdf2text.py <input.pdf> <output.txt>
输出按页分隔（`===== 第 N 页 =====`），只保证文字与换行，不还原表格与版式。
"""

import re
import sys
import zlib

OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj(.*?)endobj", re.S)
STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
REF_RE = re.compile(rb"(\d+)\s+0\s+R")
BFCHAR_RE = re.compile(rb"beginbfchar(.*?)endbfchar", re.S)
BFRANGE_RE = re.compile(rb"beginbfrange(.*?)endbfrange", re.S)
HEX_RE = re.compile(rb"<([0-9A-Fa-f\s]*)>")
ARR_RE = re.compile(rb"\[(.*?)\]", re.S)
TOK_RE = re.compile(
    rb"<<|>>|/\w+|\(|<[0-9A-Fa-f\s]*>|[-+]?\d*\.?\d+|[A-Za-z'\"]{1,3}|\[|\]|\{|\}"
)


class Pdf:
    def __init__(self, data):
        self.objs = {}
        for m in OBJ_RE.finditer(data):
            num, body = int(m.group(1)), m.group(3)
            head = body[: body.find(b"stream")] if b"stream" in body else body
            sm = STREAM_RE.search(body)
            stream = sm.group(1) if sm else None
            if stream is not None and b"/FlateDecode" in head:
                try:
                    stream = zlib.decompress(stream)
                except zlib.error:
                    pass
            self.objs[num] = {"dict": head, "stream": stream}

    def deref(self, ref):
        """把 `12 0 R` 或对象号解析成对象 dict。"""
        if isinstance(ref, int):
            return self.objs.get(ref)
        m = REF_RE.search(ref) if isinstance(ref, bytes) else None
        return self.objs.get(int(m.group(1))) if m else None

    def get(self, num, key):
        """取对象里某个 key 的值片段（到下一个 key 或定界符为止）。"""
        o = self.objs.get(num)
        if not o:
            return None
        m = re.search(re.escape(key) + rb"\s*", o["dict"])
        if not m:
            return None
        rest = o["dict"][m.end() :]
        stop = re.search(rb"/[A-Za-z]|>>", rest)
        return rest[: stop.start()] if stop else rest


def tounicode(pdf, font_obj):
    """CID -> unicode 字符。"""
    num = None
    m = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", font_obj["dict"])
    if not m:
        return {}
    st = pdf.objs.get(int(m.group(1)), {}).get("stream")
    if not st:
        return {}
    cmap = {}
    for blk in BFCHAR_RE.finditer(st):
        toks = re.findall(rb"<[0-9A-Fa-f\s]*>", blk.group(1))
        for src, dst in zip(toks[0::2], toks[1::2]):
            d = bytes.fromhex(re.sub(rb"\s", b"", src[1:-1]).decode())
            u = bytes.fromhex(re.sub(rb"\s", b"", dst[1:-1]).decode())
            cmap[int.from_bytes(d, "big")] = u.decode("utf-16-be", "ignore")
    for blk in BFRANGE_RE.finditer(st):
        toks = re.findall(rb"<[0-9A-Fa-f\s]*>|\[.*?\]|[-+]?\d+", blk.group(1), re.S)
        i = 0
        while i + 2 < len(toks):
            lo = int.from_bytes(bytes.fromhex(re.sub(rb"\s", b"", toks[i][1:-1]).decode()), "big")
            hi = int.from_bytes(bytes.fromhex(re.sub(rb"\s", b"", toks[i + 1][1:-1]).decode()), "big")
            third = toks[i + 2]
            if third.startswith(b"["):
                dsts = re.findall(rb"<[0-9A-Fa-f\s]*>", third)
                for k, d in enumerate(dsts[: hi - lo + 1]):
                    u = bytes.fromhex(re.sub(rb"\s", b"", d[1:-1]).decode())
                    cmap[lo + k] = u.decode("utf-16-be", "ignore")
                i += 3
                continue
            if third.startswith(b"<"):
                units = re.sub(rb"\s", b"", third[1:-1]).decode()
                if len(units) == 4:  # 单个 UTF-16BE 码元：dst 是起始码，逐个加
                    start = int(units, 16)
                    for k in range(hi - lo + 1):
                        cmap[lo + k] = chr(start + k)
                else:  # 写成多个码元：按位置对应
                    base = bytes.fromhex(units).decode("utf-16-be", "ignore")
                    for k, ch in enumerate(base[: hi - lo + 1]):
                        cmap[lo + k] = ch
            else:
                for k in range(hi - lo + 1):
                    cmap[lo + k] = chr(int(third) + k)
            i += 3
    return cmap


def unescape_literal(raw):
    out = bytearray()
    i = 0
    esc = {b"n": 10, b"r": 13, b"t": 9, b"b": 8, b"f": 12, b"(": 40, b")": 41, b"\\": 92}
    while i < len(raw):
        if raw[i : i + 1] != b"\\":
            out += raw[i : i + 1]
            i += 1
            continue
        nxt = raw[i + 1 : i + 2]
        if nxt in esc:
            out.append(esc[nxt])
            i += 2
            continue
        m = re.match(rb"[0-7]{1,3}", raw[i + 1 :])
        if m:
            out.append(int(m.group(0), 8))
            i += 1 + len(m.group(0))
            continue
        if nxt == b"\n":
            i += 2
            continue
        out += nxt
        i += 2
    return bytes(out)


def tokens(stream):
    i, n = 0, len(stream)
    while i < n:
        c = stream[i : i + 1]
        if c in b"%#":
            j = stream.find(b"\n", i)
            i = n if j < 0 else j + 1
            continue
        m = TOK_RE.match(stream, i)
        if not m:
            i += 1
            continue
        t = m.group(0)
        i = m.end()
        if t.startswith(b"("):
            depth, j = 1, i
            while j < n and depth:
                if stream[j : j + 1] == b"\\":
                    j += 2
                    continue
                if stream[j : j + 1] == b"(":
                    depth += 1
                elif stream[j : j + 1] == b")":
                    depth -= 1
                    if not depth:
                        break
                j += 1
            yield ("str", unescape_literal(stream[i:j]))
            i = j + 1
        elif t.startswith(b"<") and t.endswith(b">"):
            try:
                yield ("str", bytes.fromhex(re.sub(rb"\s", b"", t[1:-1]).decode()))
            except ValueError:
                pass
        else:
            yield ("tok", t)


def font_decoder(pdf, font_obj):
    """返回把字节串解码成 unicode 的函数。

    - Type0 / Identity-H：CID 字体，代码 2 字节，查 ToUnicode。
    - 简单字体（TrueType/Type1 + WinAnsiEncoding 等）：1 字节代码，按编码表解码。
    """
    d = font_obj["dict"]
    if b"/Subtype/Type0" in d or b"/Subtype /Type0" in d:
        cmap = tounicode(pdf, font_obj)
        return lambda raw, cmap=cmap: render_cid(raw, cmap)
    enc = "cp1252"
    if b"/MacRomanEncoding" in d:
        enc = "mac_roman"
    return lambda raw, enc=enc: raw.decode(enc, "replace")


def render_cid(raw, cmap):
    out = []
    for k in range(0, len(raw) - 1, 2):
        out.append(cmap.get(int.from_bytes(raw[k : k + 2], "big"), ""))
    return "".join(out)


def page_order(pdf):
    """按 /Pages 树顺序取页面对象号。"""
    root = next(
        (n for n, o in pdf.objs.items() if b"/Type/Catalog" in o["dict"]),
        None,
    )
    stack, pages = [], []
    if root:
        m = re.search(rb"/Pages\s+(\d+)\s+0\s+R", pdf.objs[root]["dict"])
        if m:
            stack.append(int(m.group(1)))
    while stack:
        num = stack.pop(0)
        d = pdf.objs.get(num, {}).get("dict", b"")
        kids = re.search(rb"/Kids\s*\[(.*?)\]", d, re.S)
        if kids:
            stack = [int(r.group(1)) for r in REF_RE.finditer(kids.group(1))] + stack
        elif b"/Type/Page" in d:
            pages.append(num)
    if not pages:  # 兜底：按对象号顺序
        pages = sorted(
            n for n, o in pdf.objs.items() if b"/Type/Page" in o["dict"] and b"/Contents" in o["dict"]
        )
    return pages


def resources(pdf, pnum):
    """页 /Resources（含从父节点继承）。"""
    seen = set()
    while pnum and pnum not in seen:
        seen.add(pnum)
        r = pdf.get(pnum, b"/Resources")
        if r:
            o = pdf.deref(r)
            return o or {}
        p = pdf.get(pnum, b"/Parent")
        pnum = int(REF_RE.search(p).group(1)) if p and REF_RE.search(p) else None
    return {}


def extract(src, dst):
    pdf = Pdf(open(src, "rb").read())
    out, total = [], 0
    for pi, pnum in enumerate(page_order(pdf), 1):
        res = resources(pdf, pnum)
        fonts = {}
        fm = re.search(rb"/Font\s*<<(.*?)>>", res.get("dict", b""), re.S)
        if fm:
            for name, ref in re.findall(rb"/(\w+)\s+(\d+)\s+0\s+R", fm.group(1)):
                fobj = pdf.objs.get(int(ref))
                if fobj:
                    fonts[name.decode()] = font_decoder(pdf, fobj)
        cval = pdf.get(pnum, b"/Contents")
        refs = [int(r.group(1)) for r in REF_RE.finditer(cval)] if cval else []
        lines, buf, font = [], [], None
        for cnum in refs:
            st = pdf.objs.get(cnum, {}).get("stream")
            if not st:
                continue
            pending_name = None
            for kind, val in tokens(st):
                if kind == "tok":
                    if val.startswith(b"/"):
                        pending_name = val[1:].decode()
                    elif val == b"Tf" and pending_name in fonts:
                        font = pending_name
                    elif val in (b"T*", b"Td", b"TD", b"'", b'"', b"ET"):
                        if buf:
                            lines.append("".join(buf))
                            buf = []
                elif kind == "str":
                    text = fonts.get(font, lambda raw: "")(val)
                    if text:
                        buf.append(text)
        if buf:
            lines.append("".join(buf))
        body = "\n".join(x for x in lines if x.strip())
        total += len(body)
        out.append(f"\n===== 第 {pi} 页 =====\n{body}")
    open(dst, "w", encoding="utf-8").write("\n".join(out).lstrip("\n"))
    print(f"pages={len(page_order(pdf))} chars={total} -> {dst}")


if __name__ == "__main__":
    extract(sys.argv[1], sys.argv[2])
