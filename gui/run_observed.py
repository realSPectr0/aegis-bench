"""Use the existing full runner with an observed Part 1 child process."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import gauntlet_runner as runner


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
    raise SystemExit(runner.main())
