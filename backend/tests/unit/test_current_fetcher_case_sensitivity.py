"""
Unit tests for case-sensitivity handling in CurrentFetcher.
Tests cover metadata lookup, cache normalization, CSV deduplication,
and file operations for lowercase and mixed-case stock symbols.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime
import pandas as pd

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from data_fetching.current_fetcher import CurrentFetcher


class TestCurrentFetcherCaseSensitivity(unittest.TestCase):
    """Test suite for case-sensitivity handling in CurrentFetcher."""

    def setUp(self):
        self.fetcher = CurrentFetcher()
        self.fetcher.cache = {}

    def test_get_stock_metadata_case_insensitive_pandas(self):
        """Verify _get_stock_metadata returns correct data regardless of symbol casing."""
        # Using real index file in permanent/us_stocks/index_us_stocks.csv (e.g. AAPL)
        upper_meta = self.fetcher._get_stock_metadata("AAPL")
        lower_meta = self.fetcher._get_stock_metadata("aapl")
        mixed_meta = self.fetcher._get_stock_metadata("AaPl")

        self.assertNotEqual(upper_meta['sector'], 'N/A')
        self.assertEqual(lower_meta['sector'], upper_meta['sector'])
        self.assertEqual(mixed_meta['sector'], upper_meta['sector'])
        self.assertEqual(lower_meta['exchange'], upper_meta['exchange'])

    def test_get_stock_metadata_csv_fallback(self):
        """Verify _get_stock_metadata works with CSV fallback when pandas is disabled."""
        with patch('data_fetching.current_fetcher.PANDAS_AVAILABLE', False):
            upper_meta = self.fetcher._get_stock_metadata("AAPL")
            lower_meta = self.fetcher._get_stock_metadata("aapl")
            mixed_meta = self.fetcher._get_stock_metadata("aApL")

            self.assertNotEqual(upper_meta['sector'], 'N/A')
            self.assertEqual(lower_meta['sector'], upper_meta['sector'])
            self.assertEqual(mixed_meta['sector'], upper_meta['sector'])

    def test_cache_normalization(self):
        """Verify cache keys are normalized so lowercase lookups hit uppercase cached entries."""
        mock_data = {
            'symbol': 'AAPL',
            'price': 150.0,
            'timestamp': datetime.now().isoformat(),
            'source': 'test'
        }
        self.fetcher.cache['AAPL'] = {
            'data': mock_data,
            'timestamp': datetime.now()
        }

        self.assertTrue(self.fetcher._is_cache_valid('AAPL'))
        self.assertTrue(self.fetcher._is_cache_valid('aapl'))
        self.assertTrue(self.fetcher._is_cache_valid('AaPl'))
        self.assertFalse(self.fetcher._is_cache_valid('MSFT'))

    def test_fetch_from_permanent_directory_case_insensitive(self):
        """Verify _fetch_from_permanent_directory resolves individual files and index info for lowercase symbols."""
        price_upper, name_upper, date_upper = self.fetcher._fetch_from_permanent_directory("AAPL")
        price_lower, name_lower, date_lower = self.fetcher._fetch_from_permanent_directory("aapl")

        self.assertEqual(price_upper, price_lower)
        self.assertEqual(name_upper, name_lower)
        self.assertEqual(date_upper, date_lower)

    def test_save_with_pandas_deduplication(self):
        """Verify _save_with_pandas prevents duplicate rows when case differs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "latest_prices.csv")
            
            # Initial save with uppercase
            data_upper = {
                'symbol': 'AAPL',
                'price': 150.0,
                'timestamp': '2026-09-20T00:00:00',
                'source': 'finnhub',
                'company_name': 'Apple Inc.',
                'sector': 'Technology'
            }
            with patch.object(self.fetcher, 'save_daily_data'):
                with patch.object(self.fetcher, 'update_dynamic_index'):
                    self.fetcher._save_with_pandas(data_upper, csv_path, 'AAPL', 'us_stocks')
                    
                    df1 = pd.read_csv(csv_path)
                    self.assertEqual(len(df1), 1)
                    self.assertEqual(df1.iloc[0]['symbol'], 'AAPL')
                    self.assertEqual(df1.iloc[0]['price'], 150.0)

                    # Second save with lowercase symbol
                    data_lower = {
                        'symbol': 'aapl',
                        'price': 155.0,
                        'timestamp': '2026-09-20T01:00:00',
                        'source': 'finnhub',
                        'company_name': 'Apple Inc.',
                        'sector': 'Technology'
                    }
                    self.fetcher._save_with_pandas(data_lower, csv_path, 'aapl', 'us_stocks')

                    df2 = pd.read_csv(csv_path)
                    # Must have deduplicated AAPL/aapl to 1 row
                    self.assertEqual(len(df2), 1)
                    self.assertEqual(df2.iloc[0]['symbol'], 'AAPL')
                    self.assertEqual(df2.iloc[0]['price'], 155.0)

    def test_save_with_csv_module_deduplication(self):
        """Verify _save_with_csv_module prevents duplicate rows when case differs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "latest_prices.csv")
            
            data_upper = {
                'symbol': 'AAPL',
                'price': 150.0,
                'timestamp': '2026-09-20T00:00:00',
                'source': 'finnhub',
                'company_name': 'Apple Inc.',
                'sector': 'Technology'
            }
            with patch.object(self.fetcher, 'save_daily_data'):
                with patch.object(self.fetcher, 'update_dynamic_index'):
                    self.fetcher._save_with_csv_module(data_upper, csv_path, 'AAPL', 'us_stocks')
                    
                    # Update with lowercase symbol
                    data_lower = {
                        'symbol': 'aapl',
                        'price': 160.0,
                        'timestamp': '2026-09-20T02:00:00',
                        'source': 'finnhub',
                        'company_name': 'Apple Inc.',
                        'sector': 'Technology'
                    }
                    self.fetcher._save_with_csv_module(data_lower, csv_path, 'aapl', 'us_stocks')

                    import csv
                    with open(csv_path, 'r', newline='', encoding='utf-8') as f:
                        reader = list(csv.DictReader(f))
                        self.assertEqual(len(reader), 1)
                        self.assertEqual(reader[0]['symbol'], 'AAPL')
                        self.assertEqual(float(reader[0]['price']), 160.0)

    def test_save_daily_data_filename_normalization(self):
        """Verify save_daily_data writes to uppercase {SYMBOL}.csv even if lowercase provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self.fetcher.latest_dir = tmpdir
            ohlcv = {
                'open': 100,
                'high': 110,
                'low': 95,
                'close': 105,
                'volume': 1000
            }
            with patch.object(self.fetcher, 'update_dynamic_index'):
                self.fetcher.save_daily_data('msft', ohlcv, 'us_stocks')
                
                expected_file = os.path.join(tmpdir, 'us_stocks', 'individual_files', 'MSFT.csv')
                self.assertTrue(os.path.exists(expected_file))

    def test_fetch_live_price_lowercase_end_to_end(self):
        """Verify fetch_live_price normalizes lowercase input to uppercase and populates metadata."""
        with patch.object(self.fetcher, 'save_to_csv'):
            result = self.fetcher.fetch_live_price('aapl')
            self.assertEqual(result['symbol'], 'AAPL')
            self.assertNotEqual(result['sector'], 'N/A')
            self.assertEqual(result['company_name'], 'Apple')

    def test_fetch_live_price_caching_across_cases(self):
        """Verify fetching lowercase symbol populates cache and subsequent uppercase fetch hits cache."""
        with patch.object(self.fetcher, 'save_to_csv'):
            res1 = self.fetcher.fetch_live_price('aapl')
            self.assertIn('AAPL', self.fetcher.cache)
            res2 = self.fetcher.fetch_live_price('AAPL')
            self.assertEqual(res1['timestamp'], res2['timestamp'])
            self.assertEqual(res1['price'], res2['price'])

    def test_indian_stock_lowercase_metadata(self):
        """Verify Indian stock symbols in lowercase resolve metadata correctly."""
        meta = self.fetcher._get_stock_metadata('reliance')
        self.assertNotEqual(meta['sector'], 'N/A')
        self.assertEqual(meta['exchange'], 'NSE')


if __name__ == '__main__':
    unittest.main()
