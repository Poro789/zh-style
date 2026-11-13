# zh-style-kit

中文写作规范工具包，用来解决一件事：**让 AI 写出来的中文不再是「怪中文」**。
症状包括翻译腔、半角标点、模糊与夸大的词，以及 `10-20kg` 这类不合规写法。

做法是把两份可机检的规范放进仓库，再配一个零依赖的规则检查器：AI 先按规范写，再用检查器卡住机器能判的那些。

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
│   ├── 规范分级-按频率与伤害排序.md        33 条规则按违反频率 × 读者伤害分级（先读这份）
│   ├── 华为产品手册中文写作规范-要点.md   按原文章节重排的要点（含全部数字、例子、表 7 单位）
│   └── AI怪中文-常见病句清单与修法.md      本仓库自撰：症状 → 病句 → 改法
├── feedback/
│   ├── 检查记录-模板.md                   检查记录模板（个案记录与口径提案，不是交付规则）
│   └── 检查记录-YYYY-MM-DD-<目标库>-<主题>.md  一次检查一份；引用原文，不进检查器扫描
├── tools/
│   ├── extract_pdf.py            PDF → UTF-8 文本入口，自动选 pdftotext / pypdf / pdf2text
│   ├── pdf2text.py               纯标准库 PDF → 文本（无 pdftotext、无第三方库时的替代）
│   ├── check_zh.py               中文规则检查器（纯标准库）
│   ├── zh_triage.py              读数聚合层：把逐条发现压成 top 表（纯标准库）
│   └── test_check_zh.py          检查器行为断言（unittest，纯标准库）
├── samples/
│   ├── bad-example.md            故意写坏的样例（也是检查器的测试输入）
│   └── good-example.md           同一内容的改写版，可用作喂给模型的风格示例
└── document-style-guide/         阮一峰《文档风格指南》整仓克隆（docs/ 下 7 篇）
```

## 两份来源

| 来源 | 内容 | 位置 |
| --- | --- | --- |
| 华为 DKBA1313—2003.12《产品手册中文写作规范》（2004-03-15 实施，59 页） | 标题层级、段落 ≤7 行、句子 ≤100 字、项目列表、表格、说明/注意分级、缩略语、数值与计量单位、中文标点、界面控件名称 | [references/产品手册中文写作规范.pdf](references/产品手册中文写作规范.pdf)，取自 [tiger8888/books-4](https://github.com/tiger8888/books-4)（仓库根目录） |
| [ruanyf/document-style-guide](https://github.com/ruanyf/document-style-guide) | 标点、数值、段落、标题、文档体系、字间距与英文处理，附正反例 | [document-style-guide/docs/](document-style-guide/docs/)（已克隆，公共领域） |

两份规范在**大数字分节**上冲突：华为用半角空格（`2 345 567 456`，2.13.2），阮一峰用半角逗号（`1,000`，number.md）。本仓库默认用逗号，但一篇文档里必须只用一种——检查器不判这一条，靠约定。

## 用法

检查一个目录或文件（默认扫 `.md` 与 `.txt`）：

```
python tools/check_zh.py .
python tools/check_zh.py rules/ samples/ --level warn
python tools/check_zh.py docs/README.md --json
python tools/check_zh.py --rules          # 打印全部规则、清单编号与出处

