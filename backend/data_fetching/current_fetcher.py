"""
Current Stock Price Fetcher

Main fetcher for current live stock prices with multiple API fallbacks.
Maintains all existing functionality while working with the new data_fetching structure.
"""

import os
import requests
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, Any
import logging
import time
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Import shared utilities
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from shared.utilities import Config, Constants, categorize_stock, get_currency_for_category

import csv
# Try to import pandas, fallback to CSV module if not available
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CurrentFetcher:
    """
    Current stock price fetcher with multiple API fallbacks:
    1. Finnhub (primary for US stocks, requires API key)
    2. Upstox (primary for Indian stocks, requires OAuth)
    3. Permanent directory (fallback, historical data)
    
    Note: yfinance removed from real-time fetching as it only provides delayed data (15+ min).
    yfinance is still used for historical data fetching where appropriate.
    
    This maintains all existing functionality while working with the new structure.
    """
    
    def __init__(self):
        # Use shared configuration
        self.config = Config()
        self.data_dir = self.config.data_dir
        self.latest_dir = os.path.join(self.data_dir, 'latest')
        
        # Ensure directories exist
        self._ensure_directories()
        
        # API configurations
        self.finnhub_api_key = self.config.finnhub_api_key
        
        # Cache configuration
        self.cache_duration = self.config.cache_duration
        self.min_request_delay = self.config.min_request_delay
        self.cache = {}  # {symbol: {data: dict, timestamp: datetime}}
        self.last_request_time = 0  # Track last API request time
        
        # Stock categorization rules
        self.us_stock_suffixes = ['.US']
        self.indian_stock_suffixes = ['.NS', '.BO']
        
    def _ensure_directories(self):
        """Ensure all required directories exist"""
        directories = [
            self.latest_dir,
            os.path.join(self.latest_dir, 'us_stocks'),
            os.path.join(self.latest_dir, 'ind_stocks')
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
    
    def _categorize_stock(self, symbol: str) -> str:
        """Categorize stock based on symbol suffix"""
        if symbol:
            symbol = symbol.strip().upper()
        return categorize_stock(symbol)
    
    def _fetch_from_finnhub(self, symbol: str) -> Tuple[float, str, None]:
        """Fetch stock price from Finnhub API (live data, no date)"""
        if symbol:
            symbol = symbol.strip().upper()
        if not self.finnhub_api_key:
            raise ValueError("Finnhub API key not configured")
        
        try:
            url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={self.finnhub_api_key}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if 'c' in data and data['c'] is not None:
                price = data['c']
                # Get company name
                profile_url = f"https://finnhub.io/api/v1/stock/profile2?symbol={symbol}&token={self.finnhub_api_key}"
                profile_response = requests.get(profile_url, timeout=10)
                
                company_name = symbol
                if profile_response.status_code == 200:
                    profile_data = profile_response.json()
                    company_name = profile_data.get('name', symbol)
                
                return float(price), company_name, None  # None for live data (no historical date)
            else:
                raise ValueError(f"No price data available for {symbol}")
                
        except Exception as e:
            logger.error(f"Finnhub error for {symbol}: {str(e)}")
            raise
    
    
    def _get_stock_metadata(self, symbol: str) -> Dict[str, str]:
        """
        Get stock metadata (sector, market_cap, headquarters, exchange) from index CSV files.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dict with metadata fields, or 'N/A' for missing fields
        """
        try:
            if not symbol or not str(symbol).strip():
                return {
                    'sector': 'N/A',
                    'market_cap': 'N/A',
                    'headquarters': 'N/A',
                    'exchange': 'N/A'
                }
            
            symbol = symbol.strip().upper()
            
            # Determine category and check permanent directory
            category = self._categorize_stock(symbol)
            
            # Map category to permanent directory path
            permanent_mapping = {
                'us_stocks': 'us_stocks',
                'ind_stocks': 'ind_stocks'
            }
            
            permanent_category = permanent_mapping.get(category, 'us_stocks')
            
            # Check permanent index file
            index_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                'permanent', permanent_category, f'index_{permanent_category}.csv'
            )
            
            if not os.path.exists(index_path):
                logger.warning(f"Index file not found: {index_path}")
                return {
                    'sector': 'N/A',
                    'market_cap': 'N/A',
                    'headquarters': 'N/A',
                    'exchange': 'N/A'
                }
            
            # Read metadata from index file
            if PANDAS_AVAILABLE:
                df = pd.read_csv(index_path)
                if 'symbol' in df.columns:
                    symbol_row = df[df['symbol'].dropna().astype(str).str.strip().str.upper() == symbol]
                else:
                    symbol_row = pd.DataFrame()
                if not symbol_row.empty:
                    row = symbol_row.iloc[0]
                    return {
                        'sector': self._clean_metadata_value(str(row.get('sector', 'N/A'))),
                        'market_cap': self._clean_metadata_value(str(row.get('market_cap', 'N/A'))),
                        'headquarters': self._clean_metadata_value(str(row.get('headquarters', 'N/A'))),
                        'exchange': self._clean_metadata_value(str(row.get('exchange', 'N/A')))
                    }
            else:
                # Fallback to csv module
                import csv
                with open(index_path, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        row_symbol = next((v for k, v in row.items() if k and k.strip().lower() == 'symbol'), row.get('symbol', ''))
                        if row_symbol and str(row_symbol).strip().upper() == symbol:
                            return {
                                'sector': self._clean_metadata_value(row.get('sector', 'N/A')),
                                'market_cap': self._clean_metadata_value(row.get('market_cap', 'N/A')),
                                'headquarters': self._clean_metadata_value(row.get('headquarters', 'N/A')),
                                'exchange': self._clean_metadata_value(row.get('exchange', 'N/A'))
                            }
            
            # Symbol not found in index
            logger.warning(f"Symbol {symbol} not found in index file: {index_path}")
            return {
                'sector': 'N/A',
                'market_cap': 'N/A',
                'headquarters': 'N/A',
                'exchange': 'N/A'
            }
            
        except Exception as e:
            logger.error(f"Error fetching metadata for {symbol}: {str(e)}")
            return {
                'sector': 'N/A',
                'market_cap': 'N/A',
                'headquarters': 'N/A',
                'exchange': 'N/A'
            }
    
    def _clean_metadata_value(self, value: str) -> str:
        """
        Clean metadata value by handling empty strings, NaN, and whitespace.
        
        Args:
            value: Raw value from CSV
            
        Returns:
            Cleaned value or 'N/A' if empty/invalid
        """
        if not value or value.strip() == '' or value.lower() in ['nan', 'none', 'null']:
            return 'N/A'
        return value.strip()

    def _fetch_from_permanent_directory(self, symbol: str) -> Tuple[float, str]:
        """
        Fetch stock price from permanent directory as fallback.
        Checks both US and Indian stock directories.
        """
        try:
            if not symbol or not str(symbol).strip():
                raise ValueError("Stock symbol is required")
            
            symbol = symbol.strip().upper()
            
            # Determine category and check permanent directory
            category = self._categorize_stock(symbol)
            
            # Map category to permanent directory path
            permanent_mapping = {
                'us_stocks': 'us_stocks',
                'ind_stocks': 'ind_stocks'
            }
            
            permanent_category = permanent_mapping.get(category, 'us_stocks')
            
            # Check permanent index file first (use absolute path from config)
            index_path = self.config.get_permanent_path(
                permanent_category, f'index_{permanent_category}.csv'
            )
            
            if not os.path.exists(index_path):
                raise ValueError(f"Permanent index file not found: {index_path}")
            
            # Read index file to get company info
            company_name = symbol
            if PANDAS_AVAILABLE:
                df = pd.read_csv(index_path)
                if 'symbol' in df.columns:
                    symbol_row = df[df['symbol'].dropna().astype(str).str.strip().str.upper() == symbol]
                else:
                    symbol_row = pd.DataFrame()
                if not symbol_row.empty:
                    company_name = symbol_row.iloc[0]['company_name']
            else:
                # Fallback to csv module
                import csv
                with open(index_path, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        row_symbol = next((v for k, v in row.items() if k and k.strip().lower() == 'symbol'), row.get('symbol', ''))
                        if row_symbol and str(row_symbol).strip().upper() == symbol:
                            company_name = row.get('company_name', symbol)
                            break
            
            # Check individual file (use absolute path from config)
            individual_path = self.config.get_permanent_path(
                permanent_category, 'individual_files', f'{symbol}.csv'
            )
            
            if not os.path.exists(individual_path):
                raise ValueError(f"Permanent individual file not found: {individual_path}")
            
            # Read the most recent price from CSV
            # All files now use unified lowercase format (fixed case inconsistencies)
            if PANDAS_AVAILABLE:
                df = pd.read_csv(individual_path)
                if df.empty:
                    raise ValueError(f"No data in permanent file for {symbol}")
                
                # Check for both lowercase and titlecase columns for compatibility
                if 'close' in df.columns:
                    price = df['close'].iloc[-1]
                elif 'Close' in df.columns:
                    price = df['Close'].iloc[-1]
                else:
                    raise ValueError(f"Missing 'close' or 'Close' column in permanent file for {symbol}")
                
                # Get the date of last data point
                if 'date' in df.columns:
                    last_date = str(df['date'].iloc[-1])
                elif 'Date' in df.columns:
                    last_date = str(df['Date'].iloc[-1])
                else:
                    last_date = 'unknown'
            else:
                # Fallback to csv module
                import csv
                rows = []
                with open(individual_path, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                
                if not rows:
                    raise ValueError(f"No data in permanent file for {symbol}")
                
                # Get last row
                last_row = rows[-1]
                if 'close' in last_row:
                    price = float(last_row['close'])
                elif 'Close' in last_row:
                    price = float(last_row['Close'])
                else:
                    raise ValueError(f"Missing 'close' or 'Close' column in permanent file for {symbol}")
                
                # Get date from last row
                last_date = last_row.get('date', last_row.get('Date', 'unknown'))
            
            logger.info(f"✅ Fetched {symbol} from permanent directory (READ-ONLY fallback): ${price} from {last_date}")
            return float(price), company_name, last_date
            
        except Exception as e:
            logger.error(f"Permanent directory error for {symbol}: {str(e)}")
            raise
    
    def _is_cache_valid(self, symbol: str) -> bool:
        """Check if cached data for symbol is still valid"""
        if not symbol or not str(symbol).strip():
            return False
        
        symbol = symbol.strip().upper()
        if symbol not in self.cache:
            return False
        
        cache_entry = self.cache[symbol]
        cache_time = cache_entry['timestamp']
        
        # Check if cache is still within duration
        return datetime.now() - cache_time < timedelta(seconds=self.cache_duration)
    
    def _enforce_rate_limit(self):
        """Enforce minimum delay between API requests"""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        
        if time_since_last_request < self.min_request_delay:
            sleep_time = self.min_request_delay - time_since_last_request
            logger.info(f"Rate limiting: sleeping for {sleep_time:.2f} seconds")
            time.sleep(sleep_time)
        
        self.last_request_time = time.time()
    
    def fetch_live_price(self, symbol: str) -> Dict:
        """Fetch live stock price using fallback strategy with caching"""
        if not symbol or not symbol.strip():
            raise ValueError("Stock symbol is required")
        
        symbol = symbol.strip().upper()
        
        # Check cache first
        if self._is_cache_valid(symbol):
            cached_data = self.cache[symbol]['data']
            logger.info(f"Returning cached data for {symbol} (age: {(datetime.now() - self.cache[symbol]['timestamp']).seconds}s)")
            return cached_data
        
        timestamp = datetime.now().isoformat()
        
        # Try APIs in order of preference
        apis = [
            ('finnhub', self._fetch_from_finnhub),
            ('permanent_directory', self._fetch_from_permanent_directory)
        ]
        
        last_error = None
        
        for api_name, api_func in apis:
            try:
                logger.info(f"Trying {api_name} for symbol {symbol}")
                price, company_name, data_date = api_func(symbol)
                
                # Get currency for the category
                category = self._categorize_stock(symbol)
                currency = get_currency_for_category(category)
                
                # Get additional metadata from index files
                metadata = self._get_stock_metadata(symbol)
                
                # Get additional data from latest CSV files
                additional_data = self._get_latest_day_data(symbol)
                
                result = {
                    'symbol': symbol,
                    'price': price,
                    'timestamp': timestamp,
                    'source': api_name,
                    'source_reliable': api_name == 'finnhub',  # Indicate if real-time
                    'data_date': data_date,  # Date of data (None for live, date for permanent)
                    'company_name': company_name,
                    'currency': currency,
                    'sector': metadata['sector'],
                    'market_cap': metadata['market_cap'],
                    'headquarters': metadata['headquarters'],
                    'exchange': metadata['exchange'],
                    'open': additional_data.get('open'),
                    'high': additional_data.get('high'),
                    'low': additional_data.get('low'),
                    'volume': additional_data.get('volume'),
                    'close': additional_data.get('close')
                }
                
                # Cache the result
                self.cache[symbol] = {
                    'data': result,
                    'timestamp': datetime.now()
                }
                
                # Save to CSV
                self.save_to_csv(result)
                
                logger.info(f"Successfully fetched {symbol} price ${price} from {api_name}")
                return result
                
            except Exception as e:
                last_error = e
                logger.warning(f"{api_name} failed for {symbol}: {str(e)}")
                continue
        
        # All APIs failed - provide better error message
        error_msg = f"Unable to fetch price for {symbol}."
        if "timed out" in str(last_error).lower():
            error_msg += " Request timed out - try again."
        elif "No data" in str(last_error):
            error_msg += " Symbol may not exist or market is closed."
        else:
            error_msg += f" All sources failed. Last error: {str(last_error)}"
        raise Exception(error_msg)
    
    def save_to_csv(self, data: Dict):
        """Save stock data to individual files only (latest_prices.csv disabled)"""
        symbol = str(data.get('symbol', '')).strip().upper()
        data['symbol'] = symbol
        category = self._categorize_stock(symbol)
        
        # Only save to individual files, not latest_prices.csv
        try:
            self.save_daily_data(symbol, data, category)
            logger.info(f"Saved {symbol} data to individual file")
            
        except Exception as e:
            logger.error(f"Error saving to individual file for {symbol}: {str(e)}")
            # Don't raise exception to avoid breaking the main flow
    
    def _save_with_pandas(self, data: Dict, csv_path: str, symbol: str, category: str):
        """Save using pandas"""
        if symbol:
            symbol = symbol.strip().upper()
        # Create DataFrame with the new data
        new_row = pd.DataFrame([{
            'symbol': symbol,
            'price': data['price'],
            'timestamp': data['timestamp'],
            'source': data['source'],
            'company_name': data['company_name'],
            'currency': data.get('currency', get_currency_for_category(category)),
            'sector': data.get('sector', 'N/A'),
            'market_cap': data.get('market_cap', 'N/A'),
            'headquarters': data.get('headquarters', 'N/A'),
            'exchange': data.get('exchange', 'N/A')
        }])
        
        # Read existing data if file exists
        if os.path.exists(csv_path):
            existing_df = pd.read_csv(csv_path)
            # Remove any existing entry for this symbol (case-insensitive)
            if 'symbol' in existing_df.columns:
                existing_df = existing_df[existing_df['symbol'].dropna().astype(str).str.strip().str.upper() != symbol]
            # Append new data
            updated_df = pd.concat([existing_df, new_row], ignore_index=True)
        else:
            updated_df = new_row
        
        # Save updated data
        updated_df.to_csv(csv_path, index=False)
        
        # Update dynamic index
        self.update_dynamic_index(category)
        
        # Save OHLCV data to individual file
        try:
            self.save_daily_data(symbol, data, category)
            logger.info(f"✓ Saved OHLCV data for {symbol} to individual file")
        except Exception as e:
            logger.warning(f"Could not save daily data for {symbol}: {e}")
    
    def _save_with_csv_module(self, data: Dict, csv_path: str, symbol: str, category: str):
        """Save using built-in csv module (fallback)"""
        if symbol:
            symbol = symbol.strip().upper()
        # Read existing data
        existing_data = []
        if os.path.exists(csv_path):
            with open(csv_path, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row_symbol = next((v for k, v in row.items() if k and k.strip().lower() == 'symbol'), row.get('symbol', ''))
                    if str(row_symbol).strip().upper() != symbol:
                        existing_data.append(row)
        
        # Add new data
        existing_data.append({
            'symbol': symbol,
            'price': str(data['price']),
            'timestamp': data['timestamp'],
            'source': data['source'],
            'company_name': data['company_name'],
            'currency': data.get('currency', get_currency_for_category(category)),
            'sector': data.get('sector', 'N/A'),
            'market_cap': data.get('market_cap', 'N/A'),
            'headquarters': data.get('headquarters', 'N/A'),
            'exchange': data.get('exchange', 'N/A')
        })
        
        # Write updated data
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['symbol', 'price', 'timestamp', 'source', 'company_name', 'currency', 'sector', 'market_cap', 'headquarters', 'exchange']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(existing_data)
        
        # Update dynamic index
        self.update_dynamic_index(category)
        
        # Save OHLCV data to individual file
        try:
            self.save_daily_data(symbol, data, category)
            logger.info(f"✓ Saved OHLCV data for {symbol} to individual file")
        except Exception as e:
            logger.warning(f"Could not save daily data for {symbol}: {e}")
    
    def update_dynamic_index(self, category: str):
        """Update the dynamic index CSV file for the category with company info using DynamicIndexManager"""
        try:
            from shared.index_manager import DynamicIndexManager
            index_manager = DynamicIndexManager(self.data_dir)
            
            csv_path = os.path.join(self.latest_dir, category, 'latest_prices.csv')
            
            if os.path.exists(csv_path):
                if PANDAS_AVAILABLE:
                    df = pd.read_csv(csv_path)
                    symbols = [str(s).strip().upper() for s in df['symbol'].dropna().unique().tolist() if str(s).strip()]
                    
                    # Try to get company info from permanent index
                    permanent_index_path = os.path.join(self.config.permanent_dir, category, f'index_{category}.csv')
                    company_info = {}
                    
                    if os.path.exists(permanent_index_path):
                        try:
                            permanent_df = pd.read_csv(permanent_index_path)
                            if 'symbol' in permanent_df.columns:
                                permanent_df['symbol'] = permanent_df['symbol'].dropna().astype(str).str.strip().str.upper()
                                company_info = permanent_df.set_index('symbol').to_dict('index')
                        except Exception as e:
                            logger.warning(f"Could not read permanent index for {category}: {e}")
                    
                    # Add each symbol to dynamic index (preserves existing stocks)
                    for symbol in symbols:
                        if not index_manager.stock_exists(symbol, category):
                            if symbol in company_info:
                                # Use info from permanent index
                                info = company_info[symbol]
                                stock_info = {
                                    'company_name': info.get('company_name', symbol),
                                    'sector': info.get('sector', 'Unknown'),
                                    'market_cap': info.get('market_cap', ''),
                                    'headquarters': info.get('headquarters', 'Unknown'),
                                    'exchange': info.get('exchange', 'Unknown')
                                }
                            else:
                                # Use basic info
                                stock_info = {
                                    'company_name': symbol,
                                    'sector': 'Unknown',
                                    'market_cap': '',
                                    'headquarters': 'Unknown',
                                    'exchange': 'Unknown'
                                }
                            
                            index_manager.add_stock(symbol, stock_info, category)
                else:
                    # Use csv module fallback
                    symbols = set()
                    with open(csv_path, 'r', newline='', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            row_symbol = next((v for k, v in row.items() if k and k.strip().lower() == 'symbol'), row.get('symbol', ''))
                            if row_symbol and str(row_symbol).strip():
                                symbols.add(str(row_symbol).strip().upper())
                    
                    # Add each symbol to dynamic index (preserves existing stocks)
                    for symbol in symbols:
                        if not index_manager.stock_exists(symbol, category):
                            stock_info = {
                                'company_name': symbol,
                                'sector': 'Unknown',
                                'market_cap': '',
                                'headquarters': 'Unknown',
                                'exchange': 'Unknown'
                            }
                            index_manager.add_stock(symbol, stock_info, category)
                
                logger.info(f"Updated index for {category} with {len(symbols)} symbols")
            else:
                logger.info(f"No latest prices file found for {category}, skipping dynamic index update")
                
        except Exception as e:
            logger.error(f"Error updating index for {category}: {str(e)}")
    
    def get_latest_prices(self, category: Optional[str] = None):
        """Get latest prices for a category or all categories by reading individual files"""
        if not PANDAS_AVAILABLE:
            logger.warning("Pandas not available, returning empty list")
            return []
        
        all_data = []
        
        if category:
            categories = [category]
        else:
            categories = ['us_stocks', 'ind_stocks']
        
        for cat in categories:
            individual_dir = os.path.join(self.latest_dir, cat, 'individual_files')
            if not os.path.exists(individual_dir):
                continue
                
            # Get all individual files in the directory
            for filename in os.listdir(individual_dir):
                if filename.endswith('.csv'):
                    symbol = filename[:-4].strip().upper()  # Remove .csv extension and normalize
                    file_path = os.path.join(individual_dir, filename)
                    
                    try:
                        # Read the individual file
                        df = pd.read_csv(file_path)
                        if df.empty:
                            continue
                        
                        # Get the latest row (last row)
                        latest_row = df.iloc[-1]
                        
                        # Create a row with the latest price data
                        latest_data = {
                            'symbol': symbol,
                            'price': latest_row.get('close', latest_row.get('price', 0)),
                            'timestamp': latest_row.get('date', ''),
                            'source': 'individual_file',
                            'company_name': symbol,  # Will be updated from dynamic index if available
                            'currency': latest_row.get('currency', get_currency_for_category(cat)),
                            'category': cat
                        }
                        
                        all_data.append(latest_data)
                        
                    except Exception as e:
                        logger.warning(f"Error reading individual file {filename}: {e}")
                        continue
        
        if all_data:
            return pd.DataFrame(all_data)
        else:
            return pd.DataFrame()
    
    def _get_latest_day_data(self, symbol: str) -> Dict:
        """
        Get the latest day's open, high, low, volume data from CSV files.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dict with additional data fields
        """
        try:
            if not symbol or not str(symbol).strip():
                return {}
            
            symbol = symbol.strip().upper()
            category = self._categorize_stock(symbol)
            
            # Try latest directory first (2025 data)
            latest_path = os.path.join(
                self.config.get_data_path('latest', category, 'individual_files', f'{symbol}.csv')
            )
            
            # Fallback to permanent directory if latest not available
            permanent_path = os.path.join(
                self.config.get_permanent_path(category, 'individual_files', f'{symbol}.csv')
            )
            
            csv_path = None
            if os.path.exists(latest_path):
                csv_path = latest_path
            elif os.path.exists(permanent_path):
                csv_path = permanent_path
            
            if not csv_path:
                logger.debug(f"No CSV file found for {symbol}")
                return {}
            
            # Read the latest row from CSV
            if PANDAS_AVAILABLE:
                try:
                    df = pd.read_csv(csv_path)
                    if df.empty:
                        return {}
                    
                    # Get the most recent row
                    latest_row = df.iloc[-1]
                    
                    return {
                        'open': float(latest_row['open']) if 'open' in latest_row and pd.notna(latest_row['open']) else None,
                        'high': float(latest_row['high']) if 'high' in latest_row and pd.notna(latest_row['high']) else None,
                        'low': float(latest_row['low']) if 'low' in latest_row and pd.notna(latest_row['low']) else None,
                        'volume': int(latest_row['volume']) if 'volume' in latest_row and pd.notna(latest_row['volume']) else None,
                        'close': float(latest_row['close']) if 'close' in latest_row and pd.notna(latest_row['close']) else None
                    }
                except Exception as e:
                    logger.debug(f"Error reading CSV with pandas for {symbol}: {e}")
            
            # Fallback to csv module
            import csv
            rows = []
            with open(csv_path, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            
            if not rows:
                return {}
            
            # Get the last row
            latest_row = rows[-1]
            
            return {
                'open': float(latest_row.get('open', 0)) if latest_row.get('open') else None,
                'high': float(latest_row.get('high', 0)) if latest_row.get('high') else None,
                'low': float(latest_row.get('low', 0)) if latest_row.get('low') else None,
                'volume': int(latest_row.get('volume', 0)) if latest_row.get('volume') else None,
                'close': float(latest_row.get('close', 0)) if latest_row.get('close') else None
            }
            
        except Exception as e:
            logger.debug(f"Error getting latest day data for {symbol}: {e}")
            return {}
    
    def save_daily_data(self, symbol: str, ohlcv_data: Dict[str, Any], category: str = None):
        """
        Append today's OHLCV data to individual stock file in latest directory.
        Only saves if data for today doesn't already exist.
        """
        try:
            from datetime import datetime
            
            if not symbol or not str(symbol).strip():
                return
            
            symbol = symbol.strip().upper()
            
            # Determine category if not provided
            if not category:
                category = self._categorize_stock(symbol)
            
            # Path to individual file in latest directory
            individual_file = os.path.join(
                self.latest_dir, category, 'individual_files', f'{symbol}.csv'
            )
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(individual_file), exist_ok=True)
            
            # Today's date
            today = datetime.now().strftime('%Y-%m-%d')
            
            # Check if file exists and read it
            if os.path.exists(individual_file):
                if PANDAS_AVAILABLE:
                    df = pd.read_csv(individual_file)
                    # Check if today's data already exists
                    if 'date' in df.columns and today in df['date'].values:
                        logger.debug(f"Today's data already exists for {symbol}, skipping")
                        return
                else:
                    # Use csv module fallback
                    with open(individual_file, 'r', newline='', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        existing_data = list(reader)
                        if any(row.get('date') == today for row in existing_data):
                            logger.debug(f"Today's data already exists for {symbol}, skipping")
                            return
            else:
                # Create new DataFrame with proper columns
                if PANDAS_AVAILABLE:
                    df = pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume', 'adjusted_close', 'currency'])
                else:
                    # Initialize empty list for csv module
                    existing_data = []
            
            # Get currency for category
            currency = get_currency_for_category(category)
            
            # Add new row for today
            new_row = {
                'date': today,
                'open': ohlcv_data.get('open', ohlcv_data.get('price', 0)),
                'high': ohlcv_data.get('high', ohlcv_data.get('price', 0)),
                'low': ohlcv_data.get('low', ohlcv_data.get('price', 0)),
                'close': ohlcv_data.get('close', ohlcv_data.get('price', 0)),
                'volume': ohlcv_data.get('volume', 0),
                'adjusted_close': ohlcv_data.get('adjusted_close', ''),
                'currency': currency
            }
            
            if PANDAS_AVAILABLE:
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                # Sort by date and save
                df = df.sort_values('date').reset_index(drop=True)
                df.to_csv(individual_file, index=False)
            else:
                # Use csv module fallback
                existing_data.append(new_row)
                # Sort by date
                existing_data.sort(key=lambda x: x.get('date', ''))
                
                # Write updated data
                with open(individual_file, 'w', newline='', encoding='utf-8') as f:
                    fieldnames = ['date', 'open', 'high', 'low', 'close', 'volume', 'adjusted_close', 'currency']
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(existing_data)
            
            logger.info(f"Saved today's data for {symbol} to {individual_file}")
            
            # Update dynamic index
            try:
                self.update_dynamic_index(category)
                logger.info(f"✓ Updated dynamic index for {symbol}")
            except Exception as e:
                logger.warning(f"Could not update dynamic index for {symbol}: {e}")
            
        except Exception as e:
            logger.error(f"Error saving daily data for {symbol}: {str(e)}")

    def fetch_historical_data(self, symbol: str, start_date: str, end_date: str) -> Dict:
        """
        [FUTURE FEATURE] Fetch historical stock data for a date range.
        This will use the same proven logic from inspiration project.
        
        Args:
            symbol: Stock symbol
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        
        Returns:
            Dict with historical data
            
        Note: This method will be implemented in a future update using the
        proven patterns from inspirations/code/us_stocks/download_us_data.py
        and inspirations/code/ind_stocks/download_ind_data.py
        """
        raise NotImplementedError("Historical data fetching - to be implemented")

# For backward compatibility, create an alias
LiveFetcher = CurrentFetcher
