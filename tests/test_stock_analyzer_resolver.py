"""stock_analyzer/resolver.py 全覆盖测试。

覆盖：
  - resolve_ticker 精确匹配
  - 模糊匹配
  - CODE_MAP 查找
  - 代码后四位匹配
  - ValueError 抛出
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from stock_analyzer.resolver import resolve_ticker


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_src_pq(tmp_path) -> str:
    """创建带 instrument index 的 parquet 文件。"""
    instruments = ["SH600519", "SZ000001", "BJ430047", "SH601318", "SZ000858"]
    df = pd.DataFrame({"value": range(len(instruments))})
    df.index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2026-01-01"), inst) for inst in instruments],
        names=["date", "instrument"],
    )
    pq_path = tmp_path / "src.parquet"
    df.to_parquet(pq_path)
    return str(pq_path)


@pytest.fixture(autouse=True)
def patch_src_pq(mock_src_pq: str, monkeypatch) -> None:
    """将 SRC_PQ 指向测试文件。"""
    import stock_analyzer.resolver as mod
    from pathlib import Path
    monkeypatch.setattr(mod, "SRC_PQ", Path(mock_src_pq))


# ── 精确匹配 ─────────────────────────────────────────────────────────────────


class TestExactMatch:
    def test_sh_ticker(self) -> None:
        ticker, name = resolve_ticker("SH600519")
        assert ticker == "SH600519"
        assert name == "SH600519"

    def test_sz_ticker(self) -> None:
        ticker, name = resolve_ticker("SZ000001")
        assert ticker == "SZ000001"
        assert name == "SZ000001"


# ── CODE_MAP 查找 ────────────────────────────────────────────────────────────


class TestCodeMapLookup:
    def test_chinese_name_lookup(self) -> None:
        """通过中文名查找 ticker。"""
        from stock_analyzer.constants import CODE_MAP
        if not CODE_MAP:
            pytest.skip("CODE_MAP 为空，跳过中文名称测试")
        first_key = next(iter(CODE_MAP))
        ticker, name = resolve_ticker(first_key)
        assert ticker == CODE_MAP[first_key]
        assert name == first_key


# ── 代码后四位匹配 ────────────────────────────────────────────────────────────


class TestSuffixMatch:
    def test_6digit_sh_suffix(self) -> None:
        ticker, name = resolve_ticker("600519")
        assert ticker == "SH600519"

    def test_6digit_sz_suffix(self) -> None:
        ticker, name = resolve_ticker("000001")
        assert ticker == "SZ000001"

    def test_no_match_suffix(self) -> None:
        with pytest.raises(ValueError, match="无法识别股票"):
            resolve_ticker("999999")

    def test_non_digit_suffix_ignored(self) -> None:
        with pytest.raises(ValueError):
            resolve_ticker("abcdef")


# ── 模糊匹配 ─────────────────────────────────────────────────────────────────


class TestFuzzyMatch:
    def test_contains_match_unique(self) -> None:
        """部分字符串匹配，唯一结果。"""
        ticker, name = resolve_ticker("60051")
        assert ticker == "SH600519"

    def test_ambiguous_match_raises(self) -> None:
        """多个匹配结果 → ValueError。"""
        # SH600519 和 SH600518 都包含 "60051"
        with patch("stock_analyzer.resolver.pd.read_parquet") as mock_read:
            instruments = ["SH600518", "SH600519"]
            df = pd.DataFrame({"value": range(2)})
            df.index = pd.MultiIndex.from_tuples(
                [(pd.Timestamp("2026-01-01"), inst) for inst in instruments],
                names=["date", "instrument"],
            )
            mock_read.return_value = df
            with pytest.raises(ValueError, match="无法识别股票"):
                resolve_ticker("60051")


# ── 异常场景 ─────────────────────────────────────────────────────────────────


class TestExceptions:
    def test_empty_instruments(self) -> None:
        """空数据源 → ValueError。"""
        with patch("stock_analyzer.resolver.pd.read_parquet") as mock_read:
            df = pd.DataFrame(columns=["value"])
            df.index = pd.MultiIndex.from_tuples([], names=["date", "instrument"])
            mock_read.return_value = df
            with pytest.raises(ValueError, match="无法识别股票"):
                resolve_ticker("SH600519")

    def test_read_parquet_error(self) -> None:
        with patch("stock_analyzer.resolver.pd.read_parquet", side_effect=IOError("read error")):
            with pytest.raises(IOError):
                resolve_ticker("SH600519")
