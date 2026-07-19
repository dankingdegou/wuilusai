import struct

from wuliusai_stepper_controller.protocol import (
    CMD_MOVE_SYNC, CMD_STATUS, STATUS_DONE, FrameParser, StepperSerial, crc8, make_frame,
)


def test_crc_and_frame_round_trip():
    frame = make_frame(0x11, bytes(range(15)))
    assert frame[:2] == b"\xaa\x55"
    assert crc8(frame[2:-1]) == frame[-1]
    parser = FrameParser()
    assert parser.feed(frame[:4]) == []
    assert parser.feed(frame[4:]) == [(0x11, bytes(range(15)))]


def test_parser_discards_noise_and_bad_crc():
    parser = FrameParser()
    good = make_frame(CMD_STATUS, b"\x00\x01\x02\x00\x03\x00\x00\x00")
    bad = good[:-1] + b"\x00"
    assert parser.feed(b"noise" + bad + good) == [(CMD_STATUS, good[4:-1])]


def test_synchronized_gantry_frame_payload_fits_firmware_limit():
    payload = struct.pack("<iiIIH", 1200, -1200, 800, 2000, 42)
    frame = make_frame(CMD_MOVE_SYNC, payload)
    assert len(payload) == 18
    assert FrameParser().feed(frame) == [(CMD_MOVE_SYNC, payload)]


def test_state_wait_accepts_latest_nonzero_request_id():
    transport = StepperSerial("unused")
    payload = struct.pack("<BBHI", 0, STATUS_DONE, 301, 1600)
    transport._handle_frame(CMD_STATUS, payload)
    status = transport.wait_axis_status(0, {STATUS_DONE}, 0.01)
    assert status.request_id == 301
    assert status.executed_steps == 1600
