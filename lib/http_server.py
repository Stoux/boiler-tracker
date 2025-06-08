import threading
import os
import json
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
import re
from loguru import logger
from typing import Optional, Dict, List

from lib.analyze import BoilerStatus
from lib.history import StatusHistory, HistoricalImageSet, HistoricalStatus
from lib.http.pages.grid import serve_grid_page as generate_grid_page
from lib.http.pages.history import serve_history_page as generate_history_page

# Global variables to store the last status and timestamp
status_lock = threading.Lock()
base_url: str = ""  # Global variable to store the base URL

# Create a history of boiler statuses
status_history = StatusHistory(max_size=50)


class BoilerHTTPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Route for history view
        history_match = re.match(r'/images/history(?:\?show_saved=(\d+))?$', self.path)
        if history_match:
            show_saved = history_match.group(1) == '1'  # Will be True if show_saved=1, False otherwise
            self.serve_history_page(show_saved)
            return

        # Route for grid view
        grid_match = re.match(r'/images/grid(?:\?timestamp=(\d+))?$', self.path)
        if grid_match:
            timestamp_str = grid_match.group(1)  # Will be None if no timestamp parameter
            self.serve_grid_page(timestamp_str)
            return

        # Route for saving snapshot to disk
        save_snapshot_match = re.match(r'/images/save_snapshot/(\d+)$', self.path)
        if save_snapshot_match:
            timestamp_str = save_snapshot_match.group(1)
            self.save_snapshot(timestamp_str)
            return

        # Route for deleting snapshot from disk
        delete_snapshot_match = re.match(r'/images/delete_snapshot/(\d+)$', self.path)
        if delete_snapshot_match:
            timestamp_str = delete_snapshot_match.group(1)
            self.delete_snapshot(timestamp_str)
            return

        # Route for frequency frames
        frequency_match = re.match(r'/images/frequency/(\d+)-(\d+)\.png', self.path)
        if frequency_match:
            timestamp_str, index_str = frequency_match.groups()
            self.serve_image('frequency', timestamp_str, index_str)
            return

        # Route for standard frames
        frames_match = re.match(r'/images/frames/(\d+)-(\d+)\.png', self.path)
        if frames_match:
            timestamp_str, index_str = frames_match.groups()
            self.serve_image('frames', timestamp_str, index_str)
            return

        # Route for original frequency frames
        frequency_original_match = re.match(r'/images/frequency/original/(\d+)-(\d+)\.png', self.path)
        if frequency_original_match:
            timestamp_str, index_str = frequency_original_match.groups()
            self.serve_image('frequency', timestamp_str, index_str, is_original=True)
            return

        # Route for original standard frames
        frames_original_match = re.match(r'/images/frames/original/(\d+)-(\d+)\.png', self.path)
        if frames_original_match:
            timestamp_str, index_str = frames_original_match.groups()
            self.serve_image('frames', timestamp_str, index_str, is_original=True)
            return

        # Default response for unknown routes
        self.send_response(404)
        self.send_header('Content-type', 'text/plain')
        # Add no-cache headers
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.end_headers()
        self.wfile.write(b'Not Found')

    def serve_image(self, image_type: str, timestamp_str: str, index_str: str, is_original: bool = False):
        try:
            # Find the status with that timestamp
            image_data = None
            status = status_history.get_by_timestamp(timestamp_str)
            if status:
                image_set: Optional[HistoricalImageSet] = None
                if image_type == 'frames':
                   image_set = status.frames
                elif image_type == 'frequency':
                   image_set = status.frequency

                image_frames: Optional[Dict[str, bytes]] = None
                if image_set:
                   if is_original:
                       image_frames = image_set.original
                   else:
                       image_frames = image_set.annotated

                if image_frames:
                    image_data = image_frames.get(index_str)

            # If not in memory, check if it exists on disk
            if not image_data:
                # Determine the file path based on the image type and whether it's original
                save_dir = f"images/saved/{timestamp_str}"
                if os.path.exists(save_dir):
                    file_prefix = "frame" if image_type == 'frames' else "frequency"
                    file_suffix = "original" if is_original else "annotated"
                    file_path = f"{save_dir}/{file_prefix}_{index_str}_{file_suffix}.png"

                    # Check if the file exists
                    if os.path.exists(file_path):
                        with open(file_path, "rb") as f:
                            image_data = f.read()

            # Check if the image exists in memory or on disk
            if not image_data:
                self.send_response(404)
                self.send_header('Content-type', 'text/plain')
                # Add no-cache headers
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
                self.end_headers()
                self.wfile.write(b'Image not found')
                return

            # Set content type for PNG
            content_type = 'image/png'

            # Serve the image from memory
            self.send_response(200)
            self.send_header('Content-type', content_type)
            # Add no-cache headers
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.end_headers()
            self.wfile.write(image_data)
        except Exception as e:
            logger.error(f"Error serving {'original ' if is_original else ''}image: {e}")
            self.send_response(500)
            self.send_header('Content-type', 'text/plain')
            # Add no-cache headers
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.end_headers()
            self.wfile.write(f"Server error: {str(e)}".encode())

    def serve_history_page(self, show_saved=False):
        with status_lock:
            if show_saved:
                # Load all saved entries from disk
                saved_entries = self.load_all_snapshots_from_disk()
                logger.info(f"Saved {len(saved_entries)} entries | {show_saved}")
                generate_history_page(self, None, base_url, show_saved, saved_entries)
            else:
                generate_history_page(self, status_history, base_url, show_saved)

    def serve_grid_page(self, timestamp_str=None):
        with status_lock:
            loaded_from_disk = False
            if timestamp_str:
                # Get the status with the specified timestamp
                status = status_history.get_by_timestamp(timestamp_str)

                # If not in memory, check if it exists on disk
                if not status:
                    status = self.load_snapshot_from_disk(timestamp_str)
                    if status:
                        loaded_from_disk = True
            else:
                # Get the last status if no timestamp is specified
                status = status_history.get_last()

            generate_grid_page(self, status, base_url, loaded_from_disk)

    def save_snapshot(self, timestamp_str):
        """Save all frames and annotated frames of a timestamp to disk."""
        try:
            with status_lock:
                # Get the status with the specified timestamp
                status = status_history.get_by_timestamp(timestamp_str)

                if not status:
                    self.send_response(404)
                    self.send_header('Content-type', 'text/plain')
                    self.end_headers()
                    self.wfile.write(b'Status not found')
                    return

                # Create the directory if it doesn't exist
                save_dir = f"images/saved/{timestamp_str}"
                os.makedirs(save_dir, exist_ok=True)

                # Save frames
                if status.frames:
                    # Save annotated frames
                    for i, image_data in status.frames.annotated.items():
                        with open(f"{save_dir}/frame_{i}_annotated.png", "wb") as f:
                            f.write(image_data)

                    # Save original frames
                    for i, image_data in status.frames.original.items():
                        with open(f"{save_dir}/frame_{i}_original.png", "wb") as f:
                            f.write(image_data)

                # Save frequency frames if they exist
                if status.frequency:
                    # Save annotated frequency frames
                    for i, image_data in status.frequency.annotated.items():
                        with open(f"{save_dir}/frequency_{i}_annotated.png", "wb") as f:
                            f.write(image_data)

                    # Save original frequency frames
                    for i, image_data in status.frequency.original.items():
                        with open(f"{save_dir}/frequency_{i}_original.png", "wb") as f:
                            f.write(image_data)

                # Save info.json with all HistoricalStatus data
                info = {
                    "heating": status.heating,
                    "lights_on": status.lights_on,
                    "general_light_on": status.general_light_on,
                    "timestamp": status.timestamp.isoformat(),
                    "timestamp_str": status.timestamp_str,
                    "lower_green": status.lower_green.tolist() if status.lower_green is not None else None,
                    "upper_green": status.upper_green.tolist() if status.upper_green is not None else None,
                    "frames": {
                        "annotated": [f"frame_{i}_annotated.png" for i in status.frames.annotated.keys()],
                        "original": [f"frame_{i}_original.png" for i in status.frames.original.keys()]
                    }
                }

                if status.frequency:
                    info["frequency"] = {
                        "annotated": [f"frequency_{i}_annotated.png" for i in status.frequency.annotated.keys()],
                        "original": [f"frequency_{i}_original.png" for i in status.frequency.original.keys()]
                    }

                with open(f"{save_dir}/info.json", "w") as f:
                    json.dump(info, f, indent=2)

                # Redirect back to the grid page
                self.send_response(302)
                self.send_header('Location', f"{base_url}/images/grid?timestamp={timestamp_str}")
                self.end_headers()

        except Exception as e:
            logger.error(f"Error saving snapshot: {e}")
            self.send_response(500)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(f"Server error: {str(e)}".encode())

    def delete_snapshot(self, timestamp_str):
        """Delete a snapshot from disk."""
        try:
            save_dir = f"images/saved/{timestamp_str}"

            # Check if the directory exists
            if not os.path.exists(save_dir):
                self.send_response(404)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Snapshot not found')
                return

            # Delete all files in the directory
            for filename in os.listdir(save_dir):
                file_path = os.path.join(save_dir, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)

            # Remove the directory
            os.rmdir(save_dir)

            # Redirect back to the history page with show_saved=1
            self.send_response(302)
            self.send_header('Location', f"{base_url}/images/history?show_saved=1")
            self.end_headers()

        except Exception as e:
            logger.error(f"Error deleting snapshot: {e}")
            self.send_response(500)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(f"Server error: {str(e)}".encode())

    def load_all_snapshots_from_disk(self):
        """Load all snapshots from disk."""
        saved_entries = []

        # Check if the saved directory exists
        if not os.path.exists("images/saved"):
            return saved_entries

        # Get all subdirectories in the saved directory
        for timestamp_str in os.listdir("images/saved"):
            # Check if it's a directory
            if os.path.isdir(f"images/saved/{timestamp_str}"):
                # Load the snapshot
                snapshot = self.load_snapshot_from_disk(timestamp_str)
                if snapshot:
                    saved_entries.append(snapshot)

        # Sort by timestamp (newest first)
        saved_entries.sort(key=lambda x: x.timestamp, reverse=True)
        return saved_entries

    def load_snapshot_from_disk(self, timestamp_str):
        """Load a snapshot from disk if it exists."""
        try:
            save_dir = f"images/saved/{timestamp_str}"

            # Check if the directory exists
            if not os.path.exists(save_dir):
                return None

            # Check if info.json exists
            info_path = f"{save_dir}/info.json"
            if not os.path.exists(info_path):
                return None

            # Load info.json
            with open(info_path, "r") as f:
                info = json.load(f)

            # Create HistoricalImageSet for frames
            frames_annotated = {}
            frames_original = {}

            # Load annotated frames
            for i, frame_path in enumerate(info["frames"]["annotated"]):
                with open(f"{save_dir}/{frame_path}", "rb") as f:
                    frames_annotated[str(i)] = f.read()

            # Load original frames
            for i, frame_path in enumerate(info["frames"]["original"]):
                with open(f"{save_dir}/{frame_path}", "rb") as f:
                    frames_original[str(i)] = f.read()

            frames = HistoricalImageSet(annotated=frames_annotated, original=frames_original)

            # Create HistoricalImageSet for frequency frames if they exist
            frequency = None
            if "frequency" in info:
                frequency_annotated = {}
                frequency_original = {}

                # Load annotated frequency frames
                for i, frame_path in enumerate(info["frequency"]["annotated"]):
                    with open(f"{save_dir}/{frame_path}", "rb") as f:
                        frequency_annotated[str(i)] = f.read()

                # Load original frequency frames
                for i, frame_path in enumerate(info["frequency"]["original"]):
                    with open(f"{save_dir}/{frame_path}", "rb") as f:
                        frequency_original[str(i)] = f.read()

                frequency = HistoricalImageSet(annotated=frequency_annotated, original=frequency_original)

            # Convert lower_green and upper_green back to numpy arrays if they exist
            import numpy as np
            lower_green = np.array(info["lower_green"]) if info["lower_green"] is not None else None
            upper_green = np.array(info["upper_green"]) if info["upper_green"] is not None else None

            # Create HistoricalStatus
            from datetime import datetime
            timestamp = datetime.fromisoformat(info["timestamp"])

            return HistoricalStatus(
                heating=info["heating"],
                lights_on=info["lights_on"],
                general_light_on=info["general_light_on"],
                timestamp=timestamp,
                timestamp_str=info["timestamp_str"],
                frames=frames,
                frequency=frequency,
                lower_green=lower_green,
                upper_green=upper_green
            )

        except Exception as e:
            logger.error(f"Error loading snapshot from disk: {e}")
            return None