python tools/zh_triage.py .               # 读数压成 top 表，有 error 退出码 1
python tools/zh_triage.py . --files       # 附上读数最响的 5 个文件
python tools/test_check_zh.py             # 检查器断言：样例读数与两处误报修复
```

退出码：有 `error` 级问题返回 1，可用于 CI 闸门（`--no-gate` 关闭）。

级别分三档：`error` 明确违反规范、`warn` 需人判断、`hint` 只提示风格。

文本输出末尾固定打印一段「检查器判不了的 8 类」自查清单，另加删修饰、回译两个测试。未覆盖的条款不产生报错，绿色读数容易被当成全量校验的凭证。CI 里用 `--no-residual` 关掉这段。

`--rules` 的「清单」列把每条规则映射到 `rules/AI怪中文-常见病句清单与修法.md` 的 `R-xx` 编号，报错可以直接反查改法。空白表示该条没有清单编号。

## 2026-11-13 审计（30 条抽样）

全量语料 1,324 个中文文档，`error` 8,778 条。按规则分层抽 30 条逐条判定：`dunhao-comma` 11/11 真、`halfwidth-punct` 11/11 真、`clause-long` 3/4 真、`range-unit` 2/2 真、`unit-symbol` 1/2 真（另 1 条是提交哈希里的 `cc`，1 条定位不到）。

据此改了三处：

- `unit-symbol` 不再判十六进制串里的 `cc`、`db`（`HEX_RUN` 排除）。
- `clause-long` 不再把「`-` 开头、含 ≥2 个 `|`」的表格化列表项算成一个构件（36 处）。
- `cjk-latin-space` 默认关。中英文空格交给 `zhlint` 这类前置排版工具；需要时用 `--enable cjk-latin-space` 打开。

两条主力规则合计占 87.8% 的 `error`，实测全真，因此没有降级任何 `error` 级规则。

- `boilerplate` 拆成两条。单次出现报 `hint`，只当线索；同一段落内 ≥3 次报 `error`（`boilerplate-pile`）。口径照上游的规则结构——单次不算问题，反复出现才算。全量 1,324 个文档上 `boilerplate-pile` 0 命中，等于一条零误报、也还没拦过东西的保险。

`feedback/` 下引用真实档案原文的记录不入库（见 `.gitignore`），只保留模板与脱敏判定。

## 读数怎么读

检查器把代码块、行内代码、URL、文件名替换成等长空格再判定，所以这些区域不计入。省略号「……」内超过 25 字按引文处理。

句子级规则三条：

- `long-sentence`：整句 >100 字（华为 2.5）。
- `clause-long`：逗号之间的构件 >40 字报 `error`，30～39 字报 `warn`（DSG 文本·句子(1)）。
- `clause-enum`：4 个以上并列项挤在一句，改项目列表（华为 2.6）。

长度口径：汉字按字计、连续拉丁词按 1 计、标点不计，否则中英混排会虚高。表格行不套用句长规则，因为华为 2.8 规定单元格按片段写。

默认排除 `extracted/`、`document-style-guide/` 与 `feedback/`。上游原文有 OCR（光学字符识别）换行，还带 2003 年的旧排版，扫出来的读数没有参考价值。`feedback/` 里的记录引用原文作证据，同样不进扫描。

并列逗号（`dunhao-comma`、`latin-enum-comma`）的判定口径：先看整行的半角逗号，按逗号两侧的构件串成并列链。链上左右都是汉字的，报 `error`；链含拉丁词时，只有整行有中文、且并列项 ≥3 个，才报 `warn`。千分位（`10,200`）、缩写后的逗号（`e.g., foo`）、纯英文整句里的逗号都不算并列。同一位置不再重复报 `halfwidth-punct`，感叹号连用时只报 `exclaim-pile` 一次。

标题层级规则只跑 `.md`，并跳过 YAML front matter 与代码块。`heading-skip` 查相邻标题跳级，`heading-orphan` 查某个标题下只有一个直接子标题。

正文级规则（`paragraph-long`，加上面三条句子级规则）只套在 `.md`/`.markdown`/`.txt` 的中文行上。配置与代码文件只跑词法级规则：引号内的字符串按数据处理，注释仍然检查。

这两条适用范围限定是 2026-11-05 加的。扫 YAML 配置时，结构行会被当成正文段落；扫英文行时，中文句长阈值会全线误报。噪声盖过了真实信号。

本仓库文档里也引用了反面例子。已改成行内代码的不计入；仍写在引号里的原文例句会计入，例如 `rules/华为产品手册中文写作规范-要点.md:174` 引用的 `计费策略：表示计费：1，表示不计费：2`。`samples/bad-example.md` 是故意写坏的测试输入，读数高属预期。

判读顺序：先看目标文档的 `error`，再看 `warn`；`hint` 只在写对外文档时处理。

## 从 PDF 重新提取文本


```
python tools/extract_pdf.py "references/产品手册中文写作规范.pdf"
python tools/extract_pdf.py <pdf> --force pypdf      # 指定工具
python tools/pdf2text.py <pdf> <out.txt>             # 纯标准库后备（两个参数，无 -o）
```

`extract_pdf.py` 按 `pdftotext` → `pypdf` → `pdf2text.py` 顺序自动选择，输出写到 `extracted/<名>.<工具>.txt`，不覆盖别的工具结果。

本机已装 poppler 25.07.0（`winget install --id oschwartz10612.Poppler`）与 pypdf 6.21.4（miniconda 里是 6.14.2）。winget 只把 poppler 的 bin 加到用户 PATH，安装前就在跑的进程取不到它，脚本会按绝对路径兜底。

三方对同一份 PDF 的读数：`pdftotext` 41,403 字符、`pypdf` 41,489 字符、`pdf2text.py` 41,982 字符。汉字数一致，正文 15,560 字。`pdf2text.py` 比 `pdftotext` 多出的 118 字全是页脚的「第」「页」。`pdf2text.py` 处理 Type0/Identity-H 与简单字体两类，靠 ToUnicode 映射中文。已知限制见文件头注释。

## 更新来源

```
git -C document-style-guide pull --depth 1
curl -L -o "references/产品手册中文写作规范.pdf" `
  "https://raw.githubusercontent.com/tiger8888/books-4/master/%E4%BA%A7%E5%93%81%E6%89%8B%E5%86%8C%E4%B8%AD%E6%96%87%E5%86%99%E4%BD%9C%E8%A7%84%E8%8C%83.pdf"
```

下载后核对字节数应为 721,808；不一致就是上游改过文件，需要重新提取并重写 `rules/华为产品手册中文写作规范-要点.md`。

## 边界

- `references/` 与 `document-style-guide/` 是上游原文，只读，不在这里改。
- `rules/` 下三份要点是人工整理的二手摘要，写文档时以 `extracted/` 的原文为准（原文有 OCR 换行噪声，数字常被拆行）。
- 检查器只报问题、不改文件。自动改写风险高（会把「降低了 30%」改成错的表述）。

## 反馈与改进

检查输出与交付口径对不上时，把差异写成检查记录。按 `feedback/检查记录-模板.md` 写，存 `feedback\`。记录分四类：A 误判、B 新规则候选、C 够不着区、D 工具与流程提案。头部写机器侧读数，A / B 各条带处置字段。

入口：满足任一条件才写记录。同一规则在同库误判 ≥2 处；规则没抓到的新特征，带反例；检查器异常且定位了根因。一个目标库一次检查至多一份，每条必须有 `文件:行号`。

出口：
- A 误判 → 改 `check_zh.py` 口径。保持纯标准库，只报不改。
- B 新规则候选 → 出处可查证才进检查器。出处是华为章节号、ruanyf 文件名、本仓库清单编号。
- C 够不着区 → 留在记录。同一边界连续两份记录确认后，移入「边界」节。
- D 工具与流程提案 → 进 `tools\`。

实施完把记录的处置字段回填。
