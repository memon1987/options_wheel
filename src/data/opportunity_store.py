"""Cloud Storage-backed opportunity store for scan-to-execution coordination."""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import json
import structlog
from google.cloud import storage

from ..utils.config import Config
from ..utils.logging_events import log_system_event, log_error_event

logger = structlog.get_logger(__name__)


class OpportunityStore:
    """Manages storage and retrieval of trading opportunities between scan and execution."""

    def __init__(self, config: Config, bucket_name: str = "options-wheel-opportunities"):
        """Initialize opportunity store.

        Args:
            config: Configuration instance
            bucket_name: GCS bucket name for storing opportunities
        """
        self.config = config
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()

        # Ensure bucket exists
        self._ensure_bucket_exists()

        logger.info("OpportunityStore initialized", bucket=bucket_name)

    def _ensure_bucket_exists(self):
        """Create bucket if it doesn't exist."""
        try:
            bucket = self.storage_client.bucket(self.bucket_name)
            if not bucket.exists():
                bucket = self.storage_client.create_bucket(
                    self.bucket_name,
                    location="us-central1"
                )
                logger.info("Created opportunities bucket", bucket=self.bucket_name)
        except Exception as e:
            logger.warning("Could not create bucket (may already exist)",
                          bucket=self.bucket_name, error=str(e))

    def store_opportunities(self, opportunities: List[Dict[str, Any]],
                           scan_time: datetime) -> bool:
        """Store opportunities from a market scan.

        Args:
            opportunities: List of opportunity dictionaries from scan
            scan_time: When the scan was performed

        Returns:
            True if stored successfully
        """
        try:
            # Create storage object with timestamp-based path
            blob_path = self._get_blob_path(scan_time)

            # Add metadata
            storage_data = {
                'scan_time': scan_time.isoformat(),
                'expires_at': (scan_time + timedelta(minutes=20)).isoformat(),
                'opportunity_count': len(opportunities),
                'opportunities': opportunities,
                'status': 'pending'
            }

            # Upload to Cloud Storage
            bucket = self.storage_client.bucket(self.bucket_name)
            blob = bucket.blob(blob_path)
            blob.upload_from_string(
                json.dumps(storage_data, indent=2),
                content_type='application/json'
            )

            log_system_event(
                logger,
                event_type="opportunities_stored",
                status="success",
                opportunity_count=len(opportunities),
                blob_path=blob_path,
                expires_at=storage_data['expires_at']
            )

            logger.info("Stored opportunities to Cloud Storage",
                       count=len(opportunities),
                       path=blob_path)

            return True

        except Exception as e:
            log_error_event(
                logger,
                error_type="opportunity_storage_failed",
                error_message=str(e),
                component="opportunity_store",
                recoverable=True,
                opportunity_count=len(opportunities)
            )
            return False

    def get_pending_opportunities(self, execution_time: datetime) -> List[Dict[str, Any]]:
        """Retrieve pending opportunities for execution.

        Finds the most recent scan file within the max age window,
        regardless of when it was created. This decouples execution from
        hard-coded time schedules.

        Args:
            execution_time: Current execution time

        Returns:
            List of valid, unexpired opportunities
        """
        try:
            bucket = self.storage_client.bucket(self.bucket_name)

            # Get all opportunity files from today
            date_str = execution_time.strftime('%Y-%m-%d')
            prefix = f"opportunities/{date_str}/"

            # List all blobs for today and sort by creation time (most recent first)
            blobs = sorted(
                bucket.list_blobs(prefix=prefix),
                key=lambda b: b.time_created,
                reverse=True
            )

            if not blobs:
                logger.info("No opportunity scans found for today",
                           date=date_str,
                           execution_time=execution_time.isoformat())
                return []

            # Find the most recent valid scan
            max_age_minutes = self.config.opportunity_max_age_minutes
            max_age_delta = timedelta(minutes=max_age_minutes)

            for blob in blobs:
                try:
                    # Download and parse
                    content = blob.download_as_string()
                    data = json.loads(content)

                    # Parse scan time
                    scan_time = datetime.fromisoformat(data['scan_time'].replace('Z', '+00:00'))
                    if scan_time.tzinfo is None:
                        scan_time = scan_time.replace(tzinfo=execution_time.tzinfo)

                    # Check if scan is too old (based on configurable max age)
                    age = execution_time - scan_time
                    if age > max_age_delta:
                        logger.info("Scan too old, skipping",
                                   scan_time=data['scan_time'],
                                   age_minutes=age.total_seconds() / 60,
                                   max_age_minutes=max_age_minutes,
                                   path=blob.name)
                        continue

                    # Check if already executed
                    if data.get('status') == 'executed':
                        logger.info("Scan already executed, checking next",
                                   path=blob.name,
                                   scan_time=data['scan_time'])
                        continue

                    # Found valid scan!
                    opportunities = data.get('opportunities', [])

                    logger.info("Retrieved most recent valid scan",
                               count=len(opportunities),
                               scan_time=data['scan_time'],
                               age_minutes=round(age.total_seconds() / 60, 1),
                               max_age_minutes=max_age_minutes,
                               path=blob.name)

                    return opportunities

                except Exception as e:
                    logger.warning("Failed to process scan file, trying next",
                                  path=blob.name,
                                  error=str(e))
                    continue

            # No valid scans found
            logger.info("No valid scans found within age window",
                       execution_time=execution_time.isoformat(),
                       max_age_minutes=max_age_minutes,
                       scans_checked=len(blobs))
            return []

        except Exception as e:
            log_error_event(
                logger,
                error_type="opportunity_retrieval_failed",
                error_message=str(e),
                component="opportunity_store",
                recoverable=True,
                execution_time=execution_time.isoformat()
            )
            return []

    def mark_executed(self, execution_time: datetime,
                     executed_count: int,
                     results: List[Dict[str, Any]],
                     scan_blob_path: Optional[str] = None) -> bool:
        """Mark opportunities as executed.

        Args:
            execution_time: When execution occurred
            executed_count: Number of opportunities executed
            results: Execution results for each opportunity
            scan_blob_path: Optional path to the scan file that was executed.
                          If not provided, will find the most recent scan.

        Returns:
            True if marked successfully
        """
        try:
            # If scan path not provided, find the most recent one
            if not scan_blob_path:
                # Re-use same logic as get_pending_opportunities
                bucket = self.storage_client.bucket(self.bucket_name)
                date_str = execution_time.strftime('%Y-%m-%d')
                prefix = f"opportunities/{date_str}/"

                blobs = sorted(
                    bucket.list_blobs(prefix=prefix),
                    key=lambda b: b.time_created,
                    reverse=True
                )

                if not blobs:
                    logger.warning("Cannot mark executed - no scans found", date=date_str)
                    return False

                # Find the most recent non-executed scan
                max_age_delta = timedelta(minutes=self.config.opportunity_max_age_minutes)
                for blob in blobs:
                    try:
                        content = blob.download_as_string()
                        data = json.loads(content)
                        scan_time = datetime.fromisoformat(data['scan_time'].replace('Z', '+00:00'))
                        age = execution_time - scan_time

                        if age <= max_age_delta and data.get('status') != 'executed':
                            scan_blob_path = blob.name
                            break
                    except:
                        continue

            if not scan_blob_path:
                logger.warning("Cannot mark executed - no valid scan found")
                return False

            bucket = self.storage_client.bucket(self.bucket_name)
            blob = bucket.blob(scan_blob_path)

            if not blob.exists():
                logger.warning("Cannot mark executed - blob not found", path=scan_blob_path)
                return False

            # Update status
            content = blob.download_as_string()
            data = json.loads(content)

            data['status'] = 'executed'
            data['executed_at'] = execution_time.isoformat()
            data['executed_count'] = executed_count
            data['execution_results'] = results

            # Save updated data
            blob.upload_from_string(
                json.dumps(data, indent=2),
                content_type='application/json'
            )

            log_system_event(
                logger,
                event_type="opportunities_marked_executed",
                status="success",
                executed_count=executed_count,
                blob_path=scan_blob_path
            )

            return True

        except Exception as e:
            log_error_event(
                logger,
                error_type="mark_executed_failed",
                error_message=str(e),
                component="opportunity_store",
                recoverable=True
            )
            return False

    def _get_blob_path(self, timestamp: datetime) -> str:
        """Generate blob path for storing opportunities.

        Args:
            timestamp: Timestamp for the scan

        Returns:
            Path like: opportunities/2025-10-03/14-00.json
        """
        date_str = timestamp.strftime('%Y-%m-%d')
        hour_min = timestamp.strftime('%H-%M')
        return f"opportunities/{date_str}/{hour_min}.json"

    def _get_scan_blob_path(self, execution_time: datetime) -> str:
        """Get the blob path for the scan that should feed this execution.

        For an execution at 10:15, looks for scan at 10:00.

        Args:
            execution_time: Execution timestamp

        Returns:
            Path to the corresponding scan file
        """
        # Round down to the hour (scans happen at :00)
        scan_time = execution_time.replace(minute=0, second=0, microsecond=0)
        return self._get_blob_path(scan_time)

    def cleanup_old_opportunities(self, older_than_hours: int = 24) -> int:
        """Delete old opportunity files.

        Args:
            older_than_hours: Delete files older than this many hours

        Returns:
            Number of files deleted
        """
        try:
            bucket = self.storage_client.bucket(self.bucket_name)
            cutoff_time = datetime.utcnow() - timedelta(hours=older_than_hours)

            deleted_count = 0
            for blob in bucket.list_blobs(prefix='opportunities/'):
                if blob.time_created.replace(tzinfo=None) < cutoff_time:
                    blob.delete()
                    deleted_count += 1

            if deleted_count > 0:
                logger.info("Cleaned up old opportunities",
                           deleted_count=deleted_count,
                           older_than_hours=older_than_hours)

            return deleted_count

        except Exception as e:
            log_error_event(
                logger,
                error_type="cleanup_failed",
                error_message=str(e),
                component="opportunity_store",
                recoverable=True
            )
            return 0
