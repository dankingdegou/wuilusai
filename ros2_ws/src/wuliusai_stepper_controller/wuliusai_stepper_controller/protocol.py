"""Serial protocol for the bjdj STM32 dual-axis stepper firmware."""

from __future__ import annotations

import struct
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import serial

HEADER = b"\xAA\x55"
CMD_INFO = 0x10
CMD_MOVE_AXIS = 0x11
CMD_STOP_AXIS = 0x12
CMD_GET_STATE = 0x13
CMD_MOVE_SYNC = 0x14
CMD_INFO_REPLY = 0x80
CMD_STATUS = 0x81
ALL_AXES = 0xFF

STATUS_ACCEPTED = 0x00
STATUS_DONE = 0x01
STATUS_ERROR = 0x02
STATUS_STOPPED = 0x03
STATUS_BUSY = 0x04
STATUS_READY = 0x10
STATUS_STATE = 0x20


def crc8(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = ((value << 1) ^ 0x07) & 0xFF if value & 0x80 else (value << 1) & 0xFF
    return value


def make_frame(command: int, payload: bytes = b"") -> bytes:
    if len(payload) > 24:
        raise ValueError("payload must be at most 24 bytes")
    body = bytes((command, len(payload))) + payload
    return HEADER + body + bytes((crc8(body),))


@dataclass(frozen=True)
class Status:
    axis: int
    code: int
    request_id: int
    executed_steps: int


class FrameParser:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[tuple[int, bytes]]:
        self._buffer.extend(data)
        frames: list[tuple[int, bytes]] = []
        while True:
            start = self._buffer.find(HEADER)
            if start < 0:
                self._buffer[:] = self._buffer[-1:]
                return frames
            if start:
                del self._buffer[:start]
            if len(self._buffer) < 5:
                return frames
            length = self._buffer[3]
            if length > 24:
                del self._buffer[0]
                continue
            total = 5 + length
            if len(self._buffer) < total:
                return frames
            raw = bytes(self._buffer[:total])
            del self._buffer[:total]
            if crc8(raw[2:-1]) == raw[-1]:
                frames.append((raw[2], raw[4:-1]))


class StepperSerial:
    """Thread-safe serial transport. Completion is reported asynchronously."""

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 0.1) -> None:
        self.port_name = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._port: Optional[serial.Serial] = None
        self._reader: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._parser = FrameParser()
        self._statuses: list[Status] = []
        self._status_event = threading.Event()
        self._info: Optional[tuple[int, int, int]] = None
        self._info_event = threading.Event()
        self.on_status: Optional[Callable[[Status], None]] = None

    @property
    def connected(self) -> bool:
        return self._port is not None and self._port.is_open

    def connect(self) -> tuple[int, int, int]:
        if self.connected:
            return self.query_info()
        self._port = serial.Serial(self.port_name, self.baudrate, timeout=self.timeout, write_timeout=1.0)
        self._running.set()
        self._reader = threading.Thread(target=self._read_loop, name="stepper-serial", daemon=True)
        self._reader.start()
        return self.query_info()

    def close(self) -> None:
        self._running.clear()
        if self._reader and self._reader is not threading.current_thread:
            self._reader.join(timeout=0.5)
        if self._port:
            self._port.close()
        self._port = None

    def _write(self, frame: bytes) -> None:
        if not self.connected:
            raise ConnectionError("stepper controller is disconnected")
        with self._write_lock:
            assert self._port is not None
            self._port.write(frame)
            self._port.flush()

    def _read_loop(self) -> None:
        try:
            while self._running.is_set() and self._port is not None:
                data = self._port.read(128)
                if not data:
                    continue
                for command, payload in self._parser.feed(data):
                    self._handle_frame(command, payload)
        except (serial.SerialException, OSError):
            self._running.clear()

    def _handle_frame(self, command: int, payload: bytes) -> None:
        if command == CMD_INFO_REPLY and len(payload) == 3:
            self._info = (payload[0], payload[1], payload[2])
            self._info_event.set()
        elif command == CMD_STATUS and len(payload) == 8:
            status = Status(payload[0], payload[1], struct.unpack_from("<H", payload, 2)[0],
                            struct.unpack_from("<I", payload, 4)[0])
            with self._state_lock:
                self._statuses.append(status)
            self._status_event.set()
            if self.on_status:
                self.on_status(status)

    def query_info(self, timeout: float = 1.0) -> tuple[int, int, int]:
        self._info = None
        self._info_event.clear()
        self._write(make_frame(CMD_INFO))
        if not self._info_event.wait(timeout) or self._info is None:
            raise TimeoutError("no protocol-info response from stepper controller")
        return self._info

    def move(self, axis: int, steps: int, max_pps: int, acceleration_pps2: int, request_id: int) -> None:
        payload = struct.pack("<BiIIH", axis, steps, max_pps, acceleration_pps2, request_id)
        self._write(make_frame(CMD_MOVE_AXIS, payload))

    def move_sync(self, steps_axis_0: int, steps_axis_1: int, max_pps: int,
                  acceleration_pps2: int, request_id: int) -> None:
        """Move both gantry rails from one STM32 command frame."""
        payload = struct.pack("<iiIIH", steps_axis_0, steps_axis_1, max_pps, acceleration_pps2, request_id)
        self._write(make_frame(CMD_MOVE_SYNC, payload))

    def stop(self, axis: int = ALL_AXES) -> None:
        self._write(make_frame(CMD_STOP_AXIS, bytes((axis,))))

    def request_state(self, axis: int = ALL_AXES) -> None:
        self._write(make_frame(CMD_GET_STATE, bytes((axis,))))

    def clear_statuses(self) -> None:
        """Discard queued asynchronous statuses before issuing a fresh query."""
        with self._state_lock:
            self._statuses.clear()
        self._status_event.clear()

    def wait_axis_status(self, axis: int, wanted: set[int], timeout: float) -> Status:
        """Return the next matching status for an axis, regardless of request id.

        GET_STATE reports the axis' latest motion request id, which is not
        necessarily zero after the first move.  State-query callers should use
        this method; motion completion callers should keep using wait_status().
        """
        deadline = time.monotonic() + timeout
        while True:
            with self._state_lock:
                for index, status in enumerate(self._statuses):
                    if status.axis == axis and status.code in wanted:
                        return self._statuses.pop(index)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for axis {axis} status")
            self._status_event.wait(min(remaining, 0.1))
            self._status_event.clear()

    def wait_status(self, axis: int, request_id: int, wanted: set[int], timeout: float) -> Status:
        deadline = time.monotonic() + timeout
        while True:
            with self._state_lock:
                for index, status in enumerate(self._statuses):
                    if status.axis == axis and status.request_id == request_id and status.code in wanted:
                        return self._statuses.pop(index)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for axis {axis} request {request_id}")
            self._status_event.wait(min(remaining, 0.1))
            self._status_event.clear()

    def wait_request_status(self, request_id: int, wanted: set[int], timeout: float) -> Status:
        """Return the next status for either axis with this request id."""
        deadline = time.monotonic() + timeout
        while True:
            with self._state_lock:
                for index, status in enumerate(self._statuses):
                    if status.request_id == request_id and status.code in wanted:
                        return self._statuses.pop(index)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for gantry request {request_id}")
            self._status_event.wait(min(remaining, 0.1))
            self._status_event.clear()
