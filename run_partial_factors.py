#!/usr/bin/env python3
"""Run all 13 fixed factors and convert to HDF5."""
import os
import pandas as pd
from pathlib import Path

BASE = Path('/run/media/onai/MyDisk/Work/RD-Agent-Work/git_ignore_folder/RD-Agent_workspace')

sessions = [
    '0d44eee04fdc468b9b0d2ebe0195f8ad',
    '29adb6eee8e740979cff12363fb47acc',
    '36db7f0e80c6467ba4999782236f1065',
    '4b1ad47505f449d0a645977c75cdb9fe',
    '54dec2334bec4988a5b89200917dcac3',
    '59ea2fae700c41bfb82d9a90cbee008a',
    '7072985109f24e2cb928bee2e1b48954',
    '889763ef5b55432686a1a2fb5d014d9a',
    '95f3d8929cd44c03bcd7fb108b945339',
    'b01b40ad1350475d921dd819d27add61',
    'c02e96ccd2644d36b7a1812b3b933541',
    'd789d95d712e4e64b5f9190f234b0bd1',
    'e380dae07ef8479f8523be67cdda0743',
]

def main():
    print("Running 13 fixed factors...")
    for sid in sessions:
        sdir = BASE / sid
        os.chdir(sdir)
        factor_py = sdir / 'factor.py'
        # Remove old result
        h5 = sdir / 'result.h5'
        pq = sdir / 'result.parquet'
        for f in [h5, pq]:
            if f.exists():
                f.unlink()
        
        with open(factor_py) as f:
            code = f.read()
        
        ns = {}
        try:
            exec(compile(code, str(factor_py), 'exec'), ns)
            func_name = code.split('def ')[1].split('(')[0].strip()
            if func_name in ns:
                ns[func_name]()
            # Verify
            if h5.exists():
                df = pd.read_hdf(h5, key='data')
                rows = len(df)
                stocks = df.index.get_level_values('instrument').nunique()
                status = "✅" if rows >= 8392254 and stocks >= 5553 else "⚠️"
                print(f"  {status} {sid}: {rows:,} rows, {stocks} stocks")
            else:
                print(f"  ❌ {sid}: no result.h5")
        except Exception as e:
            print(f"  ❌ {sid}: {e}")

if __name__ == '__main__':
    main()
