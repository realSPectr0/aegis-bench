"""Use the existing full runner with an observed Part 1 child process.

With `--wrapper pentestgpt|cai|vulnbot|aegisagent`, `--model` and `--base-url` name the Ollama backend:
the wrapper is started in front of it for the run and stopped afterwards.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import gauntlet_runner as runner
import wrapper_launch


def option(argv, flag, default=None):
    return argv[argv.index(flag) + 1] if flag in argv else default


def replace_option(argv, flag, value):
    if flag in argv:
        argv[argv.index(flag) + 1] = value
    else:
        argv.extend([flag, value])


def start_wrapper(argv):
    """Pop --wrapper from argv; if given, start it and point the run at it."""
    wrapper = option(argv, '--wrapper')
    if not wrapper:
        return None
    index = argv.index('--wrapper')
    del argv[index:index + 2]
    backend = option(argv, '--model', runner.DEFAULT_TARGET_MODEL)
    base_url = option(argv, '--base-url', runner.DEFAULT_BASE_URL)
    num_ctx = int(option(argv, '--num-ctx', runner.DEFAULT_NUM_CTX))
    logs = HERE / 'logs'
    logs.mkdir(exist_ok=True)
    print(f'Starting {wrapper} wrapper in front of {backend}...', flush=True)
    process, endpoint, name = wrapper_launch.start(wrapper, backend, base_url, num_ctx,
                                                   logs / f'wrapper-{os.getpid()}.log')
    print(f'Wrapper ready at {endpoint} (recorded as {name})', flush=True)
    replace_option(argv, '--model', name)
    replace_option(argv, '--base-url', endpoint)
    # gauntlet_runner records this in run_config.json so the run can be resumed.
    os.environ['CLANKER_WRAPPER'] = json.dumps({'wrapper': wrapper, 'backend_model': backend,
                                                'backend_base_url': base_url})
    return process


if __name__ == '__main__':
    original_build = runner.build_commands

    def build_commands(args, run_dir):
        commands = original_build(args, run_dir)
        for _, command in commands:
            if Path(command[1]).name == 'benchmark_runner.py':
                command[1] = str(HERE / 'observe_questions.py')
            elif Path(command[1]).name == 'local_challenge_runner.py':
                command[1] = str(HERE / 'observe_local.py')
        return commands

    runner.build_commands = build_commands
    try:
        wrapper = start_wrapper(sys.argv)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f'error: could not start the wrapper: {exc}', file=sys.stderr, flush=True)
        raise SystemExit(2)
    try:
        code = runner.main()
    finally:
        if wrapper:
            wrapper.terminate()
            try:
                wrapper.wait(timeout=10)
            except Exception:
                wrapper.kill()
    raise SystemExit(code)
