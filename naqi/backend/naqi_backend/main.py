from __future__ import annotations

import argparse
import asyncio

import uvicorn

from .api import build_app_pair
from .config import Settings


async def serve(settings: Settings) -> None:
    public_app, admin_app, runtime = build_app_pair(settings)
    public_server = uvicorn.Server(
        uvicorn.Config(
            public_app,
            host=settings.public_host,
            port=settings.public_port,
            log_level="info",
        )
    )
    admin_server = uvicorn.Server(
        uvicorn.Config(
            admin_app,
            host=settings.admin_host,
            port=settings.admin_port,
            log_level="info",
        )
    )
    runtime.start()
    try:
        await asyncio.gather(public_server.serve(), admin_server.serve())
    finally:
        public_server.should_exit = True
        admin_server.should_exit = True
        runtime.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the NAQI public and admin APIs")
    parser.add_argument("--public-host", default=None)
    parser.add_argument("--public-port", type=int, default=None)
    parser.add_argument("--admin-host", default=None)
    parser.add_argument("--admin-port", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = Settings.from_env()
    if args.public_host is not None or args.public_port is not None:
        settings = settings.__class__(
            **{**settings.__dict__, "public_host": args.public_host or settings.public_host,
               "public_port": args.public_port or settings.public_port}
        )
    if args.admin_host is not None or args.admin_port is not None:
        settings = settings.__class__(
            **{**settings.__dict__, "admin_host": args.admin_host or settings.admin_host,
               "admin_port": args.admin_port or settings.admin_port}
        )
    try:
        asyncio.run(serve(settings))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