def update_status(status: BoilerStatus, url_prefix: str = None) -> bool:
    """Update the global status and timestamp, and store images in memory."""
    global base_url, status_history

    # Update base_url if provided
    if url_prefix:
        base_url = url_prefix

    # Generate timestamp
    current_time = datetime.now(timezone.utc)
    timestamp_str = str(int(current_time.timestamp()))

    with status_lock:
        # Add status to history
        return status_history.add_status(status, current_time, timestamp_str)

def get_image_urls() -> Dict[str, List[str]]:
    """Generate URLs for the latest images."""
    global base_url

    with status_lock:
        last_status = status_history.get_last()

        if not last_status:
            return {"frames": [], "frequency_frames": [], "frames_original": [], "frequency_frames_original": []}

        timestamp_str = last_status.timestamp_str

        # Generate URLs for standard frames (annotated versions)
        frame_urls = []
        frame_original_urls = []
        for i in range(len(last_status.frames.annotated)):
            frame_urls.append(f"{base_url}/images/frames/{timestamp_str}-{i}.png")
            frame_original_urls.append(f"{base_url}/images/frames/original/{timestamp_str}-{i}.png")

        # Generate URLs for frequency frames (annotated versions)
        frequency_urls = []
        frequency_original_urls = []
        for i in range(len(last_status.frequency.annotated)):
            frequency_urls.append(f"{base_url}/images/frequency/{timestamp_str}-{i}.png")
            frequency_original_urls.append(f"{base_url}/images/frequency/original/{timestamp_str}-{i}.png")

        # Add grid view URL
        grid_url = f"{base_url}/images/grid"

        # Add history view URL
        history_url = f"{base_url}/images/history"

        return {
            "frames": frame_urls,
            "frames_original": frame_original_urls,
            "frequency_frames": frequency_urls,
            "frequency_frames_original": frequency_original_urls,
            "grid": [grid_url],
            "history": [history_url]
        }


def start_http_server(port: int = 8800) -> HTTPServer:
    """Start the HTTP server in a separate thread."""
    server_address = ('', port)
    httpd = HTTPServer(server_address, BoilerHTTPHandler)

    # Start the server in a separate thread
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    logger.info(f"[HTTP] Server started on port {port}")
    return httpd
