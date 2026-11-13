"""check_zh.py 的行为断言（纯标准库 unittest，无第三方依赖）。

跑法：python tools/test_check_zh.py
这些断言锁住三件事：样例文件的应有读数、两条 2026-11-13 审计修掉的误报、
cjk-latin-space 的默认关闭开关。改检查器口径后先跑它。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_zh  # noqa: E402

HERE = Path(__file__).resolve().parent
SAMPLES = HERE.parent / "samples"


def findings(text, name="t.md", level="hint"):
    return check_zh.check_text(name, text, check_zh.LEVELS[level])


def rules_of(text, name="t.md", level="hint"):
    return {f["rule"] for f in findings(text, name, level)}


class SampleFiles(unittest.TestCase):
    def test_bad_example_error_count(self):
        """bad-example.md 是故意写坏的测试输入，error 数锁在 15。"""
        text = (SAMPLES / "bad-example.md").read_text(encoding="utf-8")
        errs = [f for f in check_zh.check_text(str(SAMPLES / "bad-example.md"), text, 3)
                if f["level"] == "error"]
        self.assertEqual(len(errs), 15, msg=f"实际 {len(errs)} 条：{[f['rule'] for f in errs]}")

    def test_good_example_clean(self):
        """good-example.md 必须全绿，否则检查器在自相矛盾。"""
        path = SAMPLES / "good-example.md"
        text = path.read_text(encoding="utf-8")
        self.assertEqual(check_zh.check_text(str(path), text, 1), [])


class Audit20261113(unittest.TestCase):
    """30 条人工判定里修掉的两类误报，防回归。"""

    def test_unit_symbol_ignores_hex_run(self):
        """提交哈希 0edd96cc 里的 cc 不是立方厘米。"""
        self.assertNotIn("unit-symbol", rules_of("已由 commit 0edd96cc 修复。", level="error"))

    def test_unit_symbol_still_catches_real_unit(self):
        """真单位仍要报，别把规则一起关了。"""
        self.assertIn("unit-symbol", rules_of("线长 10 KM。", level="error"))

    def test_clause_long_skips_tabular_list(self):
        """用 | 分字段的列表项不是一句话，不该算构件长度。"""
        line = ("- **1. 创伤知情五原则** | 一句话：安全、可信、选择权、协作、赋权，"
                "核心戒律不追问细节也不替对方定暴露深度 | 学习成本：1-2小时 | 承接她人：防最坏错误的保险丝")
        self.assertNotIn("clause-long", rules_of(line, level="warn"))

    def test_clause_long_still_catches_prose(self):
        """真超长的散文构件仍要报。"""
        line = ("这一大套东西的真实用途不是把人升级成治疗师而是把人从怕接不住这件事里解放出来"
                "升级成知道边界所以敢在场而且已经在供给的那样东西")
        self.assertIn("clause-long", rules_of(line, level="warn"))


class BoilerplatePile(unittest.TestCase):
    """套话密度口径：单次是线索，同段落 ≥3 次才报 error（照上游的规则结构）。"""

    def test_three_in_one_paragraph_is_error(self):
        text = "值得注意的是，方案效果不错。综上所述，团队付出很多。由此可见，推广有价值。"
        self.assertIn("boilerplate-pile", rules_of(text, level="error"))

    def test_single_occurrence_is_not_error(self):
        self.assertNotIn("boilerplate-pile",
                         rules_of("值得注意的是，这个参数在 10 秒内生效。", level="error"))

    def test_two_occurrences_is_not_error(self):
        self.assertNotIn("boilerplate-pile",
                         rules_of("值得注意的是，方案不错。综上所述，团队付出很多。", level="error"))

    def test_paragraph_boundary_resets_count(self):
        """空行分段后各段单独计数，不跨段累加。"""
        text = ("值得注意的是，方案不错。" + "\n\n"
                "综上所述，团队付出很多。" + "\n\n"
                "由此可见，推广有价值。")
        self.assertNotIn("boilerplate-pile", rules_of(text, level="error"))

    def test_eof_paragraph_is_flushed(self):
        """文件末尾没有空行时也要结算（曾经漏掉）。"""
        text = ("值得注意的是，方案不错。" + "\n"
                "综上所述，团队付出很多。" + "\n"
                "由此可见，推广有价值。")
        self.assertIn("boilerplate-pile", rules_of(text, level="error"))


class DefaultOff(unittest.TestCase):
    """cjk-latin-space 默认关，--enable 打开。"""

    def setUp(self):
        self._saved = set(check_zh._ENABLED_OFF)

    def tearDown(self):
        check_zh._ENABLED_OFF = self._saved

    def test_off_by_default(self):
        check_zh._ENABLED_OFF = set()
        self.assertNotIn("cjk-latin-space", rules_of("中文English混排。"))

    def test_enabled_on_request(self):
        check_zh._ENABLED_OFF = {"cjk-latin-space"}
        self.assertIn("cjk-latin-space", rules_of("中文English混排。"))
        check_zh._ENABLED_OFF = set()


if __name__ == "__main__":
    unittest.main(verbosity=2)
