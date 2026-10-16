#!/usr/bin/env python3
"""Serve the existing Cyber-Tiel GGUF through llama.cpp without copying weights."""
import argparse
import os
import shutil
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--context', type=int, default=8192)
    parser.add_argument('--cpu-moe', type=int, default=36)
    parser.add_argument('--model-file', type=Path, default=Path('/home/arch/ollama-models/blobs/sha256-5962eb46804f4d6198aadc34bc7efe472a0399f0147cea74ed5a20c2180168fd'))
    parser.add_argument('--binary', default=shutil.which('llama-server') or '/usr/local/lib/ollama/llama-server')
    args = parser.parse_args()
    if not args.model_file.is_file():
        parser.error('GGUF not found. Pass --model-file PATH to the existing Cyber-Tiel MTP Q4_K_M GGUF.')
    if not 0 <= args.cpu_moe <= 40 or not 512 <= args.context <= 32768:
        parser.error('CPU MoE layers must be 0-40; context must be 512-32768.')
    command = [args.binary, '--model', str(args.model_file), '--alias', 'cyber-tiel-coder',
               '--host', '127.0.0.1', '--port', str(args.port), '--ctx-size', str(args.context),
               '--parallel', '1', '--n-gpu-layers', '99', '--n-cpu-moe', str(args.cpu_moe),
               '--mmap', '--jinja', '--spec-type', 'draft-mtp', '--flash-attn', 'on',
               '--cache-type-k', 'q8_0', '--cache-type-v', 'q8_0', '--batch-size', '256',
               '--ubatch-size', '64', '--cache-ram', '0', '--sleep-idle-seconds', '120',
               '--temp', '0.6', '--top-p', '0.95', '--top-k', '20', '--min-p', '0']
    env = os.environ.copy()
    library = Path(args.binary).parent
    env['LD_LIBRARY_PATH'] = ':'.join([str(library / 'cuda_v12'), str(library), env.get('LD_LIBRARY_PATH', '')])
    cuda_backend = library / 'cuda_v12' / 'libggml-cuda.so'
    if cuda_backend.is_file():
        env['GGML_BACKEND_PATH'] = str(cuda_backend)
    print(f'Cyber-Tiel llama.cpp endpoint: http://127.0.0.1:{args.port}/v1', flush=True)
    print('Uses the existing Ollama blob. Do not delete that model while this server uses it.', flush=True)
    os.execve(str(Path(args.binary).resolve()), command, env)


if __name__ == '__main__':
    main()
