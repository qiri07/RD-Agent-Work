import pandas as pd, numpy as np
from pathlib import Path
import warnings; warnings.filterwarnings('ignore')

import config as cfg

# Use cleaned data
SOURCE_H5 = cfg.FACTOR_SOURCE_DEBUG / "daily_pv_clean.h5"
WORKSPACE = cfg.RDAGENT_WORKSPACE


def main():
    df = pd.read_hdf(SOURCE_H5, key='data').sort_index()
    print(f'Clean data: {len(df):,} rows, {df.index.get_level_values("instrument").nunique()} stocks')

    # Compute forward 5-day returns
    returns_5d = df['$close'].groupby(level='instrument').pct_change(5).ffill().dropna()
    print(f'Forward returns: {len(returns_5d):,}, mean={returns_5d.mean()*100:.4f}%, median={returns_5d.median()*100:.4f}%')

    # IC analysis for top 3 factors
    fids = [
        ('04d1651ebc7043c9bd047ca828cc479e', 'vol_spike'),
        ('b8e06aae49f84b30956ea750ee2df222', 'vol_ratio5d'),
        ('02d7dce95b7f410aa3ba2f8c2ab29b57', 'mom_10d'),
    ]
    print('\n=== IC with CLEAN returns ===')
    for fid, name in fids:
        fp = WORKSPACE / fid / "result.h5"
        fs = pd.read_hdf(fp, key='data').iloc[:,0].ffill().dropna()
        matches = fs.dropna().index.intersection(returns_5d.dropna().index)
        if len(matches) < 100:
            print(f'  {name}: not enough matches ({len(matches)})')
            continue
        f = fs.loc[matches]
        r = returns_5d.loc[matches]
        ic = f.corr(r)
        decile = f.rank(pct=True)
        top10 = r[decile>=0.9]
        bot10 = r[decile<=0.1]
        print(f'{name:>12}: IC={ic:.4f}, top10_mean={top10.mean()*100:+.3f}%, top10_med={top10.median()*100:+.3f}%, bot10={bot10.mean()*100:+.3f}%')

    # Yearly IC for momentum
    print('\n=== Yearly IC for momentum_10d ===')
    fp = WORKSPACE / "02d7dce95b7f410aa3ba2f8c2ab29b57" / "result.h5"
    fs = pd.read_hdf(fp, key='data').iloc[:,0].ffill().dropna()
    matches = fs.dropna().index.intersection(returns_5d.dropna().index)
    f, r = fs.loc[matches], returns_5d.loc[matches]
    for y in [2023, 2024, 2025, 2026]:
        y_mask = f.index.get_level_values('datetime').year == y
        if y_mask.sum() < 50: continue
        fy, ry = f.loc[y_mask], r.loc[y_mask]
        ic_y = fy.corr(ry)
        t10 = ry[fy.rank(pct=True)>=0.9]
        print(f'  {y}: IC={ic_y:.4f}, top10_med={t10.median()*100:+.3f}%, n={len(ry)}')

    # Quick full scan: compute IC for ALL factors, write to file
    print('\n=== Full scan (writing to file) ===')
    LOOKAHEAD = {'3e4aa8771f2340e5a1602649bb7c07bb','a9358be3286b43ea84ff83c315f54547',
        '54dec2334bec4988a5b89200917dcac3','1e3c8739f45b4179bf192e0b7918bfb8',
        '3d8b904927e248158b3ef3bf52ae0d43','4414a9e452e44991b2434a0cb59e745e',
        '4e839e97c7b74a10a025fd048ea13d84','5c64640e427045c3983fd3d23de776da',
        '60998d75688c43f797781fde92ac4506','29adb6eee8e740979cff12363fb47acc'}

    results = []
    count = 0
    for d in sorted(WORKSPACE.iterdir()):
        if not d.is_dir() or d.name in LOOKAHEAD: continue
        h5 = d/'result.h5'
        if not h5.exists(): continue
        try:
            fdf = pd.read_hdf(h5, key='data')
            fname = fdf.columns[0]
            s = fdf.rename(columns={fname:d.name})[d.name].ffill().fillna(0)
            s = s[~s.index.duplicated(keep='first')]
            matches = s.dropna().index.intersection(returns_5d.dropna().index)
            if len(matches) < 100: continue
            f = s.loc[matches]
            r = returns_5d.loc[matches]
            ic = f.corr(r)
            decile = f.rank(pct=True)
            top10_med = r[decile>=0.9].median()*100
            results.append((d.name, ic, top10_med, len(matches)))
            count += 1
            if count % 10 == 0:
                print(f'  Processed {count} factors...')
        except Exception as e:
            pass

    results.sort(key=lambda x: abs(x[1]), reverse=True)
    with open('factor_ranking_clean.txt', 'w') as out:
        out.write(f'Total factors analyzed: {len(results)}\n')
        out.write(f'{"#":>3} {"因子ID":>16} {"IC":>8} {"|IC|":>7} {"top10_med%":>12}\n')
        out.write('-'*50 + '\n')
        for i,(fid, ic, top10, n) in enumerate(results[:20],1):
            out.write(f'{i:>3} {fid:>16} {ic:>8.4f} {abs(ic):>7.4f} {top10:>+11.3f}%\n')
    print(f'Saved top-20 ranking to factor_ranking_clean.txt')
    print(f'Total factors analyzed: {len(results)}')


if __name__ == "__main__":
    main()
