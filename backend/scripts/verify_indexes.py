#!/usr/bin/env python3
"""
Verify Dynamic Indexes

This script verifies that both US and Indian dynamic indexes are properly populated.
"""

import pandas as pd
import os
from pathlib import Path

def verify_indexes():
    """Verify both dynamic indexes"""
    print("=" * 60)
    print("VERIFYING DYNAMIC INDEXES")
    print("=" * 60)
    
    # Absolute data directory path resolution relative to script location
    script_dir = Path(__file__).resolve().parent
    base_dir = script_dir.parent.parent
    data_dir = base_dir / 'data'
    
    # Check US Dynamic Index
    us_path = data_dir / 'index_us_stocks_dynamic.csv'
    if us_path.exists():
        try:
            us_df = pd.read_csv(us_path)
            print("📊 US Dynamic Index:")
            print(f"   Total stocks: {len(us_df)}")
            if 'symbol' in us_df.columns:
                print(f"   Sample symbols: {us_df['symbol'].head(3).tolist()}")
            print(f"   Columns: {us_df.columns.tolist()}")
        except Exception as e:
            print(f"❌ Error reading US Dynamic Index: {e}")
    else:
        print(f"❌ US Dynamic Index not found ({us_path})")
    
    print()
    
    # Check Indian Dynamic Index
    ind_path = data_dir / 'index_ind_stocks_dynamic.csv'
    if ind_path.exists():
        try:
            ind_df = pd.read_csv(ind_path)
            print("📊 Indian Dynamic Index:")
            print(f"   Total stocks: {len(ind_df)}")
            
            if 'isin' in ind_df.columns and len(ind_df) > 0:
                # Safely handle null / non-string ISIN values
                stocks_with_isin = ind_df[ind_df['isin'].fillna('').astype(str).str.strip().str.len() > 0]
                coverage_pct = (len(stocks_with_isin) / len(ind_df)) * 100
                print(f"   Stocks with ISIN: {len(stocks_with_isin)}")
                print(f"   ISIN coverage: {coverage_pct:.1f}%")
                
                if len(stocks_with_isin) > 0 and 'symbol' in ind_df.columns:
                    print("   Sample with ISIN:")
                    for _, row in stocks_with_isin.head(5).iterrows():
                        print(f"     {row['symbol']}: {row['isin']}")
            else:
                print("   ISIN column: Not present or empty dataframe")
                
            print(f"   Columns: {ind_df.columns.tolist()}")
        except Exception as e:
            print(f"❌ Error reading Indian Dynamic Index: {e}")
    else:
        print(f"❌ Indian Dynamic Index not found ({ind_path})")
    
    print()
    print("✅ Verification complete!")

if __name__ == "__main__":
    verify_indexes()
