#!/usr/bin/env python3
from __future__ import annotations
"""
engine/safe_factor_exec.py 测试
"""
import sys
from pathlib import Path

import pytest
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.safe_factor_exec import validate_factor_code, run_factor_script


class TestValidateFactorCode:
    def test_safe_code(self):
        code = "import pandas as pd\nimport numpy as np\n\ndef factor():\n    return pd.Series([1,2,3])"
        violations = validate_factor_code(code)
        assert violations == []

    def test_os_system_blocked(self):
        code = "import os\nos.system('rm -rf /')"
        violations = validate_factor_code(code)
        assert any('os.system' in v for v in violations)

    def test_eval_blocked(self):
        code = "result = eval(user_input)"
        violations = validate_factor_code(code)
        assert any('eval()' in v for v in violations)

    def test_exec_blocked(self):
        code = "exec(dangerous_code)"
        violations = validate_factor_code(code)
        assert any('exec()' in v for v in violations)

    def test_subprocess_blocked(self):
        code = "import subprocess\nsubprocess.run(['ls'])"
        violations = validate_factor_code(code)
        assert any('subprocess' in v for v in violations)

    def test_file_write_blocked(self):
        code = 'with open("output.txt", "w") as f:\n    f.write("hello")'
        violations = validate_factor_code(code)
        assert any('文件写入' in v for v in violations)

    def test_file_append_blocked(self):
        code = 'with open("output.txt", "a") as f:\n    f.write("hello")'
        violations = validate_factor_code(code)
        assert any('文件追加' in v for v in violations)

    def test_import_os_blocked(self):
        code = "import os\nprint(os.getcwd())"
        violations = validate_factor_code(code)
        assert any('导入 os' in v for v in violations)

    def test_multiple_violations(self):
        code = "import os\nimport subprocess\nresult = eval('1+1')"
        violations = validate_factor_code(code)
        assert len(violations) >= 3

    def test_pandas_numpy_ok(self):
        code = """
import pandas as pd
import numpy as np
df = pd.DataFrame({'a': [1,2,3]})
s = df['a'].mean()
"""
        violations = validate_factor_code(code)
        assert violations == []

    def test_open_read_ok(self):
        code = 'with open("input.txt", "r") as f:\n    content = f.read()'
        violations = validate_factor_code(code)
        assert violations == []

    def test_empty_code(self):
        assert validate_factor_code("") == []

    def test_only_comments(self):
        # 注释中包含 import os 会触发规则（安全优先设计）
        code = "# This is a comment\n# import os should not be checked"
        violations = validate_factor_code(code)
        assert len(violations) >= 1


class TestRunFactorScript:
    def test_missing_file(self, tmp_path):
        missing = tmp_path / "nonexistent.py"
        ok, info = run_factor_script(missing)
        assert not ok
        assert "无 factor.py" in info

    def test_safe_script_runs(self, tmp_path):
        """脚本通过安全校验并正常执行"""
        factor_py = tmp_path / "factor.py"
        factor_py.write_text(
            "df['factor_test'] = df['close'].pct_change()\n",
            encoding="utf-8",
        )
        df = pd.DataFrame({"close": [1.0, 2.0, 3.0, 4.0, 5.0]})
        ok, info = run_factor_script(factor_py, extra_vars={"df": df})
        assert ok
        assert "成功" in info

    def test_dangerous_script_rejected(self, tmp_path):
        """危险脚本被拦截"""
        factor_py = tmp_path / "bad_factor.py"
        factor_py.write_text("import os\nos.system('echo pwned')", encoding="utf-8")
        ok, info = run_factor_script(factor_py)
        assert not ok
        assert "安全校验失败" in info

    def test_execution_error_handled(self, tmp_path):
        """执行时报错返回 False"""
        factor_py = tmp_path / "error_factor.py"
        factor_py.write_text(
            "raise ValueError('test error')\n",
            encoding="utf-8",
        )
        ok, info = run_factor_script(factor_py, extra_vars={})
        assert not ok
        assert "执行失败" in info

    def test_minimal_script(self, tmp_path):
        factor_py = tmp_path / "ok_factor.py"
        factor_py.write_text("x = 1\n", encoding="utf-8")
        ok, info = run_factor_script(factor_py)
        assert ok
