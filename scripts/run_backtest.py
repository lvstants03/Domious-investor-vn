#!/usr/bin/env python
"""
CLI Script: Chay Walk-Forward Backtest cho Dominus Paper Portfolio.

Su dung:
    cd dominus-investor
    python scripts/run_backtest.py --symbols VCB,HPG,FPT --start 2024-01-01 --end 2025-12-31
    python scripts/run_backtest.py --basket VN30 --start 2024-01-01
    python scripts/run_backtest.py --help
"""
import argparse
import asyncio
import json
import sys
import os
from datetime import date, timedelta

# Them project root vao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

VN30 = [
    "ACB", "BCM", "BID", "BVH", "CTG", "FPT", "GAS", "GVR", "HDB", "HPG",
    "MBB", "MSN", "MWG", "PLX", "POW", "SAB", "SHB", "SSB", "SSI", "STB",
    "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE",
]


def parse_args():
    p = argparse.ArgumentParser(
        description="Dominus Walk-Forward Backtest"
    )
    p.add_argument("--symbols", type=str, help="Danh sach ma cach nhau boi dau phay: VCB,HPG,FPT")
    p.add_argument("--basket", choices=["VN30"], default=None, help="Dung ro chuan san co")
    p.add_argument("--start",  type=str, default=str(date.today() - timedelta(days=730)),
                   help="Ngay bat dau YYYY-MM-DD (default: 2 nam truoc)")
    p.add_argument("--end",    type=str, default=str(date.today()),
                   help="Ngay ket thuc YYYY-MM-DD (default: hom nay)")
    p.add_argument("--score-thresh", type=float, default=80.0,
                   help="Nguong diem toi thieu de mo lenh (default: 80.0)")
    p.add_argument("--stop-pct",   type=float, default=9.0,   help="Stop Loss pct theo cau truc nen (default: 9.0)")
    p.add_argument("--target-pct", type=float, default=30.0,  help="Take Profit pct song quy (default: 30.0)")
    p.add_argument("--hold-days",  type=int,   default=60,    help="So ngay giu toi da ~1 quy (default: 60)")
    p.add_argument("--out", type=str, default=None, help="Luu ket qua ra file JSON")
    return p.parse_args()


def print_summary(result: dict):
    print("\n" + "="*60)
    print("  WALK-FORWARD BACKTEST - KET QUA TONG HOP")
    print("="*60)

    s = result.get("summary", {})
    print(f"  Tong lenh        : {result.get('total_trades', 0)}")
    print(f"  So fold          : {s.get('num_folds', 0)}")
    print(f"  Win Rate         : {s.get('win_rate', 0):.1f}%")
    print(f"  Sharpe Ratio     : {s.get('sharpe', 0):.2f}")
    print(f"  Max Drawdown     : {s.get('max_drawdown', 0):.1f}%")
    print(f"  Profit Factor    : {s.get('profit_factor', 0):.2f}")
    print(f"  Total Return     : {s.get('total_return_pct', 0):+.1f}%")

    c = result.get("calibration", {})
    print("\n  CALIBRATION:")
    print(f"  Nguong nen dung  : {c.get('recommended_threshold', 70):.0f} diem")
    print(f"  Win Rate o nguong: {c.get('win_rate_at_threshold', 0):.1f}%")
    print(f"  Loi khuyen       : {c.get('note', '')}")

    print("\n  CHI TIET THEO FOLD:")
    header = f"  {'Fold':>4} | {'Test Period':^24} | {'#':>4} | {'Win%':>6} | {'Sharpe':>7} | {'MaxDD%':>7} | {'Ret%':>7}"
    print(header)
    print("  " + "-"*80)
    for f in result.get("folds", []):
        print(
            f"  {f['fold']:>4} | {f['test']:^24} | {f['num_signals']:>4} | "
            f"{f['win_rate']:>5.1f}% | {f['sharpe']:>7.2f} | "
            f"{f['max_drawdown']:>6.1f}% | {f['total_return_pct']:>+6.1f}%"
        )

    # Khuyen nghi
    wr = s.get("win_rate", 0)
    sh = s.get("sharpe", 0)
    print("\n  DANH GIA:")
    if wr >= 55 and sh >= 0.7:
        print("  -> He thong PASS: San sang cho von that hoac giay lon.")
    elif wr >= 52:
        print("  -> He thong TRUNG BINH: Xem xet tang trong so Shark Flow len 45%.")
    else:
        print("  -> He thong CAN CALI: Tang nguong MUA GOM len 80 diem.")
    print("="*60 + "\n")


async def main_async(args):
    if args.basket == "VN30":
        symbols = VN30
    elif args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        print("Loi: Phai chi dinh --symbols hoac --basket")
        sys.exit(1)

    print(f"\nDang chay Walk-Forward Backtest cho {len(symbols)} ma...")
    print(f"Thoi gian: {args.start} -> {args.end}")
    print(f"Nguong diem: {args.score_thresh} | Stop: {args.stop_pct}% | Target: {args.target_pct}%\n")

    from src.backtest.walk_forward import WalkForwardBacktester

    bt = WalkForwardBacktester(
        score_thresh=args.score_thresh,
        stop_pct=args.stop_pct,
        target_pct=args.target_pct,
        hold_days=args.hold_days,
    )

    result = await bt.run(
        symbols=symbols,
        start_date=args.start,
        end_date=args.end,
        db_session=None,   # Fallback sang vnstock VCI
    )

    if "error" in result:
        print(f"Loi: {result['error']}")
        sys.exit(1)

    print_summary(result)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"Da luu ket qua ra: {args.out}")


def main():
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
