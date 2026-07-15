"""Direct serial smoke test; use only with motors safely unloaded."""
import argparse
import time

from .protocol import STATUS_ACCEPTED, STATUS_DONE, StepperSerial


def main() -> None:
    parser = argparse.ArgumentParser(description="bjdj dual-axis serial smoke test")
    parser.add_argument("--port", default="/dev/stepper_controller")
    parser.add_argument("--axis", type=int, choices=(0, 1), default=0)
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--pps", type=int, default=200)
    parser.add_argument("--accel", type=int, default=500)
    args = parser.parse_args()
    board = StepperSerial(args.port)
    try:
        print("info:", board.connect())
        request_id = 1
        board.move(args.axis, args.steps, args.pps, args.accel, request_id)
        print("ack:", board.wait_status(args.axis, request_id, {STATUS_ACCEPTED}, 1.0))
        print("done:", board.wait_status(args.axis, request_id, {STATUS_DONE}, max(3.0, abs(args.steps) / args.pps * 3)))
    except KeyboardInterrupt:
        board.stop(args.axis)
        time.sleep(0.1)
    finally:
        board.close()
