import argparse
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the original SkinTokens CLI with a cold-start-safe bpy timeout."
    )
    parser.add_argument("--skintokens-home", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--server-timeout", type=float, default=600.0)
    parser.add_argument("--use-transfer", action="store_true")
    parser.add_argument("--use-postprocess", action="store_true")
    return parser.parse_args()


def wait_for_bpy_server(demo, process, timeout):
    started = time.monotonic()
    next_progress = 0.0
    last_error = None
    while True:
        elapsed = time.monotonic() - started
        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(
                f"bpy_server exited before becoming ready (exit={exit_code}, elapsed={elapsed:.1f}s)"
            )
        try:
            response = demo.requests.get(f"{demo.BPY_SERVER}/ping", timeout=2)
            response.raise_for_status()
            print(f"[Main] bpy_server is ready after {elapsed:.1f}s", flush=True)
            return
        except Exception as error:
            last_error = error

        if elapsed >= next_progress:
            print(
                f"[Main] Waiting for bpy_server: elapsed={elapsed:.0f}s, "
                f"pid={process.pid}, timeout={timeout:.0f}s",
                flush=True,
            )
            next_progress = elapsed + 10.0
        if elapsed >= timeout:
            raise RuntimeError(
                f"bpy_server did not become ready within {timeout:.0f}s; "
                f"process is still alive (pid={process.pid}); last error: {last_error}"
            )
        time.sleep(1.0)


def main():
    args = parse_args()
    home = Path(args.skintokens_home).resolve()
    os.chdir(home)
    sys.path.insert(0, str(home))
    import demo

    cli_args = SimpleNamespace(
        input=str(Path(args.input).resolve()),
        output=str(Path(args.output).resolve()),
        top_k=5,
        top_p=0.95,
        temperature=1.0,
        repetition_penalty=2.0,
        num_beams=10,
        use_skeleton=False,
        use_transfer=args.use_transfer,
        use_postprocess=args.use_postprocess,
        model_ckpt=demo.MODEL_CKPTS[0],
        hf_path=None,
    )
    server_process = demo.start_bpy_server()
    wait_for_bpy_server(demo, server_process, timeout=args.server_timeout)
    demo.run_cli(cli_args)


if __name__ == "__main__":
    main()
