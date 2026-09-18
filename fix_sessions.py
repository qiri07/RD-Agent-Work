#!/usr/bin/env python3
from __future__ import annotations
"""
批量修复：重新生成 h5 + 重算因子
"""
import os
import re
import time
from pathlib import Path

import pandas as pd
from concurrent.futures import ProcessPoolExecutor, as_completed

ws = Path('git_ignore_folder/RD-Agent_workspace')


def regen_h5_for_session(sid):
    """Regenerate daily_pv.h5 from daily_pv.parquet"""
    pq = ws / sid / 'daily_pv.parquet'
    h5 = ws / sid / 'daily_pv.h5'
    if not (pq.exists() and h5.exists()):
        return sid, False, 'missing files'
    if os.path.getmtime(h5) >= os.path.getmtime(pq):
        return sid, True, 'skipped (up-to-date)'
    try:
        df = pd.read_parquet(pq)
        df.to_hdf(h5, key='data', mode='w', format='table')
        return sid, True, f'{len(df):,} rows'
    except Exception as e:
        return sid, False, str(e)


def recompute_factor_for_session(sid):
    """Re-run factor.py for a session"""
    session = ws / sid
    factor_py = session / 'factor.py'
    if not factor_py.exists():
        return sid, False, 'no factor.py'
    old_cwd = os.getcwd()
    try:
        os.chdir(session)
        code = factor_py.read_text(encoding='utf-8')
        func_match = re.search(r'def\s+(\w+)\s*\(\s*\):', code)
        func_name = func_match.group(1) if func_match else None
        namespace = {}
        from engine.safe_factor_exec import run_factor_script
        success, info = run_factor_script(factor_py)
        if not success:
            return sid, False, info
        result_h5 = session / 'result.h5'
        if result_h5.exists():
            df = pd.read_hdf(result_h5, key='data')
            return sid, True, f'{len(df):,} rows'
        return sid, False, 'no result.h5'
    except Exception as e:
        return sid, False, str(e)[:100]
    finally:
        os.chdir(old_cwd)


if __name__ == '__main__':
    sessions = sorted([d for d in ws.iterdir() if d.is_dir() and (d / 'factor.py').exists()])
    print(f'Total sessions: {len(sessions)}')

    # Step 1: Parallel h5 regeneration (4 workers)
    print("\nStep 1: Regenerating h5 files...")
    t0 = time.time()
    h5_fixed = 0
    h5_failed = 0
    with ProcessPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(regen_h5_for_session, s.name): s.name for s in sessions}
        for future in as_completed(futures):
            sid, ok, info = future.result()
            if ok:
                h5_fixed += 1
            else:
                h5_failed += 1
                print(f'  FAILED {sid}: {info}', flush=True)
            if h5_fixed % 10 == 0:
                print(f'  Progress: {h5_fixed} done...', flush=True)
    print(f'Step 1 done: {h5_fixed} fixed, {h5_failed} failed ({time.time()-t0:.1f}s')

    # Step 2: Find incomplete sessions
    print("\nStep 2: Finding incomplete sessions...")
    incomplete = []
    for s in sessions:
        result_h5 = s / 'result.h5'
        if result_h5.exists():
            df = pd.read_hdf(result_h5, key='data')
            if len(df) < 7_000_000:
                incomplete.append(s.name)
    print(f'Sessions needing factor recompute: {len(incomplete)}')

    # Step 3: Parallel factor recompute (4 workers)
    print("\nStep 3: Recomputing factors...")
    t0 = time.time()
    fix_success = 0
    fix_fail = 0
    with ProcessPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(recompute_factor_for_session, sid): sid for sid in incomplete}
        for future in as_completed(futures):
            sid, ok, info = future.result()
            if ok:
                fix_success += 1
                print(f'  OK {sid}: {info}', flush=True)
            else:
                fix_fail += 1
                print(f'  FAIL {sid}: {info}', flush=True)
            if fix_success + fix_fail > 0 and (fix_success + fix_fail) % 10 == 0:
                print(f'  Progress: {fix_success + fix_fail}/{len(incomplete)}...', flush=True)
    print(f'\nStep 3 done: {fix_success} success, {fix_fail} fail ({time.time()-t0:.1f}s')

    # Final verification
    print("\nFinal verification...")
    complete = 0
    for s in sessions:
        result_h5 = s / 'result.h5'
        if result_h5.exists():
            df = pd.read_hdf(result_h5, key='data')
            if len(df) >= 7_000_000:
                complete += 1
    print(f'Complete sessions: {complete}/{len(sessions)}')
