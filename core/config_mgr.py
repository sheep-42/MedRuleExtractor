import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class ConfigManager:
    _instance = None
    _config: Dict[str, Any] = {}
    _loaded_path: Optional[str] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
        return cls._instance

    def load_config(self, config_path: str) -> Dict[str, Any]:
        """
        加载YAML配置。如果路径相同且已加载，直接返回缓存。
        """
        if self._config and self._loaded_path == config_path:
            return self._config

        path_obj = Path(config_path)
        if not path_obj.exists():
            logger.error(f"配置文件未找到: {config_path}")
            raise FileNotFoundError(f"Config file not found: {config_path}")

        try:
            with open(path_obj, 'r', encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
                self._loaded_path = config_path
                logger.debug(f"已加载配置文件: {config_path}")
                return self._config
        except yaml.YAMLError as e:
            logger.error(f"解析配置文件失败: {e}", exc_info=True)
            raise

# 全局单例辅助函数
def load_global_config(config_path: str) -> Dict[str, Any]:
    return ConfigManager().load_config(config_path)