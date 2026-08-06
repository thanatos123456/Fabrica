# Fabrica 公共基础设施模块详细设计文档

---

## 1. 模块概述

### 1.1 职责定位

公共基础设施模块是 Fabrica 系统的**底层支撑层**，为平台核心和所有工具提供通用的基础设施能力。核心职责：

- **日志系统**：统一的日志记录、格式化和轮转策略
- **设备检测**：自动检测 CPU/GPU 可用性，为工具提供设备选择
- **路径工具**：平台无关的路径操作，临时目录和数据目录管理
- **工具函数**：通用的辅助函数，如时间格式化、文件大小格式化、哈希计算等

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **零外部依赖** | 基础设施模块只依赖 Python 标准库和 loguru，不依赖平台其他模块 |
| **平台无关** | 所有路径使用 `pathlib.Path`，换行符/编码处理兼容 Windows/Linux |
| **延迟初始化** | 日志系统、设备检测等使用延迟初始化，避免 import 时产生副作用 |
| **配置驱动** | 日志级别、目录等通过配置控制，无需修改代码 |
| **静默降级** | 设备检测失败时静默降级到 CPU，不抛出异常 |

---

## 2. 模块代码结构

```
fabrica/utils/
├── __init__.py              # 模块导出
├── logger.py                # 日志系统（基于 loguru）
├── device.py                # 设备检测（CPU/GPU）
└── helpers.py               # 工具函数
```

**模块内部依赖关系：**

```
utils 模块（零外部依赖，仅引用标准库）
    ├── logger.py
    │   └── 依赖: loguru（第三方库）
    │
    ├── device.py
    │   └── 依赖: torch（可选，import 失败时降级）
    │
    └── helpers.py
        └── 依赖: pathlib, hashlib（标准库）
```

**被依赖关系：**

```
平台核心模块（tool.py）       各工具模块（video_dedup 等）
    └── 依赖 utils/logger        └── 依赖 utils/logger
    └── 依赖 utils/helpers            └── 依赖 utils/device
```

---

## 3. 各组件详细设计

### 3.1 Logger — 日志系统

**文件：** `fabrica/utils/logger.py`

**职责：** 提供统一的日志记录能力，支持文件日志和控制台日志，自动轮转，上下文注入。

#### 3.1.1 核心接口

| 接口名 | 参数 | 返回类型 | 说明 |
|--------|------|----------|------|
| **setup_logger(level, log_dir, rotation, retention)** | str, str, str, str | None | 初始化日志系统，配置日志级别、目录、轮转和保留策略 |
| **get_logger(name)** | str | Logger | 获取指定名称的日志记录器实例 |
| **data_logger** | — | Logger | 全局数据日志记录器（模块级单例） |

#### 3.1.2 日志级别

| 级别 | 数值 | 使用场景 |
|------|------|---------|
| `DEBUG` | 10 | 调试信息，开发环境使用 |
| `INFO` | 20 | 正常操作信息，如任务创建、执行完成 |
| `WARNING` | 30 | 警告信息，如工具加载失败、参数校验未通过 |
| `ERROR` | 40 | 错误信息，如任务执行异常、配置加载失败 |

#### 3.1.3 日志格式

```
2026-08-02 14:30:00.123 | INFO     | fabrica.tools.video_dedup - 开始抽帧: video_001.mp4
```

格式组成：`时间 | 级别 | 模块名 - 消息内容`

#### 3.1.4 日志轮转策略

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `rotation` | `"1 day"` | 每天轮转一次 |
| `retention` | `"30 days"` | 保留 30 天的日志 |

#### 3.1.5 实现要点

```python
from loguru import logger

_logger_initialized = False

def setup_logger(
    level: str = "INFO",
    log_dir: str = "logs",
    rotation: str = "1 day",
    retention: str = "30 days",
) -> None:
    """初始化日志系统"""
    global _logger_initialized
    if _logger_initialized:
        return

    log_path = Path(log_dir) / "fabrica_{time:YYYY-MM-DD}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # 移除默认控制台处理器
    logger.remove()

    # 添加控制台处理器（彩色输出）
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan> - <level>{message}</level>",
        level=level.upper(),
        colorize=True,
    )

    # 添加文件处理器（自动轮转）
    logger.add(
        str(log_path),
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name} - {message}",
        level=level.upper(),
        rotation=rotation,
        retention=retention,
        encoding="utf-8",
    )

    _logger_initialized = True


def get_logger(name: str = "fabrica"):
    """获取指定名称的日志记录器"""
    return logger.bind(name=name)


# 为 data_logger 绑定额外上下文
data_logger = logger.bind(source="data")
```

