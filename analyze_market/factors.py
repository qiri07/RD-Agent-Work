#!/usr/bin/env python3
"""
因子计算模块（numpy向量化版）
==============================
对单只股票的numpy数组计算各类量化因子。
"""
import numpy as np


def compute_all_factors_np(close_arr, volume_arr):
    """对单只股票的numpy数组计算所有因子"""
    n = len(close_arr)
    factors = {}

    for p in [5, 10, 20, 60]:
        shifted = np.empty(n)
        shifted[:p] = np.nan
        shifted[p:] = close_arr[:-p]
        factors[f'momentum_{p}d'] = close_arr / shifted - 1

    # reversal
    rev = np.empty(n)
    rev[:5] = np.nan
    rev[5:] = -(close_arr[5:] / close_arr[:-5] - 1)
    factors['reversal_5d'] = rev

    # volatility
    rets = np.diff(np.log(close_arr))
    for p in [10, 20, 60]:
        vol = np.full(n, np.nan)
        for i in range(p, n):
            vol[i] = np.std(rets[i-p:i], ddof=1) * np.sqrt(252)
        factors[f'volatility_{p}d'] = vol

    # volume ratio
    vol_ma = np.full(n, np.nan)
    for i in range(20, n):
        vol_ma[i] = np.mean(volume_arr[i-20:i])
    factors['volume_ratio'] = volume_arr / vol_ma

    # RSI
    delta = np.diff(close_arr)
    gain = np.maximum(delta, 0)
    loss = np.maximum(-delta, 0)
    rs = np.full(n, np.nan)
    rsi = np.full(n, np.nan)
    for i in range(14, n):
        rg = np.mean(gain[i-14:i])
        rl = np.mean(loss[i-14:i])
        if rl == 0:
            rs[i] = np.inf
        else:
            rs[i] = rg / rl
        rsi[i] = 100 - (100 / (1 + rs[i]))
    factors['rsi_14'] = rsi

    # MACD (simplified EMA)
    ema12 = np.full(n, np.nan)
    ema26 = np.full(n, np.nan)
    k12 = 2/13
    k26 = 2/27
    ema12[0] = close_arr[0]
    ema26[0] = close_arr[0]
    for i in range(1, n):
        ema12[i] = close_arr[i] * k12 + ema12[i-1] * (1-k12)
        ema26[i] = close_arr[i] * k26 + ema26[i-1] * (1-k26)
    macd_line = ema12 - ema26
    factors['macd'] = macd_line

    # MACD signal
    k9 = 2/10
    macd_sig = np.full(n, np.nan)
    macd_sig[0] = macd_line[0]
    for i in range(1, n):
        macd_sig[i] = macd_line[i] * k9 + macd_sig[i-1] * (1-k9)
    factors['macd_signal'] = macd_sig
    factors['macd_hist'] = macd_line - macd_sig

    # Bollinger
    bb = np.full(n, np.nan)
    for i in range(20, n):
        ma = np.mean(close_arr[i-20:i])
        sd = np.std(close_arr[i-20:i], ddof=1)
        bb[i] = (close_arr[i] - ma) / (2 * sd)
    factors['bollinger_pos'] = bb

    return factors


def compute_forward_ret_np(close_arr):
    """计算forward return (5日)"""
    n = len(close_arr)
    fr = np.full(n, np.nan)
    for i in range(n-5):
        fr[i] = close_arr[i+5] / close_arr[i] - 1
    return fr
