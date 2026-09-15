#!/usr/bin/env python3
"""
股票代码解析器
==============
根据股票名称或代码，解析出标准的 ticker。
"""
import pandas as pd
from .constants import SRC_PQ


def resolve_ticker(name_or_code: str) -> tuple:
    """根据股票名称或代码，返回 (ticker, name)"""
    df = pd.read_parquet(SRC_PQ)
    instruments = df.index.get_level_values('instrument').unique().tolist()

    # 精确匹配代码
    if name_or_code in instruments:
        return name_or_code, name_or_code

    # 模糊匹配名称（中文或拼音）
    matches = [i for i in instruments if name_or_code in str(i)]
    if len(matches) == 1:
        return matches[0], matches[0]

    # 通过中文名称反向查找
    from .constants import CODE_MAP
    if name_or_code in CODE_MAP:
        ticker = CODE_MAP[name_or_code]
        return ticker, name_or_code

    # 尝试匹配代码后四位
    if name_or_code.isdigit() and len(name_or_code) == 6:
        for prefix in ['SH', 'SZ', 'BJ']:
            t = prefix + name_or_code
            if t in instruments:
                return t, t
        # 尝试无前缀
        for t in instruments:
            if t.endswith(name_or_code):
                return t, t

    raise ValueError(f"无法识别股票: {name_or_code}，请使用代码（如 SH601668）或常见中文名")
