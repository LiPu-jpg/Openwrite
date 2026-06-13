from __future__ import annotations

import os

from .config import AdapterConfig, ConfigError
from .runner import SmartStoryAdapterRunner


def main() -> int:
    try:
        config = AdapterConfig.from_env(os.environ)
    except ConfigError as exc:
        print(str(exc))
        return 78

    return SmartStoryAdapterRunner(config).run()
