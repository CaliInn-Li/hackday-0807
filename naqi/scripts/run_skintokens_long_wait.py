import argparse
import time

import requests
import torch

import demo
from src.server.spec import BPY_SERVER


def wait_for_bpy_server(timeout_seconds=180):
    started = time.time()
    while True:
        try:
            requests.get(f"{BPY_SERVER}/ping", timeout=2)
            print("[Driver] bpy_server is ready", flush=True)
            return
        except Exception as exc:
            elapsed = time.time() - started
            if elapsed > timeout_seconds:
                raise RuntimeError(f"bpy_server failed to start after {elapsed:.1f}s: {exc}")
            if int(elapsed) % 10 == 0:
                print(f"[Driver] waiting for bpy_server ({elapsed:.1f}s)", flush=True)
            time.sleep(0.5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("SkinTokens requires CUDA for this run, but torch.cuda.is_available() is false")
    print(
        f"[Driver] CUDA device: {torch.cuda.get_device_name(0)}; "
        f"capability={torch.cuda.get_device_capability(0)}",
        flush=True,
    )

    server_proc = demo.start_bpy_server()
    wait_for_bpy_server()
    cli_args = argparse.Namespace(
        input=args.input,
        output=args.output,
        top_k=5,
        top_p=0.95,
        temperature=1.0,
        repetition_penalty=2.0,
        num_beams=10,
        use_skeleton=True,
        # The official transfer path assumes an unrigged target.  With an
        # existing armature it removes the target armature and then looks up
        # the old object name, so use_skeleton should be tested through the
        # normal export path first.
        use_transfer=False,
        use_postprocess=False,
        model_ckpt=demo.MODEL_CKPTS[0],
        hf_path=None,
    )
    try:
        demo.run_cli(cli_args)
    finally:
        if server_proc.poll() is None:
            server_proc.terminate()


if __name__ == "__main__":
    main()
