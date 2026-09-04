#!/usr/bin/env python3
"""
Verify all factor results and convert parquet to hdf5.
Usage: python3 verify_factors.py [--convert]
"""
import os
import sys
import pandas as pd
from pathlib import Path

import config as cfg

BASE = cfg.RDAGENT_WORKSPACE
TARGET_ROWS = 8392254
TARGET_STOCKS = 5553

def read_result(session_dir: Path):
    """Read result from h5 or parquet, returning DataFrame."""
    h5 = session_dir / 'result.h5'
    pq = session_dir / 'result.parquet'
    if h5.exists():
        try:
            return pd.read_hdf(h5, key='data'), 'h5'
        except Exception:
            pass
    if pq.exists():
        return pd.read_parquet(pq), 'parquet'
    return None, None

def main(convert=False):
    print("=" * 70)
    print("Factor Result Verification")
    print("=" * 70)
    
    sessions = sorted([d for d in BASE.iterdir() if d.is_dir() and (d / 'factor.py').exists()])
    print(f"Total sessions: {len(sessions)}\n")
    
    full_count = 0
    partial_count = 0
    no_result = 0
    need_conversion = 0
    
    for s in sessions:
        df, fmt = read_result(s)
        if df is None:
            print(f"  ❌ {s.name}: NO result")
            no_result += 1
            continue
        
        rows = len(df)
        stocks = df.index.get_level_values('instrument').nunique()
        status = "✅" if rows >= TARGET_ROWS and stocks >= 5000 else "⚠️"
        
        if rows >= TARGET_ROWS and stocks >= 5000:
            full_count += 1
        elif rows > 0:
            partial_count += 1
        else:
            no_result += 1
        
        if fmt == 'parquet' and not (s / 'result.h5').exists():
            need_conversion += 1
        
        print(f"  {status} {s.name}: {rows:,} rows, {stocks} stocks ({fmt})")
    
    print(f"\n{'=' * 70}")
    print(f"Full data (≥{TARGET_ROWS:,} rows): {full_count}")
    print(f"Partial results: {partial_count}")
    print(f"No result: {no_result}")
    print(f"Need parquet→hdf5 conversion: {need_conversion}")
    print(f"{'=' * 70}")
    
    if convert and need_conversion > 0:
        print("\nConverting parquet → hdf5...")
        convert_ok = 0
        convert_fail = 0
        for s in sessions:
            pq = s / 'result.parquet'
            h5 = s / 'result.h5'
            if pq.exists() and not h5.exists():
                try:
                    df = pd.read_parquet(pq)
                    df.to_hdf(str(h5), key='data', mode='w')
                    convert_ok += 1
                    print(f"  ✅ {s.name}")
                except ImportError as e:
                    convert_fail += 1
                    print(f"  ❌ {s.name}: {e}")
                except Exception as e:
                    convert_fail += 1
                    print(f"  ❌ {s.name}: {e}")
        print(f"\nConversion: {convert_ok} OK, {convert_fail} failed")

if __name__ == '__main__':
    main(convert='--convert' in sys.argv)
