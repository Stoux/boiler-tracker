from datetime import datetime
from typing import Optional, Tuple
from loguru import logger
from zoneinfo import ZoneInfo

from lib.history import HistoricalStatus

def serve_grid_page(last_status: Optional[HistoricalStatus], base_url: str, loaded_from_disk: bool = False) -> Tuple[str, int, dict]:
    """
    Generate a grid page showing original and annotated frames side by side.

    Args:
        last_status: The last boiler status
        base_url: The base URL for image links
        loaded_from_disk: Whether the status was loaded from disk

    Returns:
        Tuple containing:
        - HTML content (str)
        - HTTP status code (int)
        - Headers dictionary (dict)
    """
    try:
        # Define common headers
        headers = {
            'Content-type': 'text/html',
            'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
            'Pragma': 'no-cache',
            'Expires': '0'
        }

        if not last_status:
            return 'No images available', 404, {
                'Content-type': 'text/plain',
                'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
                'Pragma': 'no-cache',
                'Expires': '0'
            }

        timestamp_str = last_status.timestamp_str

        # Convert timestamp to Europe/Amsterdam timezone and format for display
        amsterdam_time = last_status.timestamp.astimezone(ZoneInfo("Europe/Amsterdam"))
        formatted_time = amsterdam_time.strftime("%Y-%m-%d %H:%M:%S %Z")

        # Generate preload tags for all images
        preload_tags = ""

        # Add preload tags for standard frames
        if last_status.frames:
            for i in range(len(last_status.frames.annotated)):
                original_url = f"{base_url}/images/frames/original/{timestamp_str}-{i}.webp"
                annotated_url = f"{base_url}/images/frames/{timestamp_str}-{i}.webp"
                preload_tags += f'<link rel="preload" href="{original_url}" as="image" type="image/webp">\n'
                preload_tags += f'<link rel="preload" href="{annotated_url}" as="image" type="image/webp">\n'

        # Add preload tags for frequency frames if available
        if last_status.frequency and last_status.frequency.original:
            for i in range(len(last_status.frequency.original)):
                original_url = f"{base_url}/images/frequency/original/{timestamp_str}-{i}.webp"
                annotated_url = f"{base_url}/images/frequency/{timestamp_str}-{i}.webp"
                preload_tags += f'<link rel="preload" href="{original_url}" as="image" type="image/webp">\n'
                preload_tags += f'<link rel="preload" href="{annotated_url}" as="image" type="image/webp">\n'

        # Generate HTML content
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Boiler Images Grid</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            {preload_tags}
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .grid-container {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
                .grid-row {{ display: contents; }}
                .grid-item {{ text-align: center; }}
                img {{ max-width: 100%; border: 1px solid #ddd; }}
                .button {{
                    display: inline-block;
                    padding: 10px 20px;
                    background-color: #4CAF50;
                    color: white;
                    text-align: center;
                    text-decoration: none;
                    font-size: 16px;
                    margin: 10px 0;
                    cursor: pointer;
                    border: none;
                    border-radius: 4px;
                }}
                .button:hover {{
                    background-color: #45a049;
                }}
                .header {{
                    margin-bottom: 20px;
                }}
                .status-details {{
                    margin: 10px 0;
                    font-size: 16px;
                }}
                .status-timestamp {{
                    font-weight: bold;
                }}
                .heating-on {{ color: green; }}
                .heating-off {{ color: red; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Boiler Images Grid</h1>

                <div class="status-details">
                    <div class="status-timestamp">Timestamp: {formatted_time}</div>
                    <div>
                        <span>Lights: {last_status.lights_on}</span> | 
                        <span class="{last_status.heating and 'heating-on' or 'heating-off'}">
                            Heating: {last_status.heating and 'Yes' or 'No'}
                        </span> | 
                        <span>General Light: {last_status.general_light_on and 'On' or 'Off'}</span>
                    </div>
                </div>

                <p style="margin: 10px 0; font-size: 16px;">
                    <span style="padding: 5px 10px; border-radius: 4px; background-color: {loaded_from_disk and '#f0ad4e' or '#5bc0de'}; color: white;">
                        {loaded_from_disk and 'Loaded from disk' or 'Loaded from memory'}
                    </span>
                </p>
                <a href="{base_url}/images/save_snapshot/{timestamp_str}" class="button">Save snapshot to disk</a>
                {loaded_from_disk and f'<a href="{base_url}/images/delete_snapshot/{timestamp_str}" class="button" style="background-color: #d9534f;">Delete snapshot from disk</a>' or ''}
            </div>
        """

        # Add standard frames to the grid
        if last_status.frames:
            html_content += """
            <h2>Standard Frames</h2>
                <div class="grid-container">
            """
            for i in range(len(last_status.frames.annotated)):
                # Use the global base_url for image URLs
                original_url = f"{base_url}/images/frames/original/{timestamp_str}-{i}.webp"
                annotated_url = f"{base_url}/images/frames/{timestamp_str}-{i}.webp"
                html_content += f"""
                <div class="grid-row">
                    <div class="grid-item">
                        <img src="{original_url}" alt="Original Frame {i}">
                    </div>
                    <div class="grid-item">
                        <img src="{annotated_url}" alt="Annotated Frame {i}">
                    </div>
                </div>
                """
            html_content += """
            </div>
            """

        # Add frequency frames to the grid if available
        if last_status.frequency and last_status.frequency.original:
            html_content += """
            <h2>Frequency Frames</h2>
            <div class="grid-container">
            """

            for i in range(len(last_status.frequency.original)):
                # Use the global base_url for image URLs
                original_url = f"{base_url}/images/frequency/original/{timestamp_str}-{i}.webp"
                annotated_url = f"{base_url}/images/frequency/{timestamp_str}-{i}.webp"
                html_content += f"""
                <div class="grid-row">
                    <div class="grid-item">
                        <img src="{original_url}" alt="Original Frequency Frame {i}">
                    </div>
                    <div class="grid-item">
                        <img src="{annotated_url}" alt="Annotated Frequency Frame {i}">
                    </div>
                </div>
                """
            html_content += """
            </div>
            """

        html_content += """
        </body>
        </html>
        """

        # Return the HTML content, status code, and headers
        return html_content, 200, headers
    except Exception as e:
        logger.error(f"Error serving grid page: {e}")
        error_headers = {
            'Content-type': 'text/plain',
            'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
            'Pragma': 'no-cache',
            'Expires': '0'
        }
        return f"Server error: {str(e)}", 500, error_headers
