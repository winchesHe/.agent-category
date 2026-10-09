"""运行失败、同设置对照和模型输入隔离的回归测试（不调用模型）。"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.eval_runtime.configuration import gpt_model
from scripts.eval_runtime.executors import (
    CodexCliExecutor, ExecutorError, PiSdkExecutor, PiCliExecutor, RunRequest,
    RunResult, classify_error, _write_run_files,
)
from scripts.run_ci import run_cases
from scripts.run_eval import run_eval
from concurrent.futures import Future


class ModelAndProtocolTest(unittest.TestCase):
    def test_cli_defaults_match_daily_codex_acceptance(self):
        from scripts.run_ci import main
        with patch('sys.argv', ['run_ci', '--skill-path', '/tmp/demo', '--model', 'gpt-example']), patch(
                'scripts.run_ci.run_cases', return_value=({}, 0)) as run, patch('builtins.print'):
            main()
        args = run.call_args.args[0]
        self.assertEqual((args.executor, args.fallback_executor, args.purpose), ('codex', 'pi', 'acceptance'))

    def test_daily_hint_only_accepts_gpt_and_does_not_choose_model(self):
        import os
        from scripts.eval_runtime.configuration import discover_models
        for model in ('gpt-example', 'non-gpt'):
            with tempfile.TemporaryDirectory() as raw, patch.dict(os.environ, {'CODEX_HOME': raw}), patch(
                    'scripts.eval_runtime.configuration.shutil.which', return_value=None):
                Path(raw, 'config.toml').write_text(f'model = "{model}"\nmodel_reasoning_effort = "high"\n')
                result = discover_models()
                if model == 'gpt-example':
                    self.assertEqual(result['daily_environment']['model'], model)
                    self.assertEqual(result['daily_environment']['reasoning'], 'high')
                else:
                    self.assertIsNone(result['daily_environment'])
                    self.assertEqual(result['codex'], [])

    def test_explicit_gpt_choice_and_provider_conflict(self):
        self.assertEqual(gpt_model('gateway/gpt-example'), ('gateway', 'gpt-example'))
        self.assertEqual(gpt_model('gpt-next', 'local'), ('local', 'gpt-next'))
        for model in (None, 'sonnet', 'gemini-pro', '*gpt*', 'gpt-example:high'):
            with self.assertRaises(ValueError):
                gpt_model(model)
        with self.assertRaises(ValueError):
            gpt_model('one/gpt-example', 'two')

    def test_only_known_infrastructure_errors_allow_retry(self):
        for message in ('502 Bad Gateway', 'service unavailable', 'connection reset', 'Pi SDK bridge 超时'):
            self.assertEqual(classify_error(message), 'service')
        for message in ('403 forbidden 502', 'safety policy', 'permission denied', 'refusal'):
            self.assertEqual(classify_error(message), 'denied')
        for message in ('invalid_prompt', 'fixture miss'):
            self.assertEqual(classify_error(message), 'configuration')
        self.assertEqual(classify_error('unknown failure'), 'protocol')

    def test_pi_sdk_error_or_empty_output_never_completed(self):
        with tempfile.TemporaryDirectory() as raw:
            request = RunRequest('probe', '用户输入', 'without_skill', Path(raw), model='gateway/gpt-example')
            for payload in ({'status': 'failed', 'errors': [{'message': '502 Bad Gateway'}]},
                            {'final_answer': '', 'status': 'completed'},
                            {'final_answer': '95', 'errors': [{'message': 'invalid_prompt'}]}):
                with self.subTest(payload=payload), patch('shutil.which', return_value='/node'), patch(
                        'subprocess.run', return_value=subprocess.CompletedProcess([], 0, json.dumps(payload), '')):
                    with self.assertRaises(ExecutorError):
                        PiSdkExecutor().run(request)
                    self.assertTrue((Path(raw) / 'pi-sdk-response.json').exists())

    def test_pi_actual_settings_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            request = RunRequest('probe', '用户输入', 'without_skill', Path(raw), model='gateway/gpt-example')
            payload = {'status': 'completed', 'final_answer': '完成', 'actual_reasoning': 'high'}
            with patch('shutil.which', return_value='/node'), patch(
                    'subprocess.run', return_value=subprocess.CompletedProcess([], 0, json.dumps(payload), '')):
                with self.assertRaises(ExecutorError) as caught:
                    PiSdkExecutor().run(request)
            self.assertEqual(caught.exception.category, 'configuration')

    def test_pi_cli_stop_error_is_not_raw_json_answer(self):
        with tempfile.TemporaryDirectory() as raw:
            request = RunRequest('probe', '用户输入', 'without_skill', Path(raw), model='gateway/gpt-example')
            events = json.dumps({'type': 'agent_end', 'messages': [
                {'role': 'assistant', 'stopReason': 'error', 'errorMessage': '502 Bad Gateway', 'content': []}]})
            with patch('shutil.which', return_value='/pi'), patch('subprocess.run', side_effect=[
                subprocess.CompletedProcess([], 0, 'gateway gpt-example 100K', ''),
                subprocess.CompletedProcess([], 0, events, '')]):
                with self.assertRaises(ExecutorError) as caught:
                    PiCliExecutor().run(request)
                self.assertEqual(caught.exception.category, 'service')

    def test_codex_requires_completed_turn_and_nonempty_answer(self):
        with tempfile.TemporaryDirectory() as raw:
            request = RunRequest('probe', '用户输入', 'without_skill', Path(raw), model='gpt-example')
            for events in ([{'type': 'turn.failed', 'error': {'message': '502'}}],
                           [{'type': 'turn.completed'}],
                           [{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '95'}}]):
                with self.subTest(events=events), patch('shutil.which', return_value='/codex'), patch(
                        'scripts.eval_runtime.executors.codex_connection', return_value=(None, [])), patch(
                        'subprocess.run', return_value=subprocess.CompletedProcess([], 0, '\n'.join(map(json.dumps, events)), '')):
                    with self.assertRaises(ExecutorError):
                        CodexCliExecutor().run(request)

    def test_codex_prompt_does_not_include_grader_files(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / 'eval_metadata.json').write_text('SECRET_ASSERTION')
            skill = root / 'skill'; skill.mkdir()
            (skill / 'SKILL.md').write_text('本次公开指令')
            request = RunRequest('probe', '用户输入', 'with_skill', root, skill_path=skill, model='gpt-example')
            events = [{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '完成'}},
                      {'type': 'turn.completed', 'usage': {'input_tokens': 3, 'output_tokens': 1}}]
            def invoke(command, **kwargs):
                self.assertNotIn('SECRET_ASSERTION', kwargs['input'])
                self.assertIn('本次公开指令', kwargs['input'])
                self.assertNotEqual(Path(kwargs['cwd']), root)
                self.assertIn('--ignore-user-config', command)
                self.assertIn('shell_tool', command)
                return subprocess.CompletedProcess([], 0, '\n'.join(map(json.dumps, events)), '')
            with patch('shutil.which', return_value='/codex'), patch(
                    'scripts.eval_runtime.executors.codex_connection', return_value=(None, [])), patch('subprocess.run', side_effect=invoke):
                result = CodexCliExecutor().run(request)
            self.assertEqual(result.timing['total_tokens'], 4)


class TriggerFailureTest(unittest.TestCase):
    def test_failed_negative_probe_is_not_a_successful_nontrigger(self):
        class Pool:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def submit(self, *args):
                future = Future()
                future.set_exception(ExecutorError("502 service unavailable"))
                return future
        with patch("scripts.run_eval.ProcessPoolExecutor", return_value=Pool()):
            result = run_eval([{"query": "普通闲聊", "should_trigger": False}], "demo", "测试",
                              1, 10, Path("/tmp"), model="gateway/gpt-example")
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["results"][0]["pass"])
        self.assertEqual(result["results"][0]["evaluation_status"], "not_evaluated")


class FallbackTest(unittest.TestCase):
    def run_scenario(self, root, behavior, **overrides):
        skill = root / 'skill'; (skill / 'evals').mkdir(parents=True)
        (skill / 'SKILL.md').write_text('---\nname: demo\ndescription: 测试\n---\n')
        (skill / 'evals/evals.json').write_text(json.dumps({'skill_name': 'demo', 'evals': [
            {'id': 1, 'prompt': '公开任务', 'assertions': [{'type': 'contains', 'text': '满足结果', 'value': '正确'}]}]}))
        args = argparse.Namespace(skill_path=str(skill), evals=None, skill_name=None, executor='pi',
                                  pi_cli_fallback=True, gate_configuration='with_skill', runs=1,
                                  timeout=10, max_turns=2, max_tool_calls=2, max_output_tokens=100,
                                  model='gateway/gpt-example', provider=None, reasoning='medium',
                                  output_dir=str(root / 'results'), fallback_executor='codex',
                                  fallback_model='gpt-backup', codex_provider=None, selection_reason='测试选择')
        args.purpose = "smoke"
        args.fallback_provider = None
        args.fallback_reasoning = None
        for key, value in overrides.items():
            setattr(args, key, value)
        seen = []
        class Runner:
            def __init__(self, name): self.name = name
            def run(self, request):
                seen.append((self.name, request.configuration, request.model, request.provider, dict(request.limits)))
                answer = behavior(self.name, request)
                if isinstance(answer, RunResult): return answer
                result = RunResult(request.run_id, self.name, request.configuration, answer,
                                   model=request.model, provider=request.provider, metrics={'total_turns': 1})
                _write_run_files(request, result, __import__('time').monotonic())
                return result
        with patch('scripts.run_ci.create_executor', side_effect=lambda name, **kw: Runner(name)), patch(
                'scripts.run_ci.codex_connection', return_value=('backup', [])):
            summary, code = run_cases(args)
        return summary, code, seen

    def test_codex_primary_and_fallback_purpose(self):
        for purpose, expected in (("acceptance", 2), ("smoke", 0), ("portability", 0)):
            def behavior(name, request):
                if name == 'codex': raise ExecutorError('502 Bad Gateway')
                return '正确'
            with self.subTest(purpose=purpose), tempfile.TemporaryDirectory() as raw:
                summary, code, seen = self.run_scenario(Path(raw), behavior, executor='codex',
                    model='gpt-example', fallback_executor='pi', fallback_model='gateway/gpt-backup',
                    fallback_reasoning='high', purpose=purpose)
                self.assertEqual(code, expected)
                self.assertEqual([a['executor'] for a in summary['attempts']], ['codex', 'pi'])
                self.assertEqual(summary['final_attempt_status'], 'passed')
                self.assertFalse(summary['target_matched'])
                junit = Path(summary['attempts_file']).with_name('junit.xml').read_text()
                self.assertEqual('目标环境验收未完成' in junit, purpose == 'acceptance')
                self.assertEqual(seen[-1][-1]['reasoning'], 'high')
                self.assertEqual(seen[-1][2:], seen[-2][2:])
                self.assertEqual(summary['status'], 'target_unverified' if expected else 'passed')

    def test_codex_success_does_not_require_unused_pi_provider(self):
        with tempfile.TemporaryDirectory() as raw:
            summary, code, _ = self.run_scenario(Path(raw), lambda *_: '正确', executor='codex',
                model='gpt-example', fallback_executor='pi', fallback_model=None, purpose='acceptance')
            self.assertEqual(code, 0)
            self.assertTrue(summary['target_matched'])
            self.assertEqual(summary['conclusion_scope'], 'isolated_text')

    def test_missing_fallback_provider_preserves_primary_diagnostics(self):
        def behavior(*_): raise ExecutorError('502 Bad Gateway')
        with tempfile.TemporaryDirectory() as raw:
            summary, code, _ = self.run_scenario(Path(raw), behavior, executor='codex',
                model='gpt-example', fallback_executor='pi', fallback_model=None)
            self.assertEqual(code, 2)
            self.assertIn('Pi fallback', summary['fallback_configuration_error'])
            self.assertEqual(len(summary['attempts']), 1)

    def test_service_failure_rebuilds_both_configurations_with_one_setting(self):
        def behavior(name, request):
            if name == 'pi' and request.configuration == 'without_skill':
                raise ExecutorError('502 Bad Gateway')
            return '正确'
        with tempfile.TemporaryDirectory() as raw:
            summary, code, seen = self.run_scenario(Path(raw), behavior)
            self.assertEqual(code, 0)
            self.assertEqual([s[:2] for s in seen], [('pi', 'with_skill'), ('pi', 'without_skill'),
                                                   ('codex', 'with_skill'), ('codex', 'without_skill')])
            self.assertEqual(seen[2][2:], seen[3][2:])
            self.assertEqual(len(summary['attempts']), 2)
            self.assertTrue(Path(summary['attempts_file']).exists())

    def test_both_channels_unavailable_are_system_failure(self):
        def behavior(name, request): raise ExecutorError('502 Bad Gateway')
        with tempfile.TemporaryDirectory() as raw:
            summary, code, seen = self.run_scenario(Path(raw), behavior)
            self.assertEqual(code, 2)
            self.assertEqual(summary['status'], 'failed')
            self.assertEqual(len(summary['attempts']), 2)
            self.assertEqual(summary['completed_runs'], 0)
            benchmark = json.loads((Path(summary['output_dir']) / 'iteration-1/benchmark.json').read_text())
            self.assertEqual(benchmark['runs'], [])

    def test_runtime_unavailable_uses_pi_cli_before_codex(self):
        def behavior(name, request):
            if name == 'pi': raise ExecutorError('找不到 node', 'runtime')
            return '正确'
        with tempfile.TemporaryDirectory() as raw:
            summary, code, seen = self.run_scenario(Path(raw), behavior)
            self.assertEqual(code, 0)
            self.assertEqual([a['executor'] for a in summary['attempts']], ['pi', 'pi-cli'])

    def test_quality_denied_invalid_prompt_and_empty_output_do_not_switch(self):
        for outcome in ('错误答案', ExecutorError('403 forbidden'), ExecutorError('invalid_prompt'), ''):
            def behavior(name, request):
                if isinstance(outcome, Exception): raise outcome
                return outcome
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as raw:
                summary, code, seen = self.run_scenario(Path(raw), behavior)
                self.assertNotEqual(code, 0)
                self.assertEqual(len(summary['attempts']), 1)

    def test_returned_error_status_cannot_pass_even_with_expected_answer(self):
        def behavior(name, request):
            return RunResult(request.run_id, name, request.configuration, '正确', status='failed',
                             errors=[{'message': 'invalid_prompt'}])
        with tempfile.TemporaryDirectory() as raw:
            summary, code, seen = self.run_scenario(Path(raw), behavior)
            self.assertEqual(code, 2)
            self.assertEqual(summary['completed_runs'], 0)


if __name__ == '__main__':
    unittest.main()
