"""Cloud storage integration for historical data caching and persistence."""

import json
import pickle
import gzip
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import structlog
from dataclasses import asdict

try:
    from google.cloud import storage
    from google.api_core import exceptions as gcp_exceptions
    CLOUD_STORAGE_AVAILABLE = True
except ImportError:
    CLOUD_STORAGE_AVAILABLE = False
    storage = None
    gcp_exceptions = None

from ..utils.config import Config
from .historical_data import HistoricalOptionData

logger = structlog.get_logger(__name__)


class CloudStorageCache:
    """Cloud storage-based caching for historical market data."""

    def __init__(self, config: Config, bucket_name: Optional[str] = None):
        """Initialize cloud storage cache.

        Args:
            config: Configuration instance
            bucket_name: GCS bucket name (defaults to project-based name)
        """
        self.config = config
        self.project_id = getattr(config, 'gcp_project_id', 'gen-lang-client-0607444019')
        self.bucket_name = bucket_name or f"{self.project_id}-options-data"

        # Local fallback cache
        self.local_cache_dir = Path("cache/historical_data")
        self.local_cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialize GCS client if available
        self.client = None
        self.bucket = None

        if CLOUD_STORAGE_AVAILABLE:
            try:
                self.client = storage.Client(project=self.project_id)
                self._ensure_bucket_exists()
                logger.info("Cloud storage initialized", bucket=self.bucket_name)
            except Exception as e:
                logger.warning("Cloud storage unavailable, using local cache", error=str(e))
        else:
            logger.warning("Google Cloud Storage not available, using local cache only")

    def _ensure_bucket_exists(self):
        """Ensure the storage bucket exists."""
        try:
            self.bucket = self.client.get_bucket(self.bucket_name)
            logger.debug("Using existing bucket", bucket=self.bucket_name)
        except gcp_exceptions.NotFound:
            logger.info("Creating new bucket", bucket=self.bucket_name)
            # Create bucket with appropriate settings
            bucket = self.client.bucket(self.bucket_name)
            bucket.storage_class = "STANDARD"
            bucket.location = "US"

            # Set lifecycle rules for cost optimization
            bucket.lifecycle_rules = [{
                'action': {'type': 'SetStorageClass', 'storageClass': 'COLDLINE'},
                'condition': {'age': 30}  # Move to coldline after 30 days
            }, {
                'action': {'type': 'SetStorageClass', 'storageClass': 'ARCHIVE'},
                'condition': {'age': 365}  # Archive after 1 year
            }, {
                'action': {'type': 'Delete'},
                'condition': {'age': 2555}  # Delete after 7 years
            }]

            self.bucket = self.client.create_bucket(bucket)
            logger.info("Bucket created successfully", bucket=self.bucket_name)

    def _generate_cache_key(self, data_type: str, symbol: str,
                          start_date: datetime, end_date: datetime,
                          **kwargs) -> str:
        """Generate a standardized cache key.

        Args:
            data_type: Type of data ('stock', 'option_chain', 'option_bars')
            symbol: Symbol or underlying
            start_date: Start date
            end_date: End date
            **kwargs: Additional parameters for key generation

        Returns:
            Standardized cache key
        """
        # Create base key
        date_str = f"{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
        base_key = f"{data_type}/{symbol}/{date_str}"

        # Add additional parameters
        if kwargs:
            params = "_".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
            base_key += f"_{params}"

        return base_key + ".gz"

    def get_stock_data(self, symbol: str, start_date: datetime,
                      end_date: datetime, timeframe: str = "Day") -> Optional[pd.DataFrame]:
        """Get cached stock data from cloud storage.

        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
            timeframe: Data timeframe

        Returns:
            Cached DataFrame or None if not found
        """
        cache_key = self._generate_cache_key("stock", symbol, start_date, end_date,
                                           timeframe=timeframe)

        try:
            # Try cloud storage first
            if self.bucket:
                blob = self.bucket.blob(cache_key)
                if blob.exists():
                    logger.debug("Loading stock data from cloud storage",
                               symbol=symbol, key=cache_key)

                    compressed_data = blob.download_as_bytes()
                    data = pickle.loads(gzip.decompress(compressed_data))

                    # Convert back to DataFrame
                    if isinstance(data, dict) and 'dataframe' in data:
                        df = pd.DataFrame(data['dataframe'])
                        if 'index' in data:
                            df.index = pd.to_datetime(data['index'])
                        return df

            # Fallback to local cache
            local_path = self.local_cache_dir / cache_key
            if local_path.exists():
                logger.debug("Loading stock data from local cache",
                           symbol=symbol, path=str(local_path))

                with gzip.open(local_path, 'rb') as f:
                    data = pickle.load(f)

                if isinstance(data, dict) and 'dataframe' in data:
                    df = pd.DataFrame(data['dataframe'])
                    if 'index' in data:
                        df.index = pd.to_datetime(data['index'])
                    return df

            return None

        except Exception as e:
            logger.debug("Failed to load cached stock data",
                        symbol=symbol, error=str(e))
            return None

    def save_stock_data(self, symbol: str, start_date: datetime,
                       end_date: datetime, data: pd.DataFrame,
                       timeframe: str = "Day") -> bool:
        """Save stock data to cloud storage cache.

        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
            data: DataFrame to cache
            timeframe: Data timeframe

        Returns:
            True if saved successfully
        """
        cache_key = self._generate_cache_key("stock", symbol, start_date, end_date,
                                           timeframe=timeframe)

        try:
            # Prepare data for serialization
            cache_data = {
                'dataframe': data.to_dict(),
                'index': data.index.strftime('%Y-%m-%d %H:%M:%S').tolist() if hasattr(data.index, 'strftime') else data.index.tolist(),
                'symbol': symbol,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat(),
                'timeframe': timeframe,
                'cached_at': datetime.now().isoformat()
            }

            # Compress data
            compressed_data = gzip.compress(pickle.dumps(cache_data))

            # Save to cloud storage
            success_cloud = False
            if self.bucket:
                try:
                    blob = self.bucket.blob(cache_key)
                    blob.upload_from_string(compressed_data, content_type='application/octet-stream')
                    success_cloud = True
                    logger.debug("Saved stock data to cloud storage",
                               symbol=symbol, key=cache_key, size=len(compressed_data))
                except Exception as e:
                    logger.warning("Failed to save to cloud storage",
                                 symbol=symbol, error=str(e))

            # Save to local cache as fallback
            success_local = False
            try:
                local_path = self.local_cache_dir / cache_key
                local_path.parent.mkdir(parents=True, exist_ok=True)

                with gzip.open(local_path, 'wb') as f:
                    pickle.dump(cache_data, f)
                success_local = True
                logger.debug("Saved stock data to local cache",
                           symbol=symbol, path=str(local_path))
            except Exception as e:
                logger.warning("Failed to save to local cache",
                             symbol=symbol, error=str(e))

            return success_cloud or success_local

        except Exception as e:
            logger.error("Failed to save stock data", symbol=symbol, error=str(e))
            return False

    def get_option_chain(self, underlying: str, date: datetime,
                        max_dte: int = 45) -> Optional[Dict[str, List[Dict]]]:
        """Get cached option chain data.

        Args:
            underlying: Underlying symbol
            date: Date for option chain
            max_dte: Maximum DTE filter

        Returns:
            Cached option chain or None
        """
        cache_key = self._generate_cache_key("option_chain", underlying,
                                           date, date + timedelta(days=1),
                                           max_dte=max_dte)

        try:
            # Try cloud storage first
            if self.bucket:
                blob = self.bucket.blob(cache_key)
                if blob.exists():
                    logger.debug("Loading option chain from cloud storage",
                               underlying=underlying, key=cache_key)

                    compressed_data = blob.download_as_bytes()
                    data = pickle.loads(gzip.decompress(compressed_data))

                    if isinstance(data, dict) and 'option_chain' in data:
                        return data['option_chain']

            # Fallback to local cache
            local_path = self.local_cache_dir / cache_key
            if local_path.exists():
                logger.debug("Loading option chain from local cache",
                           underlying=underlying, path=str(local_path))

                with gzip.open(local_path, 'rb') as f:
                    data = pickle.load(f)

                if isinstance(data, dict) and 'option_chain' in data:
                    return data['option_chain']

            return None

        except Exception as e:
            logger.debug("Failed to load cached option chain",
                        underlying=underlying, error=str(e))
            return None

    def save_option_chain(self, underlying: str, date: datetime,
                         option_chain: Dict[str, List[Dict]],
                         max_dte: int = 45) -> bool:
        """Save option chain to cache.

        Args:
            underlying: Underlying symbol
            date: Date for option chain
            option_chain: Option chain data
            max_dte: Maximum DTE filter

        Returns:
            True if saved successfully
        """
        cache_key = self._generate_cache_key("option_chain", underlying,
                                           date, date + timedelta(days=1),
                                           max_dte=max_dte)

        try:
            cache_data = {
                'option_chain': option_chain,
                'underlying': underlying,
                'date': date.isoformat(),
                'max_dte': max_dte,
                'cached_at': datetime.now().isoformat()
            }

            compressed_data = gzip.compress(pickle.dumps(cache_data))

            # Save to cloud storage
            success_cloud = False
            if self.bucket:
                try:
                    blob = self.bucket.blob(cache_key)
                    blob.upload_from_string(compressed_data, content_type='application/octet-stream')
                    success_cloud = True
                    logger.debug("Saved option chain to cloud storage",
                               underlying=underlying, key=cache_key)
                except Exception as e:
                    logger.warning("Failed to save option chain to cloud",
                                 underlying=underlying, error=str(e))

            # Save to local cache
            success_local = False
            try:
                local_path = self.local_cache_dir / cache_key
                local_path.parent.mkdir(parents=True, exist_ok=True)

                with gzip.open(local_path, 'wb') as f:
                    pickle.dump(cache_data, f)
                success_local = True
                logger.debug("Saved option chain to local cache",
                           underlying=underlying, path=str(local_path))
            except Exception as e:
                logger.warning("Failed to save option chain locally",
                             underlying=underlying, error=str(e))

            return success_cloud or success_local

        except Exception as e:
            logger.error("Failed to save option chain", underlying=underlying, error=str(e))
            return False

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache usage statistics.

        Returns:
            Dictionary with cache statistics
        """
        stats = {
            'cloud_storage_available': self.bucket is not None,
            'bucket_name': self.bucket_name,
            'local_cache_dir': str(self.local_cache_dir),
            'local_cache_size': 0,
            'local_cache_files': 0
        }

        # Local cache stats
        try:
            local_files = list(self.local_cache_dir.rglob("*.gz"))
            stats['local_cache_files'] = len(local_files)
            stats['local_cache_size'] = sum(f.stat().st_size for f in local_files)
        except Exception as e:
            logger.debug("Failed to get local cache stats", error=str(e))

        # Cloud storage stats
        if self.bucket:
            try:
                blobs = list(self.bucket.list_blobs())
                stats['cloud_cache_files'] = len(blobs)
                stats['cloud_cache_size'] = sum(blob.size for blob in blobs if blob.size)
            except Exception as e:
                logger.debug("Failed to get cloud cache stats", error=str(e))

        return stats

    def cleanup_old_cache(self, days_old: int = 30) -> Dict[str, int]:
        """Clean up old cache files.

        Args:
            days_old: Remove files older than this many days

        Returns:
            Dictionary with cleanup statistics
        """
        cutoff_date = datetime.now() - timedelta(days=days_old)
        stats = {'local_deleted': 0, 'cloud_deleted': 0}

        # Clean local cache
        try:
            for cache_file in self.local_cache_dir.rglob("*.gz"):
                if cache_file.stat().st_mtime < cutoff_date.timestamp():
                    cache_file.unlink()
                    stats['local_deleted'] += 1
            logger.info("Local cache cleanup completed", **stats)
        except Exception as e:
            logger.warning("Local cache cleanup failed", error=str(e))

        # Clean cloud cache (handled by bucket lifecycle rules)
        # Manual cleanup not needed as we set lifecycle rules

        return stats

    def _store_json_data(self, cloud_path: str, data: Dict[str, Any]):
        """Store JSON data to cloud storage with local fallback."""
        try:
            if self.client and self.bucket:
                # Store to GCS
                blob = self.bucket.blob(cloud_path)
                blob.upload_from_string(
                    json.dumps(data, indent=2, default=str),
                    content_type='application/json'
                )
                logger.info("Stored data to cloud storage", path=cloud_path, size_kb=len(json.dumps(data))/1024)
            else:
                # Store locally as fallback
                local_path = self.local_cache_dir / cloud_path
                local_path.parent.mkdir(parents=True, exist_ok=True)
                with open(local_path, 'w') as f:
                    json.dump(data, f, indent=2, default=str)
                logger.info("Stored data locally", path=str(local_path))

        except Exception as e:
            logger.error("Failed to store data", path=cloud_path, error=str(e))
            # Fallback to local storage
            try:
                local_path = self.local_cache_dir / cloud_path
                local_path.parent.mkdir(parents=True, exist_ok=True)
                with open(local_path, 'w') as f:
                    json.dump(data, f, indent=2, default=str)
                logger.info("Fallback: stored data locally", path=str(local_path))
            except Exception as e2:
                logger.error("Failed to store data locally", error=str(e2))

    def get_stored_backtest_results(self, backtest_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve stored backtest results by ID."""
        try:
            cloud_path = f"backtest_results/{backtest_id}.json"

            if self.client and self.bucket:
                # Try cloud storage first
                try:
                    blob = self.bucket.blob(cloud_path)
                    if blob.exists():
                        data = json.loads(blob.download_as_text())
                        logger.info("Retrieved backtest results from cloud", backtest_id=backtest_id)
                        return data
                except Exception as e:
                    logger.debug("Failed to retrieve from cloud", error=str(e))

            # Try local storage
            local_path = self.local_cache_dir / cloud_path
            if local_path.exists():
                with open(local_path, 'r') as f:
                    data = json.load(f)
                logger.info("Retrieved backtest results locally", backtest_id=backtest_id)
                return data

            logger.warning("Backtest results not found", backtest_id=backtest_id)
            return None

        except Exception as e:
            logger.error("Failed to retrieve backtest results", backtest_id=backtest_id, error=str(e))
            return None

    def list_stored_backtests(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List stored backtest results with metadata."""
        try:
            results = []

            if self.client and self.bucket:
                # List from cloud storage
                try:
                    blobs = self.bucket.list_blobs(prefix="backtest_results/", max_results=limit)
                    for blob in blobs:
                        if blob.name.endswith('.json'):
                            backtest_id = blob.name.split('/')[-1].replace('.json', '')
                            results.append({
                                'backtest_id': backtest_id,
                                'created': blob.time_created.isoformat() if blob.time_created else None,
                                'size_kb': round(blob.size / 1024, 2) if blob.size else 0,
                                'storage': 'cloud'
                            })
                except Exception as e:
                    logger.debug("Failed to list from cloud", error=str(e))

            # Also check local storage
            local_results_dir = self.local_cache_dir / "backtest_results"
            if local_results_dir.exists():
                for json_file in local_results_dir.glob("*.json"):
                    backtest_id = json_file.stem
                    if not any(r['backtest_id'] == backtest_id for r in results):
                        results.append({
                            'backtest_id': backtest_id,
                            'created': datetime.fromtimestamp(json_file.stat().st_mtime).isoformat(),
                            'size_kb': round(json_file.stat().st_size / 1024, 2),
                            'storage': 'local'
                        })

            # Sort by creation date (newest first)
            results.sort(key=lambda x: x['created'] or '', reverse=True)
            return results[:limit]

        except Exception as e:
            logger.error("Failed to list stored backtests", error=str(e))
            return []


class EnhancedHistoricalDataManager:
    """Enhanced historical data manager with cloud storage integration."""

    def __init__(self, config: Config, use_cloud_cache: bool = True):
        """Initialize enhanced data manager.

        Args:
            config: Configuration instance
            use_cloud_cache: Whether to use cloud storage caching
        """
        # Import here to avoid circular imports
        from .historical_data import HistoricalDataManager

        self.base_manager = HistoricalDataManager(config)
        self.cloud_cache = CloudStorageCache(config) if use_cloud_cache else None
        self.config = config

        logger.info("Enhanced historical data manager initialized",
                   cloud_cache=use_cloud_cache)

    def get_stock_data(self, symbol: str, start_date: datetime,
                      end_date: datetime, timeframe: str = "Day") -> pd.DataFrame:
        """Get stock data with cloud caching.

        Args:
            symbol: Stock symbol
            start_date: Start date
            end_date: End date
            timeframe: Data timeframe

        Returns:
            Stock data DataFrame
        """
        # Try cache first
        if self.cloud_cache:
            cached_data = self.cloud_cache.get_stock_data(symbol, start_date, end_date, timeframe)
            if cached_data is not None and not cached_data.empty:
                logger.debug("Using cached stock data", symbol=symbol)
                return cached_data

        # Fetch from API
        logger.debug("Fetching fresh stock data", symbol=symbol)
        # Convert timeframe string to TimeFrame object if needed
        from alpaca.data.timeframe import TimeFrame
        tf_map = {
            "Day": TimeFrame.Day,
            "Hour": TimeFrame.Hour,
            "Minute": TimeFrame.Minute
        }
        tf_obj = tf_map.get(timeframe, TimeFrame.Day)

        data = self.base_manager.get_stock_data(symbol, start_date, end_date, tf_obj)

        # Cache the results
        if self.cloud_cache and not data.empty:
            self.cloud_cache.save_stock_data(symbol, start_date, end_date, data, timeframe)

        return data

    def get_option_chain_historical_bars(self, underlying: str, date: datetime,
                                       underlying_price: float, max_dte: int = 45) -> Dict[str, List[Dict]]:
        """Get option chain with cloud caching.

        Args:
            underlying: Underlying symbol
            date: Date for chain
            underlying_price: Current stock price
            max_dte: Maximum DTE

        Returns:
            Option chain data
        """
        # Try cache first
        if self.cloud_cache:
            cached_chain = self.cloud_cache.get_option_chain(underlying, date, max_dte)
            if cached_chain:
                logger.debug("Using cached option chain", underlying=underlying)
                return cached_chain

        # Fetch from API
        logger.debug("Fetching fresh option chain", underlying=underlying)
        chain = self.base_manager.get_option_chain_historical_bars(
            underlying, date, underlying_price, max_dte
        )

        # Cache the results
        if self.cloud_cache and (chain['puts'] or chain['calls']):
            self.cloud_cache.save_option_chain(underlying, date, chain, max_dte)

        return chain

    def get_cache_info(self) -> Dict[str, Any]:
        """Get information about cache usage.

        Returns:
            Cache usage information
        """
        if self.cloud_cache:
            return self.cloud_cache.get_cache_stats()
        else:
            return {'cache_enabled': False}