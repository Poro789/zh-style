# zh-style-kit

中文写作规范工具包，用来解决一件事：**让 AI 写出来的中文不再是「怪中文」**（翻译腔、模糊夸大词、半角标点、`10-20kg` 这类不合规写法）。

做法是把两份可执行的规范放进仓库，再配一个零依赖的规则检查器：AI 先按规范写，再用检查器卡住能自动判定的部分。

## 目录结构

```
zh-style-kit/
├── README.md
├── AGENTS.md                     给 AI 的入口：写作纪律 + 命令
├── references/
│   └── 产品手册中文写作规范.pdf   原件，59 页，721,808 字节
├── extracted/
│   └── 产品手册中文写作规范.raw.txt  逐字提取文本（59 页 / 41,982 字，含页眉页脚与水印）
├── rules/
│   ├── 华为产品手册中文写作规范-要点.md   按原文章节重排的要点（含全部数字、例子、表 7 单位）
│   └── AI怪中文-常见病句清单与修法.md      本仓库自撰：症状 → 病句 → 改法
├── tools/
│   ├── pdf2text.py               纯标准库 PDF → 文本（无 pdftotext、无第三方库时的替代）
│   └── check_zh.py               中文规则检查器（纯标准库）
├── samples/
│   ├── bad-example.md            故意写坏的样例（也是检查器的测试输入）
│   └── good-example.md           同一内容的改写版，可作给模型的风格示例
└── document-style-guide/         阮一峰《文档风格指南》整仓克隆（docs/ 下 6 篇）
```

## 两份来源

| 来源 | 内容 | 位置 |
| --- | --- | --- |
| 华为 DKBA1313—2003.12《产品手册中文写作规范》（2004-03-15 实施，59 页） | 标题层级、段落 ≤7 行、句子 ≤100 字、项目列表、表格、说明/注意分级、缩略语、数值与计量单位、中文标点、界面控件名称 | [references/产品手册中文写作规范.pdf](references/产品手册中文写作规范.pdf)，取自 [tiger8888/books-4](https://github.com/tiger8888/books-4)（仓库根目录） |
| [ruanyf/document-style-guide](https://github.com/ruanyf/document-style-guide) | 标点、数值、段落、标题、文档体系、字间距与英文处理，附正反例 | [document-style-guide/docs/](document-style-guide/docs/)（已克隆，公共领域） |

两份规范在**大数字分节**上互相冲突：华为用半角空格（`2 345 567 456`，2.13.2），阮一峰用半角逗号（`1,000`，number.md）。本仓库默认用逗号，但一篇文档里必须只用一种——检查器不判这一条，靠约定。

## 用法

检查一个目录或文件（默认扫 `.md` 与 `.txt`）：

```
python tools/check_zh.py .
python tools/check_zh.py rules/ samples/ --level warn
python tools/check_zh.py docs/README.md --json
python tools/check_zh.py --rules          # 打印全部规则及出处
```

退出码：有 `error` 级问题返回 1，可用于 CI 闸门（`--no-gate` 关闭）。级别分三档：`error` 明确违反规范、`warn` 需人判断、`hint` 风格提示。

### 读数怎么读

检查器把代码块、行内代码、URL、文件名替换成等长空格再判定，所以这些区域不计入。默认排除 `extracted/` 与 `document-style-guide/`：上游原文有 OCR 换行和 2003 年的旧排版，扫它们的读数没有意义。

本仓库文档里也引用了反面例子。已改成行内代码的不计入；仍写在引号里的原文例句会计入，例如 `rules/华为产品手册中文写作规范-要点.md:174` 引用的「计费策略：表示计费：1，表示不计费：2」。`samples/bad-example.md` 是故意写坏的测试输入，读数高属预期。判读顺序：先看目标文档的 `error`，再看 `warn`；`hint` 只在写对外文档时处理。


从 PDF 重新提取文本：

```
python tools/extract_pdf.py "references/产品手册中文写作规范.pdf"
python tools/extract_pdf.py <pdf> --force pypdf      # 指定工具
python tools/pdf2text.py <pdf> <out.txt>             # 纯标准库后备（两个参数，无 -o）
```

`extract_pdf.py` 按 `pdftotext` → `pypdf` → `pdf2text.py` 顺序自动选择，输出写到 `extracted/<名>.<工具>.txt`，不覆盖别的工具结果。本机已装：poppler 25.07.0（`winget install --id oschwartz10612.Poppler`）、pypdf 6.21.4（miniconda 里是 6.14.2）。winget 只把 poppler 的 bin 加到用户 PATH，安装前就在跑的进程取不到，脚本会按绝对路径兜底。

三方对同一份 PDF 的读数：`pdftotext` 41403 字符、`pypdf` 41489 字符、`pdf2text.py` 41982 字符；汉字数一致（正文 15560），自写版多出的 118 字全是页脚「第」「页」。`pdf2text.py` 处理 Type0/Identity-H 与简单字体两类，靠 ToUnicode 映射中文，已知限制见文件头注释。

## 更新来源

```
git -C document-style-guide pull --depth 1
curl -L -o "references/产品手册中文写作规范.pdf" ^
  "https://raw.githubusercontent.com/tiger8888/books-4/master/%E4%BA%A7%E5%93%81%E6%89%8B%E5%86%8C%E4%B8%AD%E6%96%87%E5%86%99%E4%BD%9C%E8%A7%84%E8%8C%83.pdf"
```

下载后核对字节数应为 721,808；不一致就是上游改过文件，需要重新提取并重写 `rules/华为产品手册中文写作规范-要点.md`。

## 边界

- `references/` 与 `document-style-guide/` 是上游原文，只读，不在这里改。
- `rules/` 下两份要点是人工整理的二手摘要，写文档时以 `extracted/` 的原文为准（原文有 OCR 换行噪声，数字常被拆行）。
- 检查器只报问题、不改文件。自动改写风险高（会把「降低了 30%」改成错的表述）。
