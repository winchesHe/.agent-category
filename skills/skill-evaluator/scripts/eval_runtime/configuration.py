"""只读发现运行配置；模型由调用 Agent 显式选择。"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def gpt_model(model: str | None, provider: str | None = None) -> tuple[str | None, str]:
    if not model:
        raise ValueError('请先 --list-models，由 Agent 选择 GPT 后传 --model；不沿用本机默认模型')
    if '/' in model:
        prefix, model = model.split('/', 1)
        if provider and provider != prefix:
            raise ValueError('模型前缀与 --provider 冲突')
        provider = prefix
    if not re.fullmatch(r'gpt-[A-Za-z0-9][A-Za-z0-9._-]*', model):
        raise ValueError('仅支持准确的 GPT 模型 ID，不支持非 GPT、模糊模式或 thinking 后缀')
    return provider, model


def codex_config() -> dict:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    path = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'config.toml'
    return tomllib.loads(path.read_text()) if path.exists() else {}


def codex_connection(provider: str | None) -> tuple[str | None, list[str]]:
    config = codex_config()
    selected = provider or config.get('model_provider')
    args = []
    if selected:
        args += ['-c', f'model_provider={json.dumps(selected)}']
        definition = config.get('model_providers', {}).get(selected, {})
        # 只复用连接字段，不载入插件、MCP、用户指令或任何硬编码凭据。
        for key in ('name', 'base_url', 'env_key', 'wire_api', 'requires_openai_auth', 'supports_websockets'):
            if key in definition:
                args += ['-c', f'model_providers.{selected}.{key}={json.dumps(definition[key])}']
    return selected, args


def discover_models() -> dict:
    result = {'pi': [], 'codex': [], 'errors': [], 'note': '配置存在不代表服务健康；按需求选择 GPT 并记录理由'}
    node = shutil.which('node')
    if node:
        try:
            run = subprocess.run([node, str(Path(__file__).with_name('pi_sdk_bridge.mjs'))],
                                 input=json.dumps({'action': 'list_models'}), capture_output=True,
                                 text=True, timeout=30)
            if run.returncode:
                result['errors'].append({'executor': 'pi', 'message': run.stderr[-1500:]})
            else:
                result['pi'] = json.loads(run.stdout)['models']
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            result['errors'].append({'executor': 'pi', 'message': str(exc)})
    if not result['pi'] and shutil.which('pi'):
        try:
            catalog = subprocess.run(['pi', '--no-extensions', '--no-skills', '--no-context-files', '--list-models', 'gpt'],
                                     capture_output=True, text=True, timeout=30)
            for line in catalog.stdout.splitlines() if catalog.returncode == 0 else []:
                fields = line.split()
                if len(fields) < 2:
                    continue
                try:
                    provider, model = gpt_model(fields[1], fields[0])
                except ValueError:
                    continue
                result['pi'].append({'provider': provider, 'model': model, 'source': 'Pi CLI 已配置目录',
                                     'thinking_levels': None})
        except (OSError, subprocess.TimeoutExpired) as exc:
            result['errors'].append({'executor': 'pi-cli', 'message': str(exc)})
    config = codex_config()
    result['daily_environment'] = None
    if config.get('model'):
        try:
            _, preferred = gpt_model(config['model'])
        except ValueError:
            pass
        else:
            result['daily_environment'] = {'executor': 'codex', 'model': preferred,
                'provider': config.get('model_provider'), 'reasoning': config.get('model_reasoning_effort'),
                'source': 'Codex config.toml 顶层配置提示，需确认实际日常设置'}
    home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    models = []
    thinking = {}
    cache = home / 'models_cache.json'
    if cache.exists():
        data = json.loads(cache.read_text())
        models = [m.get('slug', '') for m in data.get('models', [])]
        thinking = {m.get('slug'): m.get('supported_reasoning_levels', []) for m in data.get('models', [])}
    if config.get('model'):
        models.append(config['model'])
    for model in sorted(set(models)):
        try:
            _, model = gpt_model(model)
        except ValueError:
            continue
        result['codex'].append({'model': model, 'provider': config.get('model_provider'),
                                'source': '本地 model cache / config', 'cli_available': bool(os.environ.get('CODEX_EXECUTABLE') or shutil.which('codex')),
                                'thinking_levels': thinking.get(model, []),
                                'executable': os.environ.get('CODEX_EXECUTABLE') or shutil.which('codex')})
    return result
