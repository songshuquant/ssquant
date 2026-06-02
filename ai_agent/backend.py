# -*- coding: utf-8 -*-
"""
SSQuant AI Agent - Flask Backend
驱动式AI策略编写智能体

# ============================================================
# SSQuant AI Agent
# AI助手地址: ai.kanpan789.com
# SSQuant项目地址: https://gitee.com/ssquant/ssquant
# 松鼠Quant俱乐部提供技术支持
# ============================================================
"""

import os
import sys
import json
import uuid
import threading
import subprocess
import tempfile
import re
import requests
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS
import queue
import time
import socket

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ==================== 远程提示词服务配置 ====================
# 远程提示词服务器地址（云服务器部署后修改为实际地址）
PROMPT_SERVER_URL = "http://ai.kanpan789.com:6760"
# 本地开发时可使用本地服务器
#PROMPT_SERVER_URL = "http://localhost:6760"

app = Flask(__name__)
CORS(app)

# 配置路径
STRATEGIES_DIR = PROJECT_ROOT / "ai_agent" / "strategies"
BACKTEST_RESULTS_DIR = PROJECT_ROOT / "backtest_results"
BACKTEST_LOGS_DIR = PROJECT_ROOT / "backtest_logs"
# 本地提示词文件（ai_agent/prompt.py），无需远程服务器和鉴权
# PROMPT_FILE = PROJECT_ROOT / "ssquant提示词模板" / "ssquant_prompt.py"
SETTINGS_FILE = PROJECT_ROOT / "ai_agent" / "settings.json"
HISTORY_FILE = PROJECT_ROOT / "ai_agent" / "history.json"
WORKSPACES_DIR = PROJECT_ROOT / "ai_agent" / "workspaces"

# 确保目录存在
STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)
WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)

# 报告元数据文件（关联报告与工作区）
REPORT_METADATA_FILE = PROJECT_ROOT / "ai_agent" / "report_metadata.json"

def load_report_metadata():
    """加载报告元数据"""
    if REPORT_METADATA_FILE.exists():
        try:
            with open(REPORT_METADATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_report_metadata(report_name, workspace_id):
    """保存报告与工作区的关联"""
    metadata = load_report_metadata()
    metadata[report_name] = workspace_id
    try:
        with open(REPORT_METADATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存报告元数据失败: {e}")

# ==================== 持久化设置 ====================
def get_default_settings():
    """获取默认设置"""
    return {
        "ai_settings": {
            "provider": "Custom",  # Custom 表示自定义接口
            "api_key": "",
            "model": "deepseek-chat",
            "temperature": 0.7,
            "base_url": "https://api.deepseek.com/v1",  # 用户可自定义的API接口地址
            "extra_params": "",  # JSON字符串，支持思考模式等厂商特定参数
            "thinking_mode": False,  # 是否启用思考模型（延长超时、显示思考过程）
            "max_reasoning_length": 4000,  # 思考链最大字符数，0表示不限制
            "max_tokens": 8192  # 回复最大token数
        },
        "backtest_params": {
            "strategy_mode": "single",
            "symbol": "rb888",
            "start_date": "2025-12-01",
            "end_date": "2026-01-31",
            "kline_period": "5m",
            "adjust_type": "1",
            "initial_capital": 1000000,
            "commission": 0.0001,
            "margin_rate": 0.1,
            "price_tick": 1,
            "contract_multiplier": 10,
            "slippage_ticks": 1,
            "lookback_bars": 500,
            "align_data": False,
            "fill_method": "ffill",
            # 多数据源配置（用于多品种/跨周期/套利策略）
            "data_sources": [
                {
                    "symbol": "rb888",
                    "kline_period": "5m",
                    "adjust_type": "1",
                    "price_tick": 1,
                    "contract_multiplier": 10,
                    "slippage_ticks": 1
                },
                {
                    "symbol": "rb888",
                    "kline_period": "15m",
                    "adjust_type": "1",
                    "price_tick": 1,
                    "contract_multiplier": 10,
                    "slippage_ticks": 1
                }
            ],
        },
        "auto_settings": {
            "auto_backtest": False,
            "auto_debug": False,
            "auto_iterate": False
        }
    }

def load_persistent_settings():
    """从文件加载持久化设置"""
    default_settings = get_default_settings()
    
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                # 合并设置（保留默认值中存在但保存文件中不存在的键）
                for key in default_settings:
                    if key in saved:
                        default_settings[key].update(saved[key])
                print(f"[OK] 已加载持久化设置: {SETTINGS_FILE}")
                return default_settings
        else:
            # 文件不存在，创建默认设置文件
            create_default_settings_file()
    except Exception as e:
        print(f"[WARN] 加载设置失败，使用默认值: {e}")
    
    return default_settings

def create_default_settings_file():
    """创建默认设置文件"""
    try:
        default_settings = get_default_settings()
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_settings, f, ensure_ascii=False, indent=2)
        print(f"[OK] 已创建默认设置文件: {SETTINGS_FILE}")
    except Exception as e:
        print(f"✗ 创建设置文件失败: {e}")

def save_persistent_settings(ai_settings, backtest_params, auto_settings):
    """保存设置到文件"""
    try:
        settings = {
            "ai_settings": ai_settings,
            "backtest_params": backtest_params,
            "auto_settings": auto_settings
        }
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        print(f"[OK] 设置已保存到: {SETTINGS_FILE}")
        return True
    except Exception as e:
        print(f"✗ 保存设置失败: {e}")
        return False

# ==================== 历史记录持久化 ====================
def load_history():
    """从文件加载历史记录"""
    try:
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
                # 确保每条记录都有id
                for i, item in enumerate(history):
                    if 'id' not in item:
                        item['id'] = i
                print(f"[OK] 已加载历史记录: {len(history)} 条")
                return history
    except Exception as e:
        print(f"[WARN] 加载历史记录失败: {e}")
    return []

def save_history_to_file(history):
    """保存历史记录到文件"""
    try:
        # 只保存最近100条记录（避免文件过大）
        history_to_save = history[-100:]
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history_to_save, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"✗ 保存历史记录失败: {e}")
        return False

# 全局状态
class AppState:
    def __init__(self):
        self.current_strategy = ""
        self.strategy_history = load_history()  # 从文件加载历史记录
        self.backtest_running = False
        self.backtest_output_queue = queue.Queue()
        self.current_process = None  # 当前运行的策略进程
        self.ai_generating = False  # AI是否正在生成
        self.ai_stop_flag = False  # 停止生成标志
        self.last_saved_code = ""  # 上次保存的代码（用于检测变化）
        self.current_backtest_workspace_id = ""  # 当前运行关联的工作区ID
        
        # 从持久化文件加载设置
        saved_settings = load_persistent_settings()
        self.ai_settings = saved_settings["ai_settings"]
        self.backtest_params = saved_settings["backtest_params"]
        self.auto_settings = saved_settings["auto_settings"]
    
    def add_history(self, item):
        """添加历史记录并保存到文件"""
        # 使用最大id + 1，避免id冲突
        max_id = max([h.get('id', -1) for h in self.strategy_history], default=-1)
        item['id'] = max_id + 1
        self.strategy_history.append(item)
        save_history_to_file(self.strategy_history)
        return item

state = AppState()

# ==================== 提示词加载 ====================
def load_system_prompt():
    """加载SSQuant系统提示词（本地版本）
    
    直接从 ai_agent/prompt.py 加载，无需远程服务器和鉴权
    """
    global PROMPT_LOAD_ERROR
    PROMPT_LOAD_ERROR = None
    
    try:
        from ai_agent.prompt import SSQUANT_SYSTEM_PROMPT
        print(f"[OK] 成功从本地加载提示词 ({len(SSQUANT_SYSTEM_PROMPT)} 字符)")
        return SSQUANT_SYSTEM_PROMPT
    except Exception as e:
        PROMPT_LOAD_ERROR = str(e)
        print(f"[ERROR] 加载本地提示词失败: {e}")
        # 返回一个基本提示词作为降级方案
        return """你是SSQuant量化交易策略开发助手。

⚠️ 警告：无法加载本地提示词文件 ai_agent/prompt.py。

错误信息：""" + str(e) + """

请检查 ai_agent/prompt.py 文件是否存在且格式正确。
"""


# 全局变量：提示词加载错误信息
PROMPT_LOAD_ERROR = None
SYSTEM_PROMPT = load_system_prompt()

