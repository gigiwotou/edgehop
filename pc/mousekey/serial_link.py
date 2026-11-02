"""USB CDC 串口链路：后台线程负责写入，断线自动重连。"""

import queue
import sys
import threading
import time


class SerialLink:
    def __init__(self, port: str, baudrate: int = 115200, logger=print):
        self.port = port
        self.baudrate = baudrate
        self.logger = logger
        self._queue = queue.Queue(maxsize=256)
        self._stop = threading.Event()
        self._thread = None
        self._serial = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="serial-link", daemon=True)
        self._thread.start()

    def send(self, frame: bytes) -> None:
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            self._queue.get_nowait()
            self._queue.put_nowait(frame)

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        try:
            import serial
        except ImportError:
            self.logger("缺少 pyserial，先执行: pip install -r requirements.txt")
            sys.exit(1)

        retry_at = 0.0
        while not self._stop.is_set():
            if self._serial is None:
                if time.monotonic() < retry_at:
                    time.sleep(0.05)
                    continue
                try:
                    self._serial = serial.Serial(self.port, self.baudrate, timeout=0, write_timeout=0.05)
                    self.logger(f"已连接 {self.port}")
                except Exception as exc:
                    self.logger(f"打开 {self.port} 失败: {exc}")
                    retry_at = time.monotonic() + 1.0
                    continue

            try:
                frame = self._queue.get(timeout=0.005)
            except queue.Empty:
                continue

            try:
                self._serial.write(frame)
            except Exception as exc:
                self.logger(f"串口写入失败: {exc}")
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None
                retry_at = time.monotonic() + 1.0


class NullLink:
    """--dry-run 模式，只打印不发送。"""

    def __init__(self, logger=print):
        self.logger = logger

    def start(self) -> None:
        pass

    def send(self, frame: bytes) -> None:
        self.logger("frame " + " ".join(f"{b:02X}" for b in frame))

    def close(self) -> None:
        pass
