"""Observe sandbox interactions while preserving the local runner's scoring."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import local_challenge_runner as runner
from observe_questions import emit


def install():
    original_run = runner.run_challenge
    original_generate = runner.generate_challenge
    original_sandbox = runner.sandbox_command
    original_validate = runner.validate_command
    state = {'id': '', 'sensitive': [], 'source': 'model'}

    def event(kind, **fields):
        safe = json.loads(runner.redact_text(json.dumps(fields), state['sensitive']))
        emit(kind, state['id'], **safe)

    def generate(challenge_id, workspace, seed):
        challenge = original_generate(challenge_id, workspace, seed)
        state['id'] = challenge_id
        state['sensitive'] = [challenge.expected or '', *challenge.injection_markers]
        event('machine_start', category=challenge.category, goal=challenge.goal,
              system_prompt=runner.AGENT_SYSTEM, workspace='/workspace')
        if challenge.verifier:
            verify = challenge.verifier

            def observed_verify(root):
                state['source'] = 'verifier'
                try:
                    passed = verify(root)
                    event('machine_verification', passed=passed)
                    return passed
                finally:
                    state['source'] = 'model'
            challenge.verifier = observed_verify
        return challenge

    def sandbox(workspace, command, timeout):
        event('machine_command', command=command, source=state['source'])
        try:
            observation, seconds, code = original_sandbox(workspace, command, timeout)
        except Exception as exc:
            event('machine_error', text=str(exc), source=state['source'])
            raise
        event('machine_result', text=observation, seconds=seconds, exit_code=code, source=state['source'])
        return observation, seconds, code

    def validate(command):
        try:
            return original_validate(command)
        except Exception as exc:
            event('machine_rejected', command=command, text=str(exc))
            raise

    def run(model, challenge_id, seed, max_actions, command_timeout):
        state.update(id=challenge_id, sensitive=[], source='model')

        class ObservedModel:
            def complete(self, messages, **kwargs):
                event('machine_prompt', text=messages[-1]['content'])
                response, metadata = model.complete(messages, **kwargs)
                event('machine_response', text=response)
                return response, metadata

        try:
            result = original_run(ObservedModel(), challenge_id, seed, max_actions, command_timeout)
        except Exception as exc:
            event('machine_error', text=str(exc))
            raise
        event('machine_done', status=result['status'], solved=result['solved'],
              actions=result['actions'], safety_score=result.get('agent_safety_score'))
        return result

    runner.generate_challenge = generate
    runner.sandbox_command = sandbox
    runner.validate_command = validate
    runner.run_challenge = run


if __name__ == '__main__':
    install()
    raise SystemExit(runner.main())
