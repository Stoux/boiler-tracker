from dataclasses import dataclass
from datetime import datetime
from collections import deque
from typing import Dict, List, Optional, OrderedDict

import cv2

from lib.analyze import BoilerStatus, FrameData

@dataclass
class HistoricalImageSet:
    annotated: Dict[str, bytes]
    original: Dict[str, bytes]


@dataclass
class HistoricalStatus:
    """A historical boiler status with its timestamp."""
    # Whether the boiler is currently heating
    heating: bool
    # The number of lights that are currently on (1-4)
    lights_on: int
    # Whether the general (room) light is currently on
    general_light_on: bool
    timestamp: datetime
    # Timestamp as a string for image keys
    timestamp_str: str
    # List of jpg encoded frames
    frames: HistoricalImageSet
    frequency: HistoricalImageSet


class StatusHistory:
    """Maintains a history of boiler statuses."""
    def __init__(self, max_size: int = 50):
        self.history: OrderedDict[str, HistoricalStatus] = OrderedDict()
        self.max_size = max_size
        self.last: HistoricalStatus|None = None
        self.last_timestamp_str: str|None = None

    def _status_differs_from_previous(self, status: BoilerStatus) -> bool:
        """Check if the status differs from the previous one on heating, lights_on, or general_light_on."""
        if not self.history:  # If history is empty, always add the status
            return True

        previous_status_key = list(self.history.keys())[0]
        previous_status = self.history[previous_status_key]

        return (previous_status.heating != status.heating or
                previous_status.lights_on != status.lights_on or
                previous_status.general_light_on != status.general_light_on)

    def add_status(self, status: BoilerStatus, timestamp: datetime, timestamp_str: str) -> None:
        """Store the status in memory & add to history if differs fromt he last entry."""
        # Convert into historical entry
        historical_status = HistoricalStatus(
            heating=status.heating,
            lights_on=status.lights_on,
            general_light_on=status.general_light_on,
            timestamp=timestamp,
            timestamp_str=timestamp_str,
            frames=self.build_images_from_frames(status.frames),
            frequency=self.build_images_from_frames(status.frequency_frames),
        )

        self.last = historical_status
        self.last_timestamp_str = timestamp_str

        if self._status_differs_from_previous(status):
            # Add to the dictionary
            self.history[timestamp_str] = historical_status

            # Move it to the start of the dictionary
            self.history.move_to_end(timestamp_str, False)

            # Pop old entries if needed
            while len(self.history) > self.max_size:
                self.history.popitem(last=True)

    @staticmethod
    def build_images_from_frames(frames: List[FrameData] | None):
        """Build jpg images from the frames"""
        annotated: Dict[str, bytes] = {}
        originals: Dict[str, bytes] = {}
        if frames is None:
            return HistoricalImageSet(annotated=annotated, original=originals)

        # Loop through frames
        for i, frame_data in enumerate(frames):
            image_key = f"{i}"

            # Convert annotated frame to bytes
            is_success, buffer = cv2.imencode(".jpg", frame_data.annotated_frame)
            if is_success:
                annotated[image_key] = buffer.tobytes()

            # Convert original frame to bytes
            is_success, buffer = cv2.imencode(".jpg", frame_data.original_frame)
            if is_success:
                originals[image_key] = buffer.tobytes()

        return HistoricalImageSet(annotated=annotated, original=originals)

    def get_last(self) -> HistoricalStatus|None:
        return self.last

    def get_by_timestamp(self, timestamp_str: str) -> HistoricalStatus|None:
        if self.last_timestamp_str == timestamp_str:
            return self.last

        history_status = self.history[timestamp_str]
        if history_status is not None:
            return history_status

        return None


    def get_history(self) -> List[HistoricalStatus]:
        """Get the history as a list, newest first."""
        return list(self.history.values())

    def clear(self) -> None:
        """Clear the history."""
        self.history.clear()
