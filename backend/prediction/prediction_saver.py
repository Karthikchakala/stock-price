"""
Prediction Saver

This module handles saving prediction results to CSV files in the data/future directory.
"""

import os
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any
import logging
from datetime import datetime
import json

from .config import config

logger = logging.getLogger(__name__)


class PredictionSaver:
    """
    Handles saving prediction results to CSV files.
    """
    
    def __init__(self):
        self.config = config
        self._ensure_directories()
    
    def _ensure_directories(self):
        """Ensure all required directories exist."""
        directories = [
            self.config.FUTURE_DATA_DIR,
            os.path.join(self.config.FUTURE_DATA_DIR, 'us_stocks', 'individual_files'),
            os.path.join(self.config.FUTURE_DATA_DIR, 'ind_stocks', 'individual_files')
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
            logger.debug(f"Ensured directory exists: {directory}")
    
    def save_predictions(self, symbol: str, category: str, predictions: List[Dict[str, Any]]) -> bool:
        """
        Save predictions for a stock to CSV file.
        
        Args:
            symbol: Stock symbol (e.g., 'AAPL', 'RELIANCE')
            category: Stock category ('us_stocks' or 'ind_stocks')
            predictions: List of prediction dictionaries
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not predictions:
                logger.warning(f"No predictions to save for {symbol}")
                return False
            
            # Create DataFrame from predictions
            df = pd.DataFrame(predictions)
            
            # Ensure all required columns are present with category awareness
            df = self._ensure_required_columns(df, category=category)
            
            # Validate predictions
            if not self._validate_predictions(df, symbol):
                return False
            
            # Get file path
            file_path = self._get_file_path(symbol, category)
            
            # Save to CSV
            df.to_csv(file_path, index=False)
            
            logger.info(f"Saved {len(predictions)} predictions for {symbol} to {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving predictions for {symbol}: {str(e)}")
            return False
    
    def _ensure_required_columns(self, df: pd.DataFrame, category: str = 'us_stocks') -> pd.DataFrame:
        """Ensure all required columns are present in the DataFrame with category-aware defaults."""
        required_columns = self.config.OUTPUT_COLUMNS
        
        # Add missing columns with default values
        for column in required_columns:
            if column not in df.columns:
                if column == 'date':
                    df[column] = datetime.now().strftime('%Y-%m-%d')
                elif column == 'last_updated':
                    df[column] = datetime.now().isoformat()
                elif column == 'currency':
                    df[column] = 'INR' if category == 'ind_stocks' else 'USD'
                elif column == 'current_price':
                    df[column] = 0.0
                elif column in ['confidence', 'confidence_low', 'confidence_high', 'model_accuracy']:
                    df[column] = 0.0
                elif column == 'data_points_used':
                    df[column] = 0
                else:
                    df[column] = ''
        
        # If currency is present but empty or NaN, populate with category currency
        if 'currency' in df.columns:
            target_currency = 'INR' if category == 'ind_stocks' else 'USD'
            df['currency'] = df['currency'].fillna(target_currency)
            df.loc[df['currency'] == '', 'currency'] = target_currency
        
        # Reorder columns to match required order
        df = df[required_columns]
        
        return df
    
    def _validate_predictions(self, df: pd.DataFrame, symbol: str) -> bool:
        """Validate prediction data before saving."""
        try:
            # Check for required columns
            required_columns = ['date', 'horizon', 'predicted_price']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                logger.error(f"Missing required columns for {symbol}: {missing_columns}")
                return False
            
            # Validate predicted prices
            if df['predicted_price'].isnull().any():
                logger.error(f"Null predicted prices found for {symbol}")
                return False
            
            if (df['predicted_price'] <= 0).any():
                logger.error(f"Invalid predicted prices (<= 0) found for {symbol}")
                return False
            
            # Validate horizons
            valid_horizons = list(self.config.TIME_HORIZONS.keys())
            invalid_horizons = df[~df['horizon'].isin(valid_horizons)]['horizon'].unique()
            
            if len(invalid_horizons) > 0:
                logger.error(f"Invalid horizons for {symbol}: {invalid_horizons}")
                return False
            
            # Validate confidence intervals
            if 'confidence_low' in df.columns and 'confidence_high' in df.columns:
                invalid_confidence = df[df['confidence_low'] > df['confidence_high']]
                if len(invalid_confidence) > 0:
                    logger.error(f"Invalid confidence intervals for {symbol}")
                    return False
            
            logger.debug(f"Prediction validation passed for {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"Error validating predictions for {symbol}: {str(e)}")
            return False
    
    def _get_file_path(self, symbol: str, category: str) -> str:
        """Get the file path for saving predictions."""
        return os.path.join(
            self.config.FUTURE_DATA_DIR,
            category,
            'individual_files',
            f'{symbol}.csv'
        )
    
    def load_predictions(self, symbol: str, category: str) -> Optional[pd.DataFrame]:
        """
        Load existing predictions for a stock.
        
        Args:
            symbol: Stock symbol
            category: Stock category
            
        Returns:
            DataFrame with predictions or None if not found
        """
        try:
            file_path = self._get_file_path(symbol, category)
            
            if not os.path.exists(file_path):
                logger.debug(f"No existing predictions found for {symbol}")
                return None
            
            if os.path.getsize(file_path) == 0:
                logger.warning(f"Prediction file for {symbol} is empty.")
                return None
            
            df = pd.read_csv(file_path)
            logger.debug(f"Loaded {len(df)} existing predictions for {symbol}")
            return df
            
        except Exception as e:
            logger.error(f"Error loading predictions for {symbol}: {str(e)}")
            return None
    
    def update_predictions(self, symbol: str, category: str, new_predictions: List[Dict[str, Any]]) -> bool:
        """
        Update existing predictions with new ones.
        
        Args:
            symbol: Stock symbol
            category: Stock category
            new_predictions: List of new prediction dictionaries
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if not new_predictions:
                logger.warning(f"No new predictions to update for {symbol}")
                return False
                
            # Load existing predictions
            existing_df = self.load_predictions(symbol, category)
            
            if existing_df is None or existing_df.empty:
                # No existing predictions, save new ones
                return self.save_predictions(symbol, category, new_predictions)
            
            # Create DataFrame from new predictions
            new_df = pd.DataFrame(new_predictions)
            new_df = self._ensure_required_columns(new_df, category=category)
            
            # Validate new predictions
            if not self._validate_predictions(new_df, symbol):
                return False
            
            # Merge with existing predictions (replace by horizon)
            if 'horizon' in existing_df.columns and 'horizon' in new_df.columns:
                # Remove existing predictions for horizons that are being updated
                horizons_to_update = new_df['horizon'].unique()
                existing_df = existing_df[~existing_df['horizon'].isin(horizons_to_update)]
                
                # Combine old and new predictions
                combined_df = pd.concat([existing_df, new_df], ignore_index=True)
            else:
                # If no horizon column, just append
                combined_df = pd.concat([existing_df, new_df], ignore_index=True)
            
            # Re-normalize combined DataFrame for category currency & column order
            combined_df = self._ensure_required_columns(combined_df, category=category)
            
            # Save combined predictions
            file_path = self._get_file_path(symbol, category)
            combined_df.to_csv(file_path, index=False)
            
            logger.info(f"Updated predictions for {symbol}: {len(new_predictions)} new, {len(combined_df)} total")
            return True
            
        except Exception as e:
            logger.error(f"Error updating predictions for {symbol}: {str(e)}")
            return False
    
    def get_prediction_summary(self, category: str) -> Dict[str, Any]:
        """
        Get summary of all predictions for a category.
        
        Args:
            category: Stock category ('us_stocks' or 'ind_stocks')
            
        Returns:
            Dictionary with prediction summary
        """
        try:
            individual_files_dir = os.path.join(
                self.config.FUTURE_DATA_DIR,
                category,
                'individual_files'
            )
            
            if not os.path.exists(individual_files_dir):
                return {
                    'total_stocks': 0,
                    'total_predictions': 0,
                    'latest_update': None,
                    'horizons_available': []
                }
            
            # Get all CSV files
            csv_files = [f for f in os.listdir(individual_files_dir) if f.endswith('.csv')]
            
            total_predictions = 0
            latest_update = None
            horizons = set()
            
            for csv_file in csv_files:
                file_path = os.path.join(individual_files_dir, csv_file)
                try:
                    if os.path.getsize(file_path) == 0:
                        continue
                    df = pd.read_csv(file_path)
                    total_predictions += len(df)
                    
                    # Track latest update
                    if 'last_updated' in df.columns:
                        file_latest = df['last_updated'].max()
                        if latest_update is None or file_latest > latest_update:
                            latest_update = file_latest
                    
                    # Track horizons
                    if 'horizon' in df.columns:
                        horizons.update(df['horizon'].unique())
                        
                except Exception as e:
                    logger.warning(f"Error reading {csv_file}: {str(e)}")
                    continue
            
            return {
                'total_stocks': len(csv_files),
                'total_predictions': total_predictions,
                'latest_update': latest_update,
                'horizons_available': sorted(list(horizons))
            }
            
        except Exception as e:
            logger.error(f"Error getting prediction summary for {category}: {str(e)}")
            return {
                'total_stocks': 0,
                'total_predictions': 0,
                'latest_update': None,
                'horizons_available': []
            }
    
    def create_prediction_dict(self, 
                             horizon: str, 
                             predicted_price: float,
                             current_price: float = 0.0,
                             confidence: float = 50.0,
                             confidence_low: float = None,
                             confidence_high: float = None,
                             algorithm_used: str = '',
                             currency: str = 'USD',
                             model_accuracy: float = 0.0,
                             data_points_used: int = 0) -> Dict[str, Any]:
        """
        Create a standardized prediction dictionary.
        
        Args:
            horizon: Time horizon (1D, 1W, 1M, 1Y, 5Y)
            predicted_price: Predicted price
            confidence: Confidence score (0-100)
            confidence_low: Lower confidence bound
            confidence_high: Upper confidence bound
            algorithm_used: Algorithm(s) used for prediction
            currency: Currency of the prediction
            model_accuracy: Model accuracy score
            data_points_used: Number of data points used for training
            
        Returns:
            Dictionary with prediction data
        """
        # Calculate prediction date
        prediction_date = self.config.get_prediction_date(horizon)
        
        # Set default confidence bounds if not provided
        if confidence_low is None or confidence_high is None:
            confidence_range = predicted_price * 0.1  # 10% range
            confidence_low = predicted_price - confidence_range
            confidence_high = predicted_price + confidence_range
        
        return {
            'date': prediction_date.strftime('%Y-%m-%d'),
            'horizon': horizon,
            'predicted_price': round(predicted_price, 2),
            'current_price': round(current_price, 2),
            'confidence': round(confidence, 1),
            'confidence_low': round(confidence_low, 2),
            'confidence_high': round(confidence_high, 2),
            'algorithm_used': algorithm_used,
            'currency': currency,
            'last_updated': datetime.now().isoformat(),
            'model_accuracy': round(model_accuracy, 4),
            'data_points_used': data_points_used
        }
    
    def delete_predictions(self, symbol: str, category: str) -> bool:
        """
        Delete predictions for a stock.
        
        Args:
            symbol: Stock symbol
            category: Stock category
            
        Returns:
            True if successful, False otherwise
        """
        try:
            file_path = self._get_file_path(symbol, category)
            
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Deleted predictions for {symbol}")
                return True
            else:
                logger.debug(f"No predictions file found for {symbol}")
                return True
                
        except Exception as e:
            logger.error(f"Error deleting predictions for {symbol}: {str(e)}")
            return False