### 3.2 DeviceDetector — 设备检测

**文件：** `fabrica/utils/device.py`

**职责：** 自动检测可用计算设备（CPU/GPU），提供统一的设备选择接口，支持手动指定。

#### 3.2.1 核心接口

| 接口名 | 参数 | 返回类型 | 说明 |
|--------|------|----------|------|
| **get_device(prefer)** | str | str | 获取计算设备，`prefer="auto"` 时自动检测 |
| **get_device_info()** | — | dict | 获取设备详细信息 |
| **is_cuda_available()** | — | bool | 检查 CUDA 是否可用 |
| **get_batch_size_hint()** | — | int | 根据设备返回建议的 batch_size |

#### 3.2.2 实现要点

```python
import torch

def get_device(prefer: str = "auto") -> str:
    """
    获取计算设备。

    Args:
        prefer: "auto" 自动检测 / "cpu" 强制 CPU / "cuda" 强制 CUDA

    Returns:
        "cuda" 或 "cpu"
    """
    if prefer == "cpu":
        return "cpu"
    if prefer == "cuda":
        return "cuda" if torch.cuda.is_available() else "cpu"
    # auto: 自动检测
    return "cuda" if torch.cuda.is_available() else "cpu"

def get_device_info() -> dict:
    """获取设备详细信息"""
    info = {
        "device": get_device(),
        "cuda_available": torch.cuda.is_available(),
    }
    if info["cuda_available"]:
        info["cuda_device_count"] = torch.cuda.device_count()
        info["cuda_device_name"] = torch.cuda.get_device_name(0)
        info["cuda_version"] = torch.version.cuda
    return info

def get_batch_size_hint() -> int:
    """根据设备返回建议的 batch_size"""
    if get_device() == "cuda":
        return 64  # GPU 可处理更大的 batch
    return 16     # CPU 用小 batch 防止 OOM
```

#### 3.2.3 设备信息示例

```json
{
    "device": "cuda",
    "cuda_available": true,
    "cuda_device_count": 1,
    "cuda_device_name": "NVIDIA GeForce RTX 4090",
    "cuda_version": "12.1"
}
```

### 3.3 PathUtils — 路径工具

**文件：** `fabrica/utils/helpers.py`（PathUtils 部分）

**职责：** 提供平台无关的路径操作，确保 Linux 开发环境与 Windows 部署环境的一致性。

#### 3.3.1 核心接口

| 接口名 | 参数 | 返回类型 | 说明 |
|--------|------|----------|------|
| **get_temp_dir(base_dir, prefix)** | str, str | Path | 创建并返回临时目录路径 |
| **get_data_dir(base_dir, tool_name)** | str, str | Path | 获取工具持久化数据目录 |
| **ensure_dir(path)** | str/Path | Path | 确保目录存在，不存在则创建 |
| **safe_filename(filename)** | str | str | 清理文件名，移除非法字符 |

#### 3.3.2 实现要点

```python
from pathlib import Path
import tempfile
import re
import uuid

def get_temp_dir(base_dir: str = "data/tmp", prefix: str = "") -> Path:
    """创建并返回临时目录"""
    temp_base = Path(base_dir)
    temp_base.mkdir(parents=True, exist_ok=True)
    dir_name = f"{prefix}{uuid.uuid4().hex[:8]}" if prefix else uuid.uuid4().hex[:12]
    temp_dir = temp_base / dir_name
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir

def get_data_dir(base_dir: str = "data/tools", tool_name: str = "unknown") -> Path:
    """获取工具持久化数据目录"""
    data_dir = Path(base_dir) / tool_name
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir

def ensure_dir(path: str | Path) -> Path:
    """确保目录存在"""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p

def safe_filename(filename: str) -> str:
    """清理文件名，移除 Windows/Linux 上的非法字符"""
    # Windows 非法字符: \ / : * ? " < > |
    safe = re.sub(r'[\\/*?:"<>|]', "_", filename)
    # 去除首尾空白和点
    return safe.strip(". ")
```

