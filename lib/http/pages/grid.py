from datetime import datetime
from typing import Optional
from http.server import BaseHTTPRequestHandler
from loguru import logger
from zoneinfo import ZoneInfo

from lib.history import HistoricalStatus


def serve_grid_page(handler: BaseHTTPRequestHandler, last_status: Optional[HistoricalStatus], base_url: str, loaded_from_disk: bool = False):
    """
    Serve a grid page showing original and annotated frames side by side.

    Args:
        handler: The HTTP request handler
        last_status: The last boiler status
        base_url: The base URL for image links
        loaded_from_disk: Whether the status was loaded from disk
    """
    try:
        if not last_status:
            handler.send_response(404)
            handler.send_header('Content-type', 'text/plain')
            # Add no-cache headers
            handler.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            handler.send_header('Pragma', 'no-cache')
            handler.send_header('Expires', '0')
            handler.end_headers()
            handler.wfile.write(b'No images available')
            return

        timestamp_str = last_status.timestamp_str

        # Convert timestamp to Europe/Amsterdam timezone and format for display
        amsterdam_time = last_status.timestamp.astimezone(ZoneInfo("Europe/Amsterdam"))
        formatted_time = amsterdam_time.strftime("%Y-%m-%d %H:%M:%S %Z")

        # Generate HTML content
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Boiler Images Grid</title>
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
                original_url = f"{base_url}/images/frames/original/{timestamp_str}-{i}.png"
                annotated_url = f"{base_url}/images/frames/{timestamp_str}-{i}.png"
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
                original_url = f"{base_url}/images/frequency/original/{timestamp_str}-{i}.png"
                annotated_url = f"{base_url}/images/frequency/{timestamp_str}-{i}.png"
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

        # Serve the HTML page
        handler.send_response(200)
        handler.send_header('Content-type', 'text/html')
        # Add no-cache headers
        handler.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        handler.send_header('Pragma', 'no-cache')
        handler.send_header('Expires', '0')
        handler.end_headers()
        handler.wfile.write(html_content.encode())
    except Exception as e:
        logger.error(f"Error serving grid page: {e}")
        handler.send_response(500)
        handler.send_header('Content-type', 'text/plain')
        # Add no-cache headers
        handler.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        handler.send_header('Pragma', 'no-cache')
        handler.send_header('Expires', '0')
        handler.end_headers()
        handler.wfile.write(f"Server error: {str(e)}".encode())
