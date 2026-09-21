"""
Data Fetching Module

This module handles all stock data fetching and updates.
Contains functionality for:
- Real-time stock price fetching
- Historical data fetching (2020-2024)
- Latest data fetching (2025-current)
- Market data updates
- Data caching and storage
- Multiple API fallbacks (yfinance, Finnhub, Alpha Vantage)
"""

try:
    from .current_fetcher import CurrentFetcher, LiveFetcher
except ImportError:
    from current_fetcher import CurrentFetcher, LiveFetcher

# For backward compatibility
__all__ = ['CurrentFetcher', 'LiveFetcher']
