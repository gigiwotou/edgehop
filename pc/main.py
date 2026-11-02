import argparse
import sys
from pathlib import Path

from mousekey.controller import Controller
from mousekey.input_capture import InputCapture
from mousekey.layout import load_config
from mousekey.serial_link import NullLink, SerialLink


def list_serial_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        print("缺少 pyserial，先执行: pip install -r requirements.txt")
        return
    for port in list_ports.comports():
        print(f"{port.device}\t{port.description}")


def main():
    if sys.platform != "win32":
        print("PC 端目前只支持 Windows")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="MouseKey 主机端")
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.json")))
    parser.add_argument("--port", help="覆盖配置里的串口，例如 COM5")
    parser.add_argument("--dry-run", action="store_true", help="不连串口，只打印报文")
    parser.add_argument("--list-ports", action="store_true", help="列出可用串口后退出")
    args = parser.parse_args()

    if args.list_ports:
        list_serial_ports()
        return

    port, layout = load_config(args.config)
    port = args.port or port
    if not port and not args.dry_run:
        print("没有配置串口，可用 --port COMx 指定，或先运行 --list-ports")
        sys.exit(1)

    link = NullLink() if args.dry_run else SerialLink(port)
    controller = Controller(link, layout)

    link.start()
    capture = InputCapture(controller.on_mouse, controller.on_key)
    capture.install()

    print(f"端口: {'dry-run' if args.dry_run else port}")
    print(f"主显示器: {controller.vw}x{controller.vh}")
    print(f"左侧: {layout.left.name if layout.left else '无'}，"
          f"右侧: {layout.right.name if layout.right else '无'}")
    print("鼠标移到左/右边缘自动切出；Ctrl+Alt+M 返回主机。Ctrl+C 退出。")

    try:
        capture.run()
    except KeyboardInterrupt:
        pass
    finally:
        controller.shutdown()
        capture.stop()
        link.close()
        print("已退出")


if __name__ == "__main__":
    main()
