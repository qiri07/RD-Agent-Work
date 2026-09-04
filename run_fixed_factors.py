#!/usr/bin/env python3
"""
Run all 11 fixed factors and convert to HDF5.
Reads from parquet, writes to both parquet and hdf5.
"""
import os
import sys
import pandas as pd
from pathlib import Path

BASE = Path('/run/media/onai/MyDisk/Work/RD-Agent-Work/git_ignore_folder/RD-Agent_workspace')

sessions = {
    '0e589b24e03e472b8e42b10aa0f49f0e': 'calculate_volume_ratio_5d',
    '2cb4b5273aa9433489e45414bef08f67': 'calculate_PriceMomentum_10d',
    '3ef33683c244464c990cdbc62603fe40': 'calculate_medium_term_momentum_20d',
    '5315a043edb24782a88423bda5f67946': 'calculate_VolWeighted_Return_1d',
    'a9358be3286b43ea84ff83c315f54547': 'calculate_intraday_strength',
    'f700dcc15e24475c805a37a5266a012a': 'calculate_momentum_20d',
    '1274f8dfd7b94c8c89c87cc450826cbf': 'calculate_10d_Return_Std',
    'b4d4062434eb448bb99309452e419ad9': 'calculate_RealizedVol_HL_10d',
    'e4a5995b1d3c48f8a34eae87de928ff1': 'calculate_momentum_5d_ew',
    'edf5da7804e54f7fa7200aea263b937f': 'calculate_momentum_20d_ew',
    '61d516c548964e01a58211c84a8a9aee': 'calculate_momentum_10d_ew',
}

def main():
    print("Running 11 fixed factors with HDF5 output...")
    for sid, fname in sessions.items():
        sdir = BASE / sid
        os.chdir(sdir)
        factor_py = sdir / 'factor.py'
        # Remove old results
        for f in ['result.h5', 'result.parquet']:
            p = sdir / f
            if p.exists():
                p.unlink()
        
        with open(factor_py) as f:
            code = f.read()
        
        ns = {}
        try:
            exec(compile(code, str(factor_py), 'exec'), ns)
            if fname in ns:
                ns[fname]()
            # Also ensure HDF5 output exists
            pq = sdir / 'result.parquet'
            h5 = sdir / 'result.h5'
            if pq.exists() and not h5.exists():
                df = pd.read_parquet(pq)
                df.to_hdf(str(h5), key='data', mode='w')
                print(f"  ✅ {sid}: {len(df):,} rows, {df.index.get_level_values('instrument').nunique()} stocks -> h5")
            elif h5.exists():
                df = pd.read_hdf(h5, key='data')
                print(f"  ✅ {sid}: {len(df):,} rows, {df.index.get_level_values('instrument').nunique()} stocks")
            else:
                print(f"  ⚠️  {sid}: no result produced")
        except Exception as e:
            print(f"  ❌ {sid}: {e}")

if __name__ == '__main__':
    main()
