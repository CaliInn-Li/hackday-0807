import argparse
import json
import os
import random
import struct
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from rig_contract import SKINTOKENS_TRANSFER_ARMATURE_NAME


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the original SkinTokens CLI with a cold-start-safe bpy timeout."
    )
    parser.add_argument("--skintokens-home", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--server-timeout", type=float, default=600.0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--use-skeleton",
        action="store_true",
        help="Preserve the supplied SMPL-22 skeleton and generate skin weights only.",
    )
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


def build_cli_args(args, demo):
    return SimpleNamespace(
        input=str(Path(args.input).resolve()),
        output=str(Path(args.output).resolve()),
        top_k=5,
        top_p=0.95,
        temperature=1.0,
        repetition_penalty=2.0,
        num_beams=10,
        use_skeleton=args.use_skeleton,
        use_transfer=args.use_transfer,
        use_postprocess=args.use_postprocess,
        model_ckpt=demo.MODEL_CKPTS[0],
        hf_path=None,
    )


def seed_everything(seed):
    random.seed(seed)
    try:
        import numpy

        numpy.random.seed(seed)
    except ImportError:
        pass
    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except ImportError:
        pass


def validate_transfer_input_glb(path):
    """Fail before GPU inference when the fixed skeleton cannot be transferred."""
    path = Path(path).resolve()
    if path.suffix.lower() != ".glb":
        raise RuntimeError("Fixed-skeleton production input must be a GLB")
    with path.open("rb") as stream:
        header = stream.read(20)
        if len(header) != 20:
            raise RuntimeError(f"Invalid GLB header: {path}")
        magic, version, _, json_length, chunk_type = struct.unpack("<IIIII", header)
        if magic != 0x46546C67 or version != 2 or chunk_type != 0x4E4F534A:
            raise RuntimeError(f"Invalid GLB 2.0 JSON chunk: {path}")
        payload = json.loads(stream.read(json_length).decode("utf-8"))
    skins = payload.get("skins", [])
    if len(skins) != 1:
        raise RuntimeError(
            f"Fixed-skeleton input must contain exactly one skin, found {len(skins)}"
        )
    skin = skins[0]
    if len(skin.get("joints", [])) != 22:
        raise RuntimeError(
            f"Fixed-skeleton input must contain 22 joints, found {len(skin.get('joints', []))}"
        )
    skin_name = skin.get("name")
    if skin_name != SKINTOKENS_TRANSFER_ARMATURE_NAME:
        raise RuntimeError(
            "Fixed-skeleton input uses armature/skin name "
            f"{skin_name!r}; SkinTokens transfer currently requires "
            f"{SKINTOKENS_TRANSFER_ARMATURE_NAME!r}. Re-run stage 1A."
        )
    return skin_name


def main():
    args = parse_args()
    transfer_armature_name = None
    if args.use_skeleton and args.use_transfer:
        transfer_armature_name = validate_transfer_input_glb(args.input)
    home = Path(args.skintokens_home).resolve()
    os.chdir(home)
    sys.path.insert(0, str(home))
    import demo

    seed_everything(args.seed)
    cli_args = build_cli_args(args, demo)
    print(
        "[Main] "
        + json.dumps(
            {
                "contract_mode": "fixed-smpl22" if args.use_skeleton else "free-generation",
                "use_skeleton": cli_args.use_skeleton,
                "use_transfer": cli_args.use_transfer,
                "use_postprocess": cli_args.use_postprocess,
                "seed": args.seed,
                "transfer_armature_name": transfer_armature_name,
                "input": cli_args.input,
                "output": cli_args.output,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    server_process = demo.start_bpy_server()
    wait_for_bpy_server(demo, server_process, timeout=args.server_timeout)
    demo.run_cli(cli_args)


if __name__ == "__main__":
    main()