def _parse_extra_params(settings):
    """解析用户配置的额外 JSON 参数（思考模式、推理强度等）"""
    extra_str = settings.get("extra_params", "")
    if not extra_str:
        return {}
    try:
        import json
        extra = json.loads(extra_str)
        if not isinstance(extra, dict):
            return {}
        # 过滤掉不允许覆盖的关键参数（避免破坏流式调用和消息结构）
        for key in ("messages", "stream"):
            extra.pop(key, None)
        return extra
    except Exception:
        return {}

def _inject_claude_thinking(kwargs, settings):
    """Claude 专属：如果用户开启了思考模式且未手动设置 thinking，自动注入 budget_tokens"""
    if "thinking" in kwargs:
        return  # 用户已通过 extra_params 手动设置，不覆盖
    if not settings.get("thinking_mode"):
        return  # 未开启思考模式
    max_reasoning = settings.get("max_reasoning_length", 0)
    if max_reasoning <= 0:
        return  # 0 表示不限制，不注入
    # budget_tokens 必须 >= 1024，且必须 < max_tokens
    max_tokens = kwargs.get("max_tokens", 16384)
    budget = max(1024, min(max_reasoning, max_tokens - 1024))
    kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
    print(f"[DEBUG] Claude thinking 自动注入: budget_tokens={budget}, max_tokens={max_tokens}")

def _is_claude_provider(provider):
    """判断是否为 Claude 提供商（原生 Anthropic API）"""
    return provider and provider.lower() in ('claude', 'anthropic')

def _convert_messages_for_claude(messages):
    """
    将 OpenAI 格式的 messages 转换为 Claude 格式。
    Claude 要求 system prompt 作为独立参数，messages 中只能有 user/assistant。
    支持多模态 content（图片 + 文本）。
    """
    system_parts = []
    claude_messages = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            if isinstance(content, list):
                text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
                system_parts.append("\n".join(text_parts))
            else:
                system_parts.append(content)
        elif role in ("user", "assistant"):
            if isinstance(content, list):
                claude_content = []
                for item in content:
                    if item.get("type") == "text":
                        claude_content.append({"type": "text", "text": item.get("text", "")})
                    elif item.get("type") == "image_url":
                        url = item.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            media_type = url.split(";")[0].split(":")[1]
                            data = url.split(",")[1]
                            claude_content.append({
                                "type": "image",
                                "source": {"type": "base64", "media_type": media_type, "data": data}
                            })
                        else:
                            claude_content.append({
                                "type": "image",
                                "source": {"type": "url", "url": url}
                            })
                claude_messages.append({"role": role, "content": claude_content})
            else:
                claude_messages.append({"role": role, "content": content})
        # 忽略其他 role（如 tool/function）
    system = "\n\n".join(system_parts) if system_parts else None
    return system, claude_messages

# AI API调用（流式，支持 OpenAI / Claude 多厂商，静默自动续写，自动重试）
def call_ai_api_stream(messages, settings):
    """调用AI API（流式输出，使用 OpenAI SDK，静默自动续写，出错自动重试5次）
    
    支持 OpenAI SDK 兼容格式 及 Claude (Anthropic) 原生 API
    用户可自定义 base_url 来使用不同的服务商
    """
    # 检查鉴权状态，鉴权失败则拒绝服务
    if PROMPT_LOAD_ERROR:
        yield {"error": f"⚠️ 俱乐部鉴权失败，无法使用AI功能。\n\n错误信息：{PROMPT_LOAD_ERROR}\n\n请在 ssquant/config/trading_config.py 中正确填写俱乐部账号密码，然后重启AI Agent。"}
        return
    
    provider = settings.get("provider", "Custom")
    api_key = settings.get("api_key", "")
    model = settings.get("model", "deepseek-chat")
    temperature = settings.get("temperature", 0.7)
    custom_base_url = settings.get("base_url", "")
    
    if not api_key:
        yield {"error": "请先配置API Key"}
        return
    
    is_claude = _is_claude_provider(provider)
    max_retries = 5
    
    def _do_stream():
        """实际的流式调用（内部生成器）"""
        if is_claude:
            # ========== Claude (Anthropic) 流式调用 ==========
            import anthropic
            
            api_timeout = 600.0 if settings.get('thinking_mode') else 300.0
            client = anthropic.Anthropic(api_key=api_key, timeout=api_timeout)
            system_prompt, current_messages = _convert_messages_for_claude(messages)
            
            while True:  # 自动续写直到完成
                kwargs = {
                    "model": model,
                    "messages": current_messages,
                    "temperature": temperature,
                    "max_tokens": settings.get("max_tokens", 8192),
                    "stream": True,
                }
                if system_prompt:
                    kwargs["system"] = system_prompt
                kwargs.update(_parse_extra_params(settings))
                _inject_claude_thinking(kwargs, settings)
                
                stream = client.messages.create(**kwargs)
                
                chunk_response = ""
                stop_reason = None
                
                for chunk in stream:
                    if chunk.type == "content_block_delta":
                        # 支持 Claude 3.7 Thinking 的 thinking 内容
                        thinking = getattr(chunk.delta, 'thinking', None)
                        if thinking:
                            yield {"reasoning": thinking}
                        text = chunk.delta.text if hasattr(chunk.delta, 'text') else ""
                        if text:
                            chunk_response += text
                            yield {"content": text}
                    elif chunk.type == "message_delta":
                        stop_reason = chunk.delta.stop_reason if hasattr(chunk.delta, 'stop_reason') else None
                
                # 如果因为长度截断(max_tokens)，静默续写
                if stop_reason == "max_tokens":
                    current_messages.append({"role": "assistant", "content": chunk_response})
                    current_messages.append({"role": "user", "content": "继续"})
                else:
                    break
        else:
            # ========== OpenAI 兼容格式流式调用 ==========
            from openai import OpenAI
            
            if custom_base_url:
                base_url = custom_base_url.rstrip('/')
            elif provider == "DeepSeek":
                base_url = "https://api.deepseek.com/v1"
            elif provider == "OpenAI":
                base_url = "https://api.openai.com/v1"
            else:
                base_url = "https://api.deepseek.com/v1"
            
            api_timeout = 600.0 if settings.get('thinking_mode') else 300.0
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=api_timeout)
            current_messages = messages.copy()
            
            while True:  # 自动续写直到完成
                kwargs = {
                    "model": model,
                    "messages": current_messages,
                    "temperature": temperature,
                    "stream": True,
                }
                kwargs.update(_parse_extra_params(settings))
                stream = client.chat.completions.create(**kwargs)
                
                chunk_response = ""
                finish_reason = None
                
                for chunk in stream:
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        # 支持思考模型（如 DeepSeek-R1）的 reasoning_content
                        reasoning = getattr(delta, 'reasoning_content', None)
                        if reasoning:
                            yield {"reasoning": reasoning}
                        if delta and delta.content:
                            chunk_response += delta.content
                            yield {"content": delta.content}
                        if chunk.choices[0].finish_reason:
                            finish_reason = chunk.choices[0].finish_reason
                
                # 如果因为长度截断，静默续写
                if finish_reason == "length":
                    current_messages.append({"role": "assistant", "content": chunk_response})
                    current_messages.append({"role": "user", "content": "继续"})
                else:
                    break
    
    for attempt in range(max_retries + 1):
        try:
            yield from _do_stream()
            return
        except Exception as e:
            error_msg = str(e)
            if "timeout" in error_msg.lower():
                friendly_error = "API请求超时"
            elif "connection" in error_msg.lower():
                friendly_error = "网络连接失败"
            elif "api_key" in error_msg.lower() or "authentication" in error_msg.lower():
                friendly_error = "API Key 无效"
            else:
                friendly_error = f"API调用失败: {error_msg}"
            
            if attempt < max_retries:
                yield {"retry": attempt + 1, "max_retries": max_retries, "error": friendly_error}
                import time
                time.sleep(min(2 ** attempt, 30))  # 指数退避，最多30秒
            else:
                yield {"error": f"{friendly_error}（已重试{max_retries}次，请检查网络或API配置后重试）"}
                return

