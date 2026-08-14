import argparse
import os
import sys
from pathlib import Path
from types import SimpleNamespace


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the original SkinTokens CLI with a cold-start-safe bpy timeout."
    )
    parser.add_argument("--skintokens-home", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--server-timeout", type=float, default=180.0)
    parser.add_argument("--use-transfer", action="store_true")
    parser.add_argument("--use-postprocess", action="store_true")
    return parser.parse_args()


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
    demo.start_bpy_server()
    demo.wait_for_bpy_server(timeout=args.server_timeout)
    demo.run_cli(cli_args)


if __name__ == "__main__":
    main()
