import os
import threading
from pathlib import Path
from loguru import logger
from datetime import datetime

def generate_error_image_path() -> str:
    return f"{get_error_image_dir()}/error-{datetime.now().timestamp()}.jpg"

def get_error_image_dir() -> Path:
    """Get the path to the configured error image dir"""
    return Path(os.getenv("ERROR_IMAGE_DIR", "./images/errors"))

def get_folder_size(folder_path: Path) -> int:
    """Calculates the total size of all files in a folder in bytes."""
    total_size = 0
    try:
        for item in folder_path.iterdir():
            if item.is_file():
                total_size += item.stat().st_size
    except FileNotFoundError:
        logger.warning(f"Folder Watcher: Error image folder not found: {folder_path}")
        return 0
    except Exception as e:
        logger.error(f"Folder Watcher: Error calculating folder size for {folder_path}: {e}")
        return 0

    return total_size

def parse_timestamp_from_filename(filename: str) -> float|None:
    """Extracts timestamp from filenames like 'error-{timestamp}.jpg'."""
    try:
        # Assumes format "error-1683390000.12345.jpg"
        return float(filename.split('-')[1].rsplit('.jpg', 1)[0])
    except (IndexError, ValueError) as e:
        logger.warning(f"Folder Watcher: Could not parse timestamp from filename: {filename} - {e}")
        return None


def run_cleanup(stop_event: threading.Event):
    """
      Monitors the configured  folder's size and deletes oldest files if it exceeds max_size_bytes.
      Files are expected to be named 'error-{timestamp}.jpg'.
    """
    folder_path = get_error_image_dir()
    logger.info(f"Folder Watcher: Cleanup Thread Started for folder {folder_path}")

    # Create the image dir if not exists yet
    try:
        folder_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"Folder Watcher: Could not create error image folder {folder_path}: {e}")
        return None

    # Get the max allowed size
    max_size_bytes = int(os.getenv("ERROR_IMAGE_DIR_MAX_SIZE_MB", 100)) * 1024 * 1024
    check_interval = int(os.getenv("ERROR_IMAGE_DIR_CLEANUP_INTERVAL_SECONDS", 300))

    # Infinite loop until a stop event is given
    while not stop_event.is_set():
        try:
            # Resolve the current size
            current_size = get_folder_size(folder_path)
            logger.debug(f"Folder Watcher: Current size of {folder_path} is {current_size / (1024 * 1024):.2f} MB")

            # Check if the folder is too big
            if current_size > max_size_bytes:
                logger.info(f"Folder Watcher: Size limit {max_size_bytes / (1024 * 1024):.2f} MB exceeded. Current size: {current_size / (1024 * 1024):.2f} MB. Starting cleanup...")

                # Attempt to find all current error images, format should have a timestamp in the name
                files_to_delete = []
                for item in folder_path.glob("error-*.jpg"):
                    if item.is_file():
                        timestamp = parse_timestamp_from_filename(item.name)
                        if timestamp is not None and timestamp > 0:
                            files_to_delete.append({'path': item, 'timestamp': timestamp, 'size': item.stat().st_size})

                # Sort files by timestamp (oldest first)
                files_to_delete.sort(key=lambda x: x['timestamp'])

                # Start deleting files
                deleted_count = 0
                size_after_deletion = current_size
                for file_info in files_to_delete:
                    if size_after_deletion <= max_size_bytes:
                        break  # Stop deleting if size is now below threshold

                    try:
                        file_path = file_info['path']
                        file_size = file_info['size']
                        file_path.unlink()  # Delete the file
                        size_after_deletion -= file_size
                        deleted_count += 1
                        logger.info(f"Folder Watcher: Deleted oldest file: {file_path.name} (Size: {file_size} bytes)")
                    except Exception as e:
                        logger.error(f"Folder Watcher: Error deleting file {file_info['path'].name}: {e}")

                if deleted_count > 0:
                    logger.info(f"Folder Watcher: Cleanup finished. Deleted {deleted_count} files. New folder size: {size_after_deletion / (1024 * 1024):.2f} MB")
                else:
                    logger.info(f"Folder Watcher: Cleanup attempted but no files were deleted (or size still over limit).")

        except Exception as e:
            logger.exception(f"Folder Watcher: An error occurred in monitoring loop: {e}")

        # Wait for the next check interval or until stop_event is set
        stop_event.wait(timeout=check_interval)

    logger.info("Folder Watcher: Thread stopping.")
    return None
