#!/usr/bin/env python3
"""
数据去重脚本 — 修复 daily_pv_full.parquet 中的重复行问题
=========================================================
根因: convert_tradero_to_rdagent.py 多次运行累积重复，
      且重复行内容可能不完全相同（保留首次出现）。

用法:
    python3 deduplicate_source_data.py [--apply]
    
    --apply       应用去重并覆盖原文件（默认只报告）
    --output      指定输出路径（不覆盖原文件时有效）
"""
import argparse
import sys
import warnings
warnings.filterwarnings('ignore')

import pandas as pd
from pathlib import Path

import config as cfg


def main():
    parser = argparse.ArgumentParser(description='数据去重工具')
    parser.add_argument('--apply', action='store_true', help='应用去重并覆盖原文件')
    parser.add_argument('--output', type=str, default=None, help='输出文件路径（不覆盖原文件）')
    args = parser.parse_args()

    src = cfg.DAILY_PV_FULL_PQ
    if not src.exists():
        print(f"❌ 源文件不存在: {src}")
        sys.exit(1)

    print("=" * 60)
    print("  数据去重工具")
    print("=" * 60)

    print(f"\n📂 加载数据: {src}")
    t0 = __import__('time').time()
    df = pd.read_parquet(src)
    load_time = __import__('time').time() - t0
    print(f"  加载完成: {len(df):,} rows, {df.index.nunique():,} unique, {load_time:.1f}s")

    # 统计重复
    dup_count = len(df) - df.index.nunique()
    dup_rate = dup_count / len(df) * 100 if len(df) > 0 else 0
    print(f"  重复行数: {dup_count:,} ({dup_rate:.1f}%)")

    if dup_count == 0:
        print("\n✅ 数据无重复，无需去重")
        return

    # 检查重复行内容是否完全一致
    all_same = True
    check_count = 0
    for idx, group in df.groupby(df.index):
        if len(group) > 1:
            first = group.iloc[0]
            for i in range(1, len(group)):
                if not group.iloc[i].equals(first):
                    all_same = False
                    break
        check_count += 1
        if check_count >= 1000:  # 抽样检查
            break

    print(f"  重复行内容一致: {'是' if all_same else '否（部分有差异）'}")

    # 去重（保留首次出现的行）
    print(f"\n🔧 执行去重...")
    before = len(df)
    df_unique = df[~df.index.duplicated(keep='first')]
    after = len(df_unique)
    removed = before - after
    print(f"  去重前: {before:,} rows")
    print(f"  去重后: {after:,} rows")
    print(f"  移除:   {removed:,} rows ({removed/before*100:.1f}%)")
    print(f"  唯一股票: {df_unique.index.get_level_values('instrument').nunique():,}")
    print(f"  日期范围: {df_unique.index.get_level_values(0).min().date()} ~ {df_unique.index.get_level_values(0).max().date()}")

    if not args.apply and not args.output:
        print(f"\n  ⚠️  仅报告模式，未保存。使用 --apply 覆盖原文件或 --output 指定新路径。")
        return

    # 保存
    out_path = Path(args.output) if args.output else src
    print(f"\n💾 保存去重后数据: {out_path}")
    t1 = __import__('time').time()
    df_unique.to_parquet(str(out_path), engine="pyarrow")
    save_time = __import__('time').time() - t1
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"  保存完成: {size_mb:.1f} MB, {save_time:.1f}s")

    # 同时更新 h5 格式
    h5_path = src.parent / src.name.replace('.parquet', '.h5')
    if args.apply or args.output:
        print(f"\n💾 同步更新 HDF5: {h5_path}")
        import subprocess
        env_py = Path(__file__).parent / "rdagent-env" / "bin" / "python"
        if env_py.exists():
            result = subprocess.run(
                [str(env_py), "-c",
                 f"import pandas as pd; "
                 f"df=pd.read_parquet('{out_path}'); "
                 f"df.to_hdf('{h5_path}', key='data', mode='w')"],
                capture_output=True, text=True, timeout=180,
            )
            if result.returncode == 0:
                print(f"  HDF5 更新完成")
            else:
                print(f"  ⚠️  HDF5 更新失败: {result.stderr[:200]}")
        else:
            print(f"  ⚠️  未找到 rdagent-env/python，跳过 HDF5 更新")


if __name__ == "__main__":
    main()