# AI API调用（非流式，用于分析等）
def call_ai_api(messages, settings):
    """调用AI API（非流式，支持 OpenAI / Claude 多厂商）"""
    # 检查鉴权状态，鉴权失败则拒绝服务
    if PROMPT_LOAD_ERROR:
        return {"error": f"⚠️ 俱乐部鉴权失败，无法使用AI功能。\n\n错误信息：{PROMPT_LOAD_ERROR}\n\n请在 ssquant/config/trading_config.py 中正确填写俱乐部账号密码，然后重启AI Agent。"}
    
    provider = settings.get("provider", "Custom")
    api_key = settings.get("api_key", "")
    model = settings.get("model", "deepseek-chat")
    temperature = settings.get("temperature", 0.7)
    custom_base_url = settings.get("base_url", "")
    
    if not api_key:
        return {"error": "请先配置API Key"}
    
    is_claude = _is_claude_provider(provider)
    
    try:
        if is_claude:
            # ========== Claude (Anthropic) 非流式调用 ==========
            import anthropic
            
            api_timeout = 300.0 if settings.get('thinking_mode') else 120.0
            client = anthropic.Anthropic(api_key=api_key, timeout=api_timeout)
            system_prompt, claude_messages = _convert_messages_for_claude(messages)
            
            kwargs = {
                "model": model,
                "messages": claude_messages,
                "temperature": temperature,
                "max_tokens": settings.get("max_tokens", 16384),
            }
            if system_prompt:
                kwargs["system"] = system_prompt
            kwargs.update(_parse_extra_params(settings))
            _inject_claude_thinking(kwargs, settings)
            
            response = client.messages.create(**kwargs)
            content = response.content[0].text if response.content else ""
            # 提取 Claude thinking 内容
            reasoning = ""
            for block in response.content:
                if getattr(block, 'type', None) == 'thinking':
                    reasoning += getattr(block, 'thinking', '')
            if reasoning:
                return {"content": content, "reasoning": reasoning}
            return {"content": content}
        else:
            # ========== OpenAI 兼容格式非流式调用 ==========
            from openai import OpenAI
            
            if custom_base_url:
                base_url = custom_base_url.rstrip('/')
            elif provider == "DeepSeek":
                base_url = "https://api.deepseek.com/v1"
            elif provider == "OpenAI":
                base_url = "https://api.openai.com/v1"
            else:
                base_url = "https://api.deepseek.com/v1"
            
            api_timeout = 300.0 if settings.get('thinking_mode') else 120.0
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=api_timeout)
            
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": settings.get("max_tokens", 16384),
            }
            kwargs.update(_parse_extra_params(settings))
            response = client.chat.completions.create(**kwargs)
            
            msg = response.choices[0].message
            content = msg.content or ""
            reasoning = getattr(msg, 'reasoning_content', None)
            if reasoning:
                return {"content": content, "reasoning": reasoning}
            return {"content": content}
    
    except Exception as e:
        return {"error": f"API调用失败: {str(e)}"}

def extract_search_replace_blocks(response_text):
    """从AI响应中提取 SEARCH/REPLACE 格式的修改块"""
    if not response_text:
        return []
    
    blocks = []
    # 匹配 <<<<<<< SEARCH ... ======= ... >>>>>>> REPLACE 格式
    # 使用更灵活的模式，允许分隔符前后有空格
    pattern = r'<{6,7}\s*SEARCH\s*\n(.*?)\n={6,7}\s*\n(.*?)\n>{6,7}\s*REPLACE'
    matches = re.findall(pattern, response_text, re.DOTALL)
    
    for search_text, replace_text in matches:
        # 保留原始缩进，但去除首尾的空行
        search_text = search_text.rstrip('\n')
        replace_text = replace_text.rstrip('\n')
        if search_text:  # search 不能为空
            blocks.append({
                'search': search_text,
                'replace': replace_text
            })
    
    return blocks


def clean_code_artifacts(code):
    """清理代码中可能残留的 SEARCH/REPLACE 分隔符和其他AI输出标记"""
    if not code:
        return code
    
    # 移除残留的 SEARCH/REPLACE 分隔符
    patterns_to_remove = [
        r'^<{6,7}\s*SEARCH\s*$',      # <<<<<<< SEARCH
        r'^={6,7}\s*$',                # =======
        r'^>{6,7}\s*REPLACE\s*$',      # >>>>>>> REPLACE
        r'^<{6,7}\s*$',                # <<<<<<< (不带SEARCH)
        r'^>{6,7}\s*$',                # >>>>>>> (不带REPLACE)
    ]
    
    lines = code.split('\n')
    cleaned_lines = []
    
    for line in lines:
        should_remove = False
        for pattern in patterns_to_remove:
            if re.match(pattern, line.strip()):
                should_remove = True
                break
        if not should_remove:
            cleaned_lines.append(line)
    
    return '\n'.join(cleaned_lines)


def apply_search_replace(original_code, blocks):
    """应用 SEARCH/REPLACE 修改块到原始代码"""
    if not blocks or not original_code:
        return original_code, []
    
    modified_code = original_code
    applied = []
    failed = []
    
    for i, block in enumerate(blocks):
        search = block['search']
        replace = block['replace']
        
        if search in modified_code:
            modified_code = modified_code.replace(search, replace, 1)
            applied.append({
                'index': i,
                'search': search[:50] + '...' if len(search) > 50 else search,
                'success': True
            })
        else:
            # 尝试模糊匹配（忽略空白差异）
            search_normalized = ' '.join(search.split())
            lines = modified_code.split('\n')
            found = False
            
            for j, line in enumerate(lines):
                # 尝试在每一行开始进行多行匹配
                remaining = '\n'.join(lines[j:])
                if search_normalized in ' '.join(remaining.split()):
                    # 找到模糊匹配，尝试找到精确的替换位置
                    search_lines = search.split('\n')
                    match_start = j
                    match_end = j + len(search_lines)
                    if match_end <= len(lines):
                        # 替换这些行
                        new_lines = lines[:match_start] + replace.split('\n') + lines[match_end:]
                        modified_code = '\n'.join(new_lines)
                        applied.append({
                            'index': i,
                            'search': search[:50] + '...' if len(search) > 50 else search,
                            'success': True,
                            'fuzzy': True
                        })
                        found = True
                        break
            
            if not found:
                failed.append({
                    'index': i,
                    'search': search[:100] + '...' if len(search) > 100 else search,
                    'error': '未找到匹配的代码'
                })
    
    # 清理代码中可能残留的 SEARCH/REPLACE 分隔符
    modified_code = clean_code_artifacts(modified_code)
    
    return modified_code, {'applied': applied, 'failed': failed}


def extract_code_from_response(response_text):
    """从AI响应中提取Python代码"""
    if not response_text:
        return None
    
    code = None
    
    # 尝试提取完整的```python代码块
    pattern = r'```python\s*(.*?)```'
    matches = re.findall(pattern, response_text, re.DOTALL)
    if matches:
        code = max(matches, key=len).strip()
        if len(code) > 50:
            return clean_code_artifacts(code)
    
    # 尝试提取完整的```py代码块
    pattern = r'```py\s*(.*?)```'
    matches = re.findall(pattern, response_text, re.DOTALL)
    if matches:
        code = max(matches, key=len).strip()
        if len(code) > 50:
            return clean_code_artifacts(code)
    
    # 尝试提取普通```代码块
    pattern = r'```\s*(.*?)```'
    matches = re.findall(pattern, response_text, re.DOTALL)
    if matches:
        valid_matches = [m.strip() for m in matches if len(m.strip()) > 50]
        if valid_matches:
            code = max(valid_matches, key=len)
            return clean_code_artifacts(code)
    
    # 处理不完整的代码块（有开头没结尾）
    incomplete_pattern = r'```python\s*(.*?)$'
    match = re.search(incomplete_pattern, response_text, re.DOTALL)
    if match:
        code = match.group(1).strip()
        # 如果代码看起来像是策略代码
        if len(code) > 100 and ('def ' in code or 'import ' in code):
            return clean_code_artifacts(code)
    
    # 处理 ```py 开头的不完整代码块
    incomplete_pattern = r'```py\s*(.*?)$'
    match = re.search(incomplete_pattern, response_text, re.DOTALL)
    if match:
        code = match.group(1).strip()
        if len(code) > 100 and ('def ' in code or 'import ' in code):
            return clean_code_artifacts(code)
    
    return None


def process_ai_response(response_text, editor_code):
    """
    处理 AI 响应，智能判断是精确修改还是完整代码
    返回: {
        'type': 'search_replace' | 'full_code' | 'no_code',
        'code': 最终代码,
        'blocks': SEARCH/REPLACE 块（如果是精确修改）,
        'apply_result': 应用结果（如果是精确修改）
    }
    """
    if not response_text:
        return {'type': 'no_code', 'code': None}
    
    # 1. 首先尝试提取 SEARCH/REPLACE 块
    blocks = extract_search_replace_blocks(response_text)
    
    if blocks and editor_code:
        # 有 SEARCH/REPLACE 块且有原始代码，尝试应用精确修改
        modified_code, apply_result = apply_search_replace(editor_code, blocks)
        
        if apply_result['applied']:  # 至少有一个修改成功应用
            return {
                'type': 'search_replace',
                'code': modified_code,
                'blocks': blocks,
                'apply_result': apply_result
            }
    
    # 2. 如果没有 SEARCH/REPLACE 块，或应用失败，尝试提取完整代码
    full_code = extract_code_from_response(response_text)
    if full_code:
        return {
            'type': 'full_code',
            'code': full_code
        }
    
    # 3. 没有找到任何代码
    return {'type': 'no_code', 'code': None}