### 3.4 Helpers — 工具函数

**文件：** `fabrica/utils/helpers.py`

**职责：** 提供通用的辅助函数，减少重复代码。

#### 3.4.1 核心接口

| 接口名 | 参数 | 返回类型 | 说明 |
|--------|------|----------|------|
| **format_size(bytes)** | int | str | 格式化文件大小（如 "1.5 GB"） |
| **format_duration(seconds)** | float | str | 格式化时间（如 "1h 23m 45s"） |
| **format_timestamp(dt)** | datetime | str | 格式化时间戳（ISO 8601） |
| **compute_file_hash(path, algo)** | str, str | str | 计算文件哈希（默认 md5） |
| **chunked(iterable, size)** | iterable, int | generator | 将可迭代对象分块处理 |

#### 3.4.2 实现要点

```python
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Iterator, Any

def format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"

def format_duration(seconds: float) -> str:
    """格式化时间间隔"""
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    parts = []
    if h > 0: parts.append(f"{h}h")
    if m > 0: parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)

def format_timestamp(dt: datetime | None = None) -> str:
    """格式化时间戳"""
    dt = dt or datetime.now()
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def compute_file_hash(path: str | Path, algo: str = "md5") -> str:
    """计算文件哈希"""
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):  # 1MB 分块
            h.update(chunk)
    return h.hexdigest()

def chunked(iterable: Iterator[Any], size: int) -> Iterator[list[Any]]:
    """将可迭代对象分批处理"""
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
```

---

## 4. 配置项

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `fabrica.logging.level` | str | `"INFO"` | 日志级别：DEBUG / INFO / WARNING / ERROR |
| `fabrica.logging.dir` | str | `"logs"` | 日志文件目录 |
| `fabrica.logging.rotation` | str | `"1 day"` | 日志轮转周期 |
| `fabrica.logging.retention` | str | `"30 days"` | 日志保留时间 |
| `fabrica.storage.temp_dir` | str | `"data/tmp"` | 临时文件目录 |
| `fabrica.storage.data_dir` | str | `"data/tools"` | 工具持久化数据目录 |

---

## 5. 模块关系

| 依赖方向 | 消费者 | 使用组件 | 说明 |
|----------|--------|---------|------|
| 基础设施 → 标准库 | logger.py | logging, sys | 日志系统 |
| 基础设施 → 标准库 | helpers.py | hashlib, pathlib, datetime | 工具函数 |
| 基础设施 → 第三方库 | logger.py | loguru | 日志框架 |
| 基础设施 → 第三方库 | device.py | torch（可选） | 设备检测 |
| 平台核心 → 基础设施 | tool.py | logger, helpers | 日志和工具函数 |
| 工具 → 基础设施 | video_dedup | logger, device | 日志和设备检测 |

---

## 6. 扩展与迭代

### 6.1 添加新的日志处理器

在 `setup_logger()` 中添加新的 `logger.add()` 调用即可：

```python
# 添加 JSON 格式日志处理器（用于日志分析）
logger.add(
    "logs/structured.json",
    serialize=True,  # JSON 序列化
    level="INFO",
    rotation="1 day",
)
```

### 6.2 添加新的工具函数

在 `helpers.py` 中添加新的函数，遵循以下规范：
- 函数应为纯函数，无副作用
- 添加类型注解和文档字符串
- 在 `__init__.py` 中导出

### 6.3 未来迭代计划

| 迭代项 | 描述 | 优先级 |
|-------|------|--------|
| 性能计数器 | 添加 `@timed()` 装饰器用于性能统计 | P2 |
| 配置校验 | 使用 pydantic 对配置进行类型校验 | P1 |
| 环境检测 | 添加操作系统版本、Python 版本等环境信息检测 | P2 |
| 错误码标准化 | 统一基础设施层的错误码和异常类型 | P3 |