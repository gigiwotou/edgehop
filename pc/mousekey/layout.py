"""屏幕布局：只描述主机左右两侧的从机，用于判断从哪个边缘切出。"""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Machine:
    id: int
    name: str
    width: int = 0
    height: int = 0
    master: bool = False


@dataclass
class Layout:
    machines: list = field(default_factory=list)

    def __post_init__(self):
        masters = [m for m in self.machines if m.master]
        if len(masters) != 1:
            raise ValueError("配置里必须且只能有一个 master 机器")
        self.master = masters[0]
        index = self.machines.index(self.master)
        self.left = self.machines[index - 1] if index > 0 else None
        self.right = self.machines[index + 1] if index < len(self.machines) - 1 else None

    def by_id(self, machine_id: int):
        for m in self.machines:
            if m.id == machine_id:
                return m
        return None


def load_config(path) -> tuple:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    machines = [Machine(**item) for item in data["machines"]]
    return data.get("hub_port"), Layout(machines)