def check_code_syntax(code):
    """检查代码语法错误，返回 (是否通过, 错误信息)"""
    import ast
    try:
        ast.parse(code)
        return True, None
    except SyntaxError as e:
        error_msg = f"语法错误 (第{e.lineno}行): {e.msg}"
        if e.text:
            error_msg += f"\n问题代码: {e.text.strip()}"
        return False, error_msg
    except Exception as e:
        return False, f"代码检查失败: {str(e)}"

def run_backtest_in_thread(strategy_code, params):
    """在后台线程运行策略"""
    print(f"[DEBUG] run_backtest_in_thread 启动, backtest_running={state.backtest_running}")
    state.backtest_running = True
    # 清空队列而不是重新创建，避免与旧的 SSE 生成器竞争消息
    while not state.backtest_output_queue.empty():
        try:
            state.backtest_output_queue.get_nowait()
        except queue.Empty:
            break
    
    # 检测运行模式
    run_mode = detect_run_mode(strategy_code)
    mode_name = get_run_mode_name(run_mode)
    print(f"[DEBUG] 运行模式: {mode_name}")
    
    try:
        # 先检查代码语法
        print("[DEBUG] 检查代码语法...")
        syntax_ok, syntax_error = check_code_syntax(strategy_code)
        if not syntax_ok:
            print(f"[DEBUG] 语法检查失败: {syntax_error}")
            state.backtest_output_queue.put({
                "type": "error", 
                "message": f"⚠️ 代码语法检查失败！\n{syntax_error}\n\n请让AI修复后重试。"
            })
            state.backtest_output_queue.put({"type": "done", "error": syntax_error})
            state.backtest_running = False
            return
        
        print("[DEBUG] 语法检查通过")
        
        # 创建临时策略文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        strategy_file = STRATEGIES_DIR / f"strategy_{timestamp}.py"
        
        # 注入运行参数
        modified_code = inject_backtest_params(strategy_code, params)
        
        with open(strategy_file, 'w', encoding='utf-8') as f:
            f.write(modified_code)
        
        print(f"[DEBUG] 策略文件已保存: {strategy_file}")
        state.backtest_output_queue.put({"type": "info", "message": f"策略文件已保存: {strategy_file.name}"})
        state.backtest_output_queue.put({"type": "info", "message": f"开始运行{mode_name}..."})
        
        # 设置环境变量，解决Windows下的Unicode编码问题
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        
        # 确保日志目录存在
        BACKTEST_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        
        # 使用临时日志文件代替 PIPE，避免 Windows 上 PIPE 阻塞问题
        log_file_path = BACKTEST_LOGS_DIR / f"strategy_{timestamp}.log"
        log_file = open(log_file_path, 'w', encoding='utf-8')
        state.current_log_file = log_file  # 保存到 state，供 stop_backtest 关闭
        
        print(f"[DEBUG] 启动子进程: {sys.executable} {strategy_file}")
        # 运行策略
        process = subprocess.Popen(
            [sys.executable, str(strategy_file)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
            env=env
        )
        state.current_process = process
        print(f"[DEBUG] 子进程 PID: {process.pid}")
        
        # 实时读取输出，收集错误信息
        output_lines = []
        error_lines = []
        in_traceback = [False]
        last_log_position = [0]  # 使用列表以便在闭包中修改
        
        def _reader():
            """定期读取日志文件，避免 PIPE 阻塞"""
            print("[DEBUG] _reader 线程启动")
            try:
                while True:
                    try:
                        with open(log_file_path, 'r', encoding='utf-8') as f:
                            f.seek(last_log_position[0])
                            new_lines = f.readlines()
                            last_log_position[0] = f.tell()
                        
                        for line in new_lines:
                            stripped = line.strip()
                            if not stripped:
                                continue
                            output_lines.append(stripped)
                            
                            if 'Traceback' in stripped:
                                in_traceback[0] = True
                            
                            if in_traceback[0] or 'Error' in stripped or 'Exception' in stripped:
                                error_lines.append(stripped)
                                state.backtest_output_queue.put({"type": "error", "message": stripped})
                            else:
                                state.backtest_output_queue.put({"type": "output", "message": stripped})
                    except Exception as e:
                        print(f"[DEBUG] _reader 读取异常: {e}")
                        pass
                    
                    time.sleep(0.5)
                    
                    # 如果进程已结束且没有新内容，退出读取循环
                    if process.poll() is not None:
                        try:
                            with open(log_file_path, 'r', encoding='utf-8') as f:
                                f.seek(last_log_position[0])
                                new_lines = f.readlines()
                                last_log_position[0] = f.tell()
                            if not new_lines:
                                break
                        except Exception:
                            break
            except Exception as e:
                print(f"[DEBUG] _reader 线程异常: {e}")
                pass
            print("[DEBUG] _reader 线程结束")
        
        reader_thread = threading.Thread(target=_reader)
        reader_thread.daemon = True
        reader_thread.start()
        
        # 主线程等待进程结束（带超时保护，默认 10 分钟）
        print("[DEBUG] 主线程开始等待进程结束")
        start_time = time.time()
        timeout_seconds = 600  # 10 分钟超时
        try:
            while process.poll() is None:
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    print(f"[DEBUG] 子进程运行超过 {timeout_seconds} 秒，强制终止")
                    state.backtest_output_queue.put({"type": "warning", "message": f"⚠️ 策略运行超过 {timeout_seconds//60} 分钟，已自动终止"})
                    try:
                        process.kill()
                        process.wait(timeout=5)
                    except Exception as e:
                        print(f"[DEBUG] 超时 kill 失败: {e}")
                    break
                time.sleep(0.5)
        except Exception as e:
            print(f"[DEBUG] poll 循环异常: {e}")
            pass
        print(f"[DEBUG] 进程结束, returncode={process.returncode}")
        
        # 等待读取线程完成最后一轮读取
        reader_thread.join(timeout=3)
        
        # 关闭日志文件
        try:
            log_file.close()
        except Exception:
            pass
        finally:
            state.current_log_file = None
        
        if process.returncode == 0:
            state.backtest_output_queue.put({"type": "success", "message": f"{mode_name}完成!"})
            # 查找最新的报告文件
            report_file = find_latest_report()
            if report_file:
                state.backtest_output_queue.put({"type": "report", "path": str(report_file)})
                # 保存报告与工作区的关联
                save_report_metadata(report_file.name, state.current_backtest_workspace_id)
                # 保存到历史（使用add_history自动持久化）
                state.add_history({
                    "timestamp": timestamp,
                    "name": f"{mode_name}_{timestamp}",
                    "code": strategy_code,
                    "report_path": str(report_file),
                    "file_path": str(strategy_file),
                    "strategy_file": str(strategy_file),
                    "auto_saved": False,
                    "workspace_id": state.current_backtest_workspace_id
                })
        else:
            # 将所有收集的错误信息组合
            if error_lines:
                full_error = '\n'.join(error_lines)
                state.backtest_output_queue.put({"type": "error", "message": f"{mode_name}失败:\n{full_error}"})
            else:
                state.backtest_output_queue.put({"type": "error", "message": f"{mode_name}失败，返回码: {process.returncode}"})
            
    except Exception as e:
        print(f"[DEBUG] run_backtest_in_thread 异常: {e}")
        import traceback
        traceback.print_exc()
        state.backtest_output_queue.put({"type": "error", "message": f"执行错误: {str(e)}"})
    finally:
        print("[DEBUG] run_backtest_in_thread finally 执行")
        state.backtest_running = False
        state.current_process = None
        state.backtest_output_queue.put({"type": "done"})

def detect_run_mode(code):
    """从策略代码中检测运行模式
    
    优先匹配 RUN_MODE = RunMode.XXX 的赋值语句，
    避免被注释或其他地方的模式名称误导。
    """
    # 1. 优先查找明确的 RUN_MODE 赋值语句
    match = re.search(r'RUN_MODE\s*=\s*RunMode\.(BACKTEST|SIMNOW|REAL_TRADING)', code)
    if match:
        return match.group(1)
    
    # 2. 备选：查找未被注释的 RunMode.XXX（在行首没有 #）
    for line in code.split('\n'):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        if 'RunMode.SIMNOW' in stripped:
            return 'SIMNOW'
        if 'RunMode.REAL_TRADING' in stripped:
            return 'REAL_TRADING'
    
    return 'BACKTEST'

def get_run_mode_name(mode):
    """获取运行模式的中文名称"""
    names = {
        'SIMNOW': 'SIMNOW 模拟交易',
        'REAL_TRADING': 'CTP 实盘交易',
        'BACKTEST': '回测'
    }
    return names.get(mode, '回测')

def inject_backtest_params(code, params):
    """将运行参数注入到策略代码中"""
    # 查找并替换配置参数
    replacements = {
        r"initial_capital\s*=\s*\d+": f"initial_capital={params.get('initial_capital', 1000000)}",
        r"commission\s*=\s*[\d.]+": f"commission={params.get('commission', 0.0001)}",
        r"margin_rate\s*=\s*[\d.]+": f"margin_rate={params.get('margin_rate', 0.1)}",
        r"contract_multiplier\s*=\s*\d+": f"contract_multiplier={params.get('contract_multiplier', 10)}",
        r"price_tick\s*=\s*[\d.]+": f"price_tick={params.get('price_tick', 1)}",
        r"slippage_ticks\s*=\s*\d+": f"slippage_ticks={params.get('slippage_ticks', 1)}",
        r"adjust_type\s*=\s*['\"]?\d['\"]?": f"adjust_type='{params.get('adjust_type', '1')}'",
        r"lookback_bars\s*=\s*\d+": f"lookback_bars={params.get('lookback_bars', 500)}",
    }
    
    # 替换symbol（如果提供）
    if params.get('symbol'):
        replacements[r"symbol\s*=\s*['\"][^'\"]+['\"]"] = f"symbol='{params.get('symbol')}'"
    
    # 替换日期
    if params.get('start_date'):
        replacements[r"start_date\s*=\s*['\"][^'\"]+['\"]"] = f"start_date='{params.get('start_date')}'"
    if params.get('end_date'):
        replacements[r"end_date\s*=\s*['\"][^'\"]+['\"]"] = f"end_date='{params.get('end_date')}'"
    
    # 替换K线周期
    if params.get('kline_period'):
        replacements[r"kline_period\s*=\s*['\"][^'\"]+['\"]"] = f"kline_period='{params.get('kline_period')}'"
    
    modified_code = code
    for pattern, replacement in replacements.items():
        modified_code = re.sub(pattern, replacement, modified_code)
    
    return modified_code

def find_latest_report():
    """查找最新的运行报告"""
    if not BACKTEST_RESULTS_DIR.exists():
        return None
    
    html_files = list(BACKTEST_RESULTS_DIR.glob("*_report_*.html"))
    if not html_files:
        return None
    
    # 按修改时间排序
    latest = max(html_files, key=lambda x: x.stat().st_mtime)
    return latest

def parse_report_metrics(report_path):
    """解析运行报告的关键指标"""
    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        metrics = {}
        
        # 提取关键指标（简化版，根据实际报告格式调整）
        patterns = {
            "total_return": r"总收益率[：:]\s*([-\d.]+)%",
            "sharpe_ratio": r"夏普比率[：:]\s*([-\d.]+)",
            "max_drawdown": r"最大回撤[：:]\s*([-\d.]+)%",
            "win_rate": r"胜率[：:]\s*([-\d.]+)%",
            "trade_count": r"总交易次数[：:]\s*(\d+)",
        }
        
        for key, pattern in patterns.items():
            match = re.search(pattern, content)
            if match:
                metrics[key] = float(match.group(1))
        
        return metrics
    except Exception as e:
        return {"error": str(e)}

# ==================== Flask Routes ====================

@app.route('/')
def index():
    """主页"""
    return render_template('index.html')

@app.route('/api/chat', methods=['POST'])
def chat():
    """AI对话接口（非流式，兼容旧版）"""
    data = request.json
    user_message = data.get('message', '')
    history = data.get('history', [])
    include_code = data.get('include_code', True)
    
    # 构建消息列表
    system_content = SYSTEM_PROMPT
    # 思考模式：追加约束，要求模型简要思考
    if state.ai_settings.get("thinking_mode"):
        max_reasoning = state.ai_settings.get("max_reasoning_length", 4000)
        system_content += f"\n\n【重要约束】你当前处于思考模式。请保持思考简洁高效，不要过度分析或重复推演。思考内容控制在 {max_reasoning} 字符以内，直接给出结论和可执行代码。"
    messages = [{"role": "system", "content": system_content}]
    
    # 添加历史消息
    for msg in history[-10:]:
        messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
    
    # 如果需要，添加当前策略代码上下文
    if include_code and state.current_strategy:
        context = f"\n\n当前策略代码：\n```python\n{state.current_strategy}\n```"
        user_message = user_message + context
    
    messages.append({"role": "user", "content": user_message})
    
    # 调用AI API
    result = call_ai_api(messages, state.ai_settings)
    
    if "error" in result:
        return jsonify({"success": False, "error": result["error"]})
    
    response_content = result.get("content", "")
    extracted_code = extract_code_from_response(response_content)
    
    return jsonify({
        "success": True,
        "response": response_content,
        "extracted_code": extracted_code
    })

@app.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    """AI对话接口（流式输出，支持图片/文本附件）"""
    data = request.json
    user_message = data.get('message', '')
    history = data.get('history', [])
    editor_code = data.get('editor_code', '')
    attachments = data.get('attachments', [])
    
    print(f"[DEBUG] /api/chat/stream 收到请求, user_message_len={len(user_message)}, history_len={len(history)}, ai_generating={state.ai_generating}")
    
    # 重置停止标志
    state.ai_stop_flag = False
    state.ai_generating = True
    
    # 构建消息列表
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # 添加历史消息
    for msg in history[-10:]:
        messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
    
    # 添加编辑器中的代码作为上下文
    if editor_code and len(editor_code) > 50:
        context = f"\n\n【当前编辑器中的策略代码】：\n```python\n{editor_code}\n```\n\n请使用 SEARCH/REPLACE 格式精确修改需要改动的部分，不要重写整个代码。只有在创建全新策略时才返回完整代码。"
        user_message = user_message + context
    
    # 处理文本附件：将内容附加到用户消息中
    for att in attachments:
        if att.get('type') == 'text':
            user_message += f"\n\n【上传文件: {att['name']}】\n```\n{att['data']}\n```"
    
    # 处理图片附件：使用多模态格式
    image_attachments = [att for att in attachments if att.get('type') == 'image']
    if image_attachments and not user_message.strip():
        user_message = "请分析这张图片。"
    if image_attachments:
        content = [{"type": "text", "text": user_message}]
        for att in image_attachments:
            content.append({
                "type": "image_url",
                "image_url": {"url": att['data']}
            })
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": user_message})
    
    def generate():
        full_response = ""
        was_stopped = False
        try:
            for chunk in call_ai_api_stream(messages, state.ai_settings):
                # 检查停止标志
                if state.ai_stop_flag:
                    was_stopped = True
                    yield f"data: {json.dumps({'stopped': True}, ensure_ascii=False)}\n\n"
                    break
                    
                if "error" in chunk:
                    yield f"data: {json.dumps({'error': chunk['error']}, ensure_ascii=False)}\n\n"
                    # 发送结束信号
                    yield f"data: {json.dumps({'done': True, 'code_result': None}, ensure_ascii=False)}\n\n"
                    return
                if "heartbeat" in chunk:
                    # 发送心跳保持连接
                    yield f"data: {json.dumps({'heartbeat': True}, ensure_ascii=False)}\n\n"
                    continue
                if "reasoning" in chunk:
                    # 转发思考内容（完整显示，不做截断）
                    yield f"data: {json.dumps({'reasoning': chunk['reasoning']}, ensure_ascii=False)}\n\n"
                    continue
                if "content" in chunk:
                    full_response += chunk["content"]
                    yield f"data: {json.dumps({'content': chunk['content']}, ensure_ascii=False)}\n\n"
            
            # 发送完成信号和处理后的代码
            if was_stopped:
                # 被停止时也发送 done 信号，确保前端能正确结束
                yield f"data: {json.dumps({'done': True, 'stopped': True, 'code_result': None}, ensure_ascii=False)}\n\n"
            else:
                # 正常完成，使用新的智能处理函数
                code_result = process_ai_response(full_response, editor_code)
                
                # 兼容旧版前端：同时发送 extracted_code
                result_data = {
                    'done': True,
                    'code_result': code_result,
                    'extracted_code': code_result.get('code')  # 兼容旧版
                }
                yield f"data: {json.dumps(result_data, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': f'生成过程出错: {str(e)}'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True, 'code_result': None}, ensure_ascii=False)}\n\n"
        finally:
            state.ai_generating = False
    
    # 禁用缓冲，确保数据立即发送
    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response

@app.route('/api/chat/stop', methods=['POST'])
def stop_generation():
    """停止AI生成"""
    state.ai_stop_flag = True
    return jsonify({"success": True, "message": "已发送停止信号"})

@app.route('/api/chat/status')
def chat_status():
    """获取AI生成状态"""
    return jsonify({
        "generating": state.ai_generating,
        "stopped": state.ai_stop_flag
    })

@app.route('/api/strategy', methods=['GET', 'POST'])
def strategy():
    """获取/更新当前策略"""
    if request.method == 'GET':
        return jsonify({
            "success": True,
            "code": state.current_strategy,
            "history": state.strategy_history[-20:]  # 返回最近20个版本
        })
    else:
        data = request.json
        new_code = data.get('code', '')
        state.current_strategy = new_code
        return jsonify({"success": True})

@app.route('/api/backtest/start', methods=['POST'])
def start_backtest():
    """启动策略运行"""
    # 如果上一次运行仍在进行，先等待它结束（最多5秒）
    if state.backtest_running:
        import time
        for _ in range(10):
            if not state.backtest_running:
                break
            time.sleep(0.5)
        if state.backtest_running:
            return jsonify({"success": False, "error": "已有策略正在运行，请等待结束或点击停止"})
    
    data = request.json
    code = data.get('code', state.current_strategy)
    params = data.get('params', state.backtest_params)
    workspace_id = data.get('workspace_id', '')  # 新增：工作区ID
    
    if not code:
        return jsonify({"success": False, "error": "没有策略代码"})
    
    # 检测运行模式
    run_mode = detect_run_mode(code)
    mode_name = get_run_mode_name(run_mode)
    
    # 保存当前工作区ID供运行使用
    state.current_backtest_workspace_id = workspace_id
    
    # 在后台线程运行策略
    thread = threading.Thread(target=run_backtest_in_thread, args=(code, params))
    thread.daemon = True
    thread.start()
    
    return jsonify({"success": True, "message": f"{mode_name}已启动", "run_mode": run_mode, "mode_name": mode_name})

@app.route('/api/backtest/status')
def backtest_status():
    """获取运行状态（SSE流）"""
    print(f"[DEBUG] SSE 连接建立, backtest_running={state.backtest_running}, queue大小={state.backtest_output_queue.qsize()}")
    # 捕获当前队列引用，避免 run_backtest_in_thread 清空队列后切换到新队列
    q = state.backtest_output_queue
    def generate():
        msg_count = 0
        while True:
            try:
                msg = q.get(timeout=1)
                msg_count += 1
                print(f"[DEBUG] SSE 发送消息 #{msg_count}: {msg.get('type')}, {msg.get('message','')[:50]}")
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                if msg.get("type") == "done":
                    print("[DEBUG] SSE 收到 done，结束连接")
                    break
            except queue.Empty:
                if not state.backtest_running:
                    print("[DEBUG] SSE backtest_running=False，发送 done 并结束")
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    break
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
    
    response = Response(generate(), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    return response

@app.route('/api/backtest/running')
def backtest_running():
    """检查运行是否正在进行"""
    return jsonify({"running": state.backtest_running})

@app.route('/api/backtest/stop', methods=['POST'])
def stop_backtest():
    """强制停止当前运行的策略进程"""
    # 先关闭日志文件句柄，避免 Windows 上文件被占用
    if hasattr(state, 'current_log_file') and state.current_log_file:
        try:
            state.current_log_file.close()
        except Exception:
            pass
        state.current_log_file = None
    
    process = state.current_process
    state.current_process = None
    
    if process and process.poll() is None:
        try:
            # Windows 上使用 taskkill /F /T 强制终止进程树，比 TerminateProcess 更可靠
            if sys.platform == 'win32':
                import subprocess as _sp
                _sp.run(['taskkill', '/F', '/T', '/PID', str(process.pid)], 
                       capture_output=True, timeout=10)
            else:
                process.kill()
                process.wait(timeout=5)
            print(f"[DEBUG] 进程 {process.pid} 已强制终止")
        except Exception as e:
            print(f"[DEBUG] 停止进程失败: {e}")
    
    # 重置前端状态并发送 done，确保前端不会卡住
    state.backtest_running = False
    state.backtest_output_queue.put({"type": "warning", "message": "⚠️ 策略进程已被强制终止"})
    state.backtest_output_queue.put({"type": "done"})
    
    return jsonify({"success": True, "message": "已强制停止策略进程"})

@app.route('/api/reports')
def get_reports():
    """获取运行报告列表"""
    workspace_id = request.args.get('workspace_id', '')
    
    if not BACKTEST_RESULTS_DIR.exists():
        return jsonify({"success": True, "reports": []})
    
    # 加载报告元数据
    report_metadata = load_report_metadata()
    
    reports = []
    filtered_count = 0
    for html_file in sorted(BACKTEST_RESULTS_DIR.glob("*_report_*.html"), 
                           key=lambda x: x.stat().st_mtime, reverse=True)[:50]:
        # 按工作区过滤
        report_ws_id = report_metadata.get(html_file.name, '')
        if workspace_id and report_ws_id != workspace_id:
            filtered_count += 1
            continue
            
        reports.append({
            "name": html_file.name,
            "path": str(html_file),
            "modified": datetime.fromtimestamp(html_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "workspace_id": report_ws_id
        })
    
    response = jsonify({"success": True, "reports": reports})
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response

@app.route('/api/report/<path:filename>')
def get_report(filename):
    """获取单个报告内容"""
    report_path = BACKTEST_RESULTS_DIR / filename
    if not report_path.exists():
        return jsonify({"success": False, "error": "报告不存在"})
    
    with open(report_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    return jsonify({"success": True, "content": content})

@app.route('/api/report/<path:filename>', methods=['DELETE'])
def delete_report(filename):
    """删除单个报告及相关文件"""
    import re
    from datetime import datetime, timedelta
    
    report_path = BACKTEST_RESULTS_DIR / filename
    print(f"[删除报告] 文件名: {filename}")
    print(f"[删除报告] 完整路径: {report_path}")
    print(f"[删除报告] 文件存在: {report_path.exists()}")
    
    if not report_path.exists():
        return jsonify({"success": False, "error": f"报告不存在: {report_path}"})
    
    try:
        # 从文件名提取合约代码和时间戳
        # 如 rb888_report_20260112_111234.html -> symbol=rb888, timestamp=20260112_111234
        match = re.search(r'^(.+?)_report_(\d{8}_\d{6})\.html$', filename)
        if match:
            symbol = match.group(1)
            report_timestamp = match.group(2)
            report_date = report_timestamp.split('_')[0]  # 20260112
            print(f"[删除报告] 合约代码: {symbol}, 时间戳: {report_timestamp}, 日期: {report_date}")
        else:
            symbol = None
            report_timestamp = None
            report_date = None
            print(f"[删除报告] 无法解析文件名")
        
        # 删除报告HTML
        report_path.unlink()
        print(f"[删除报告] HTML已删除")
        
        # 删除对应的 performance 文件（按合约+日期匹配，时间戳在报告前60秒内）
        if symbol and report_date:
            try:
                report_time = datetime.strptime(report_timestamp, "%Y%m%d_%H%M%S")
            except:
                report_time = None
            
            for perf_file in BACKTEST_RESULTS_DIR.glob(f"performance_{symbol}_{report_date}_*.txt"):
                # 提取性能文件的时间戳
                perf_match = re.search(r'_(\d{8}_\d{6})\.txt$', perf_file.name)
                if perf_match and report_time:
                    try:
                        perf_time = datetime.strptime(perf_match.group(1), "%Y%m%d_%H%M%S")
                        # 如果性能文件时间在报告时间之前60秒内，认为是同一次运行
                        if timedelta(seconds=0) <= (report_time - perf_time) <= timedelta(seconds=60):
                            print(f"[删除报告] 删除性能文件: {perf_file}")
                            perf_file.unlink()
                    except:
                        pass
        
        # 删除对应的日志文件（按合约+日期匹配，时间戳在报告前60秒内）
        if symbol and report_date and BACKTEST_LOGS_DIR.exists():
            for log_file in BACKTEST_LOGS_DIR.glob(f"backtest_{symbol}_{report_date}_*.log"):
                log_match = re.search(r'_(\d{8}_\d{6})\.log$', log_file.name)
                if log_match and report_time:
                    try:
                        log_time = datetime.strptime(log_match.group(1), "%Y%m%d_%H%M%S")
                        if timedelta(seconds=0) <= (report_time - log_time) <= timedelta(seconds=60):
                            print(f"[删除报告] 删除日志文件: {log_file}")
                            log_file.unlink()
                    except:
                        pass
        
        print(f"[删除报告] 删除成功")
        return jsonify({"success": True})
    except Exception as e:
        print(f"[删除报告] 错误: {e}")
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/reports/clear', methods=['DELETE'])
def clear_all_reports():
    """清空所有报告及相关文件"""
    count = 0
    try:
        # 清空 backtest_results 目录
        if BACKTEST_RESULTS_DIR.exists():
            for f in BACKTEST_RESULTS_DIR.glob("*.html"):
                f.unlink()
                count += 1
            for f in BACKTEST_RESULTS_DIR.glob("*.txt"):
                f.unlink()
        
        # 清空 backtest_logs 目录
        if BACKTEST_LOGS_DIR.exists():
            for f in BACKTEST_LOGS_DIR.glob("*.log"):
                f.unlink()
        
        return jsonify({"success": True, "count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/prompt/status', methods=['GET'])
def prompt_status():
    """获取提示词加载状态"""
    return jsonify({
        "success": PROMPT_LOAD_ERROR is None,
        "error": PROMPT_LOAD_ERROR,
        "prompt_length": len(SYSTEM_PROMPT) if SYSTEM_PROMPT else 0,
        "remote_server": PROMPT_SERVER_URL
    })


@app.route('/api/prompt/reload', methods=['POST'])
def reload_prompt():
    """重新加载提示词"""
    global SYSTEM_PROMPT, PROMPT_LOAD_ERROR
    
    SYSTEM_PROMPT = load_system_prompt()
    
    return jsonify({
        "success": PROMPT_LOAD_ERROR is None,
        "error": PROMPT_LOAD_ERROR,
        "prompt_length": len(SYSTEM_PROMPT) if SYSTEM_PROMPT else 0,
        "message": "提示词已重新加载" if PROMPT_LOAD_ERROR is None else f"加载失败: {PROMPT_LOAD_ERROR}"
    })


@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    """获取/更新设置"""
    if request.method == 'GET':
        return jsonify({
            "success": True,
            "ai_settings": state.ai_settings,
            "backtest_params": state.backtest_params,
            "auto_settings": state.auto_settings,
            "prompt_status": {
                "loaded": PROMPT_LOAD_ERROR is None,
                "error": PROMPT_LOAD_ERROR
            }
        })
    else:
        data = request.json
        if 'ai_settings' in data:
            state.ai_settings.update(data['ai_settings'])
        if 'backtest_params' in data:
            state.backtest_params.update(data['backtest_params'])
        if 'auto_settings' in data:
            state.auto_settings.update(data['auto_settings'])
        
        # 持久化保存到文件
        save_persistent_settings(state.ai_settings, state.backtest_params, state.auto_settings)
        
        return jsonify({"success": True, "message": "设置已保存"})

@app.route('/api/history')
def get_history():
    """获取策略历史版本"""
    workspace_id = request.args.get('workspace_id', '')
    
    # 过滤和处理历史记录
    history_with_ids = []
    filtered_count = 0
    for i, item in enumerate(state.strategy_history[-50:]):
        # 按工作区过滤（如果指定了workspace_id）
        item_ws = item.get('workspace_id', '')
        if workspace_id and item_ws != workspace_id:
            filtered_count += 1
            continue
            
        item_copy = dict(item)
        # 计算原始数组中的索引
        original_index = len(state.strategy_history) - 50 + i if len(state.strategy_history) > 50 else i
        if original_index < 0:
            original_index = i
        item_copy['id'] = item.get('id', original_index)
        history_with_ids.append(item_copy)
    
    response = jsonify({
        "success": True,
        "history": history_with_ids
    })
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response

@app.route('/api/history/<int:item_id>')
def get_history_item(item_id):
    """获取指定历史版本（通过id查找）"""
    # 通过id查找历史记录
    for item in state.strategy_history:
        if item.get('id') == item_id:
            return jsonify({
                "success": True,
                "item": item
            })
    # 兼容旧数据：如果id匹配不到，尝试用索引
    if 0 <= item_id < len(state.strategy_history):
        return jsonify({
            "success": True,
            "item": state.strategy_history[item_id]
        })
    return jsonify({"success": False, "error": "找不到该历史记录"})

@app.route('/api/history/<int:item_id>', methods=['DELETE'])
def delete_history_item(item_id):
    """删除单个历史记录"""
    # 通过id查找并删除
    for i, item in enumerate(state.strategy_history):
        if item.get('id') == item_id:
            # 删除对应的策略文件
            file_path = item.get('file_path')
            if file_path:
                try:
                    p = Path(file_path)
                    if p.exists():
                        p.unlink()
                except Exception as e:
                    print(f"删除策略文件失败: {e}")
            
            state.strategy_history.pop(i)
            save_history_to_file(state.strategy_history)
            return jsonify({"success": True})
    return jsonify({"success": False, "error": "找不到该历史记录"})

@app.route('/api/history/clear', methods=['DELETE'])
def clear_all_history():
    """清空所有历史记录"""
    count = len(state.strategy_history)
    
    # 删除所有策略文件
    for item in state.strategy_history:
        file_path = item.get('file_path')
        if file_path:
            try:
                p = Path(file_path)
                if p.exists():
                    p.unlink()
            except Exception as e:
                print(f"删除策略文件失败: {e}")
    
    state.strategy_history.clear()
    save_history_to_file(state.strategy_history)
    return jsonify({"success": True, "count": count})

@app.route('/api/history/save', methods=['POST'])
def save_history():
    """保存策略到历史版本"""
    data = request.json
    code = data.get('code', '')
    name = data.get('name', '')
    auto_save = data.get('auto_save', False)
    workspace_id = data.get('workspace_id', '')  # 新增：工作区ID
    force_save = data.get('force_save', False)  # 强制保存（跳过重复检查）
    
    if not code or len(code) < 50:
        return jsonify({"success": False, "error": "代码太短"})
    
    # 检查是否与上次保存的相同（避免重复保存）- 除非强制保存
    if not force_save and code == state.last_saved_code:
        return jsonify({"success": True, "message": "代码未变化，跳过保存", "skipped": True})
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 自动生成名称
    if not name:
        # 尝试从代码中提取策略名称
        match = re.search(r'["\']([^"\']*策略[^"\']*)["\']', code)
        if match:
            name = match.group(1)
        else:
            name = f"策略_{timestamp}"
    
    # 保存到文件
    strategy_file = STRATEGIES_DIR / f"strategy_{timestamp}.py"
    with open(strategy_file, 'w', encoding='utf-8') as f:
        f.write(code)
    
    # 添加到历史（使用add_history自动持久化）
    history_item = state.add_history({
        "timestamp": timestamp,
        "name": name,
        "code": code,
        "file_path": str(strategy_file),
        "report_path": None,
        "auto_saved": auto_save,
        "workspace_id": workspace_id  # 新增：关联工作区
    })
    state.last_saved_code = code
    state.current_strategy = code
    
    return jsonify({
        "success": True, 
        "message": "已保存到历史版本",
        "item": history_item
    })

@app.route('/api/history/preview/<int:item_id>')
def preview_history(item_id):
    """预览历史版本代码（通过id查找）"""
    # 通过id查找历史记录
    for item in state.strategy_history:
        if item.get('id') == item_id:
            return jsonify({
                "success": True,
                "code": item.get('code', ''),
                "name": item.get('name', ''),
                "timestamp": item.get('timestamp', ''),
                "file_path": item.get('file_path', '')
            })
    # 兼容旧数据：如果id匹配不到，尝试用索引
    if 0 <= item_id < len(state.strategy_history):
        item = state.strategy_history[item_id]
        return jsonify({
            "success": True,
            "code": item.get('code', ''),
            "name": item.get('name', ''),
            "timestamp": item.get('timestamp', ''),
            "file_path": item.get('file_path', '')
        })
    return jsonify({"success": False, "error": "找不到该历史记录"})

@app.route('/api/examples')
def get_examples():
    """获取示例策略列表"""
    examples_dir = PROJECT_ROOT / "examples"
    examples = []
    
    if examples_dir.exists():
        for py_file in sorted(examples_dir.glob("B_*.py")):
            examples.append({
                "name": py_file.stem,
                "path": str(py_file)
            })
    
    return jsonify({"success": True, "examples": examples})

@app.route('/api/example/<path:filename>')
def get_example(filename):
    """获取示例策略内容"""
    example_path = PROJECT_ROOT / "examples" / filename
    if not example_path.exists():
        return jsonify({"success": False, "error": "文件不存在"})
    
    with open(example_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    return jsonify({"success": True, "content": content})

@app.route('/api/analyze', methods=['POST'])
def analyze_report():
    """让AI分析运行报告"""
    data = request.json
    report_path = data.get('report_path', '')
    
    if not report_path or not Path(report_path).exists():
        return jsonify({"success": False, "error": "报告不存在"})
    
    # 读取报告
    with open(report_path, 'r', encoding='utf-8') as f:
        report_content = f.read()
    
    # 提取关键数据（简化版）
    metrics = parse_report_metrics(report_path)
    
    # 构建分析请求
    analysis_prompt = f"""
请分析以下运行结果并给出改进建议：

运行指标摘要:
{json.dumps(metrics, ensure_ascii=False, indent=2)}

优化目标:
- 最小交易次数: {state.optimization_targets['min_trades']}
- 目标夏普比率: {state.optimization_targets['target_sharpe']}
- 目标胜率: {state.optimization_targets['target_win_rate']}
- 最大回撤限制: {state.optimization_targets['max_drawdown']}

当前策略代码:
```python
{state.current_strategy[:3000] if state.current_strategy else "无"}
```

请从以下几个方面进行分析：
1. 策略表现评估
2. 存在的问题和风险
3. 具体改进建议
4. 参数优化方向

如果需要修改代码，请提供完整的修改后代码。
"""
    
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": analysis_prompt}
    ]
    
    result = call_ai_api(messages, state.ai_settings)
    
    if "error" in result:
        return jsonify({"success": False, "error": result["error"]})
    
    response_content = result.get("content", "")
    extracted_code = extract_code_from_response(response_content)
    
    return jsonify({
        "success": True,
        "analysis": response_content,
        "metrics": metrics,
        "suggested_code": extracted_code
    })

# ==================== 工作区管理 ====================

def get_workspace_file(workspace_id):
    """获取工作区文件路径"""
    return WORKSPACES_DIR / f"{workspace_id}.json"

def load_workspace(workspace_id):
    """加载工作区数据"""
    ws_file = get_workspace_file(workspace_id)
    if ws_file.exists():
        with open(ws_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def save_workspace(workspace_id, data):
    """保存工作区数据"""
    ws_file = get_workspace_file(workspace_id)
    with open(ws_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return True

@app.route('/api/workspaces')
def list_workspaces():
    """获取所有工作区列表"""
    workspaces = []
    for ws_file in sorted(WORKSPACES_DIR.glob("*.json"), 
                          key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            with open(ws_file, 'r', encoding='utf-8') as f:
                ws_data = json.load(f)
                workspaces.append({
                    "id": ws_file.stem,
                    "name": ws_data.get("name", "未命名工作区"),
                    "created_at": ws_data.get("created_at", ""),
                    "updated_at": ws_data.get("updated_at", ""),
                    "message_count": len(ws_data.get("chat_history", []))
                })
        except Exception as e:
            print(f"加载工作区失败 {ws_file}: {e}")
    
    return jsonify({"success": True, "workspaces": workspaces})

@app.route('/api/workspace', methods=['POST'])
def create_workspace():
    """创建新工作区"""
    data = request.json
    name = data.get('name', '新工作区')
    
    # 生成唯一ID
    workspace_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:8]
    
    ws_data = {
        "id": workspace_id,
        "name": name,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "chat_history": [],
        "editor_code": "",
        "settings": {}
    }
    
    save_workspace(workspace_id, ws_data)
    
    return jsonify({
        "success": True,
        "workspace": {
            "id": workspace_id,
            "name": name,
            "created_at": ws_data["created_at"],
            "updated_at": ws_data["updated_at"],
            "message_count": 0
        }
    })

@app.route('/api/workspace/<workspace_id>', methods=['GET'])
def get_workspace(workspace_id):
    """获取工作区详情"""
    ws_data = load_workspace(workspace_id)
    if not ws_data:
        return jsonify({"success": False, "error": "工作区不存在"})
    
    return jsonify({"success": True, "workspace": ws_data})

@app.route('/api/workspace/<workspace_id>', methods=['PUT'])
def update_workspace(workspace_id):
    """更新工作区"""
    ws_data = load_workspace(workspace_id)
    if not ws_data:
        return jsonify({"success": False, "error": "工作区不存在"})
    
    data = request.json
    
    # 更新字段
    if 'name' in data:
        ws_data['name'] = data['name']
    if 'chat_history' in data:
        ws_data['chat_history'] = data['chat_history']
    if 'editor_code' in data:
        ws_data['editor_code'] = data['editor_code']
    
    ws_data['updated_at'] = datetime.now().isoformat()
    
    save_workspace(workspace_id, ws_data)
    
    return jsonify({"success": True, "message": "工作区已更新"})

@app.route('/api/workspace/<workspace_id>', methods=['DELETE'])
def delete_workspace(workspace_id):
    """删除工作区（级联删除关联的报告和策略文件）"""
    ws_file = get_workspace_file(workspace_id)
    if not ws_file.exists():
        return jsonify({"success": False, "error": "工作区不存在"})
    
    deleted_reports = 0
    deleted_strategies = 0
    deleted_perfs = 0
    
    # 1. 删除关联的回测报告
    try:
        metadata = load_report_metadata()
        reports_to_remove = [name for name, ws_id in metadata.items() if ws_id == workspace_id]
        for report_name in reports_to_remove:
            report_path = BACKTEST_RESULTS_DIR / report_name
            if report_path.exists():
                # 提取合约代码和时间戳，删除关联的 performance 文件
                match = re.search(r'^(.+?)_report_(\d{8}_\d{6})\.html$', report_name)
                if match:
                    symbol = match.group(1)
                    report_timestamp = match.group(2)
                    report_date = report_timestamp.split('_')[0]
                    try:
                        report_time = datetime.strptime(report_timestamp, "%Y%m%d_%H%M%S")
                        for perf_file in BACKTEST_RESULTS_DIR.glob(f"performance_{symbol}_{report_date}_*.txt"):
                            perf_match = re.search(r'_(\d{8}_\d{6})\.txt$', perf_file.name)
                            if perf_match:
                                try:
                                    perf_time = datetime.strptime(perf_match.group(1), "%Y%m%d_%H%M%S")
                                    if timedelta(seconds=0) <= (report_time - perf_time) <= timedelta(seconds=60):
                                        perf_file.unlink()
                                        deleted_perfs += 1
                                except Exception:
                                    pass
                    except Exception:
                        pass
                report_path.unlink()
                deleted_reports += 1
            # 从元数据中移除
            del metadata[report_name]
        # 保存更新后的元数据
        with open(REPORT_METADATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[删除工作区] 删除报告失败: {e}")
    
    # 2. 删除关联的策略文件和历史记录
    try:
        indices_to_remove = []
        for i, item in enumerate(state.strategy_history):
            if item.get('workspace_id') == workspace_id:
                file_path = item.get('file_path')
                if file_path:
                    try:
                        p = Path(file_path)
                        if p.exists():
                            p.unlink()
                            deleted_strategies += 1
                    except Exception as e:
                        print(f"[删除工作区] 删除策略文件失败: {e}")
                indices_to_remove.append(i)
        # 从后往前删除，避免索引偏移
        for i in reversed(indices_to_remove):
            state.strategy_history.pop(i)
        if indices_to_remove:
            save_history_to_file(state.strategy_history)
    except Exception as e:
        print(f"[删除工作区] 删除策略历史失败: {e}")
    
    # 3. 删除工作区文件本身
    ws_file.unlink()
    
    return jsonify({
        "success": True,
        "message": f"工作区已删除（报告 {deleted_reports} 个，策略 {deleted_strategies} 个，性能文件 {deleted_perfs} 个）"
    })

# ==================== 主入口 ====================
# 
# 注意：本文件不再支持直接运行（python backend.py）。
# 生产环境请使用 start_server.py 启动：
#     cd ai_agent
#     python start_server.py
# 
# 如需调试，可在 start_server.py 中调整 waitress 的 expose_tracebacks=True
# 或在代码中添加 logging 输出。

