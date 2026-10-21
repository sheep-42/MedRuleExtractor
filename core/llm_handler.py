import logging
from typing import Dict, Any, List, Union, Optional
from openai import OpenAI, APIError
import json_repair
from .file_handler import TextUtils

logger = logging.getLogger(__name__)

class LLMHandler:
    def __init__(self, config: Dict[str, Any], phase: str = 'model_phase1'):
        """
        初始化 OpenAI 客户端
        :param config: 全局配置字典，应包含 ['openai'] 部分
        """
        openai_cfg = config.get('openai', {})
        self.client = OpenAI(
            base_url=openai_cfg.get('base_url'),
            api_key=openai_cfg.get('api_key')
        )
        self.default_model = openai_cfg.get(phase)  # 默认模型

    def chat_completion_json(
        self,
        prompt: str,
        system_prompt: str = "你是专业的医学助手。",
        model: Optional[str] = None,
        expected_type: type = dict,
        temperature: float = 0.1,
        fallback_data: Optional[Dict[str, Any]] = None
    ) -> Union[Dict[str, Any], List[Any]]:
        """
        执行 ChatCompletion 并使用 json_repair 解析结果。
        
        :param expected_type: 期望返回的类型 (dict 或 list)
        :param fallback_data: 发生错误时，将此数据合并到错误返回中
        """
        model_name = model or self.default_model
        
        try:
            response = self.client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                extra_body={"enable_thinking": False},
                temperature=temperature,
                max_tokens=16384,
                response_format={'type': 'json_object'} 
            )
            
            content = response.choices[0].message.content
            logger.debug(f"LLM 原始响应 (前100字符): {content[:100]}...")
            
            return self._robust_json_parse(content, expected_type, fallback_data)

        except APIError as e:
            logger.error(f"OpenAI API 调用失败: {e}", exc_info=True)
            return self._create_error_response("API Error", str(e), None, fallback_data)
        except Exception as e:
            logger.error(f"未知错误: {e}", exc_info=True)
            return self._create_error_response("Unknown Error", str(e), None, fallback_data)

    def _robust_json_parse(
        self, 
        content: str, 
        expected_type: type, 
        fallback_data: Dict[str, Any] = None
    ) -> Any:
        """内部方法：使用 json_repair 进行健壮解析"""
        
        # 1. 预处理：先尝试提取 Markdown 代码块
        # json_repair 虽然强大，但如果 LLM 在 JSON 外输出了大量文本，提取一下更安全
        cleaned_content = TextUtils.extract_json_block(content)
        
        # 2. 解析与修复
        try:
            # json_repair.loads 会自动处理 JSONDecodeError 并尝试修复
            # 它是 json.loads 的 drop-in replacement
            data = json_repair.loads(cleaned_content)
        except Exception as e:
            logger.error(f"JSON Repair 解析彻底失败: {e}")
            logger.error(f"问题内容: {content}")
            return self._create_error_response("JSON Decode Error", str(e), content, fallback_data)

        # 3. 类型检查与适配 (处理 List/Dict 混淆的情况)
        if expected_type == list:
            if isinstance(data, list):
                # 过滤掉列表中非 dict 的元素（增强健壮性）
                return [x for x in data if isinstance(x, dict)]
            elif isinstance(data, dict):
                logger.warning("期望列表但 LLM 返回了字典，已自动包装为列表。")
                return [data]
            else:
                logger.warning(f"期望列表但 LLM 返回了 {type(data)}，返回空列表。")
                return []
        
        elif expected_type == dict:
            if isinstance(data, dict):
                return data
            elif isinstance(data, list):
                if len(data) > 0 and isinstance(data[0], dict):
                    logger.warning("期望字典但 LLM 返回了列表，取第一个元素。")
                    return data[0]
                return self._create_error_response("Type Mismatch", "Got empty list instead of dict", content, fallback_data)
            else:
                return self._create_error_response("Type Mismatch", f"Expected dict, got {type(data)}", content, fallback_data)
        
        return data

    def _create_error_response(self, error_type: str, details: str, raw_response: str, fallback: Dict) -> Dict:
        """构造标准化的错误返回结构"""
        err_obj = {
            "error": error_type,
            "error_details": details,
            "raw_response": raw_response
        }
        if fallback:
            # 浅拷贝避免修改原字典
            fb = fallback.copy()
            fb["错误信息"] = err_obj
            return fb
        return err_obj