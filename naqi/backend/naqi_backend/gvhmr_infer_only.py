"""Run the official GVHMR demo through PT export, without preview rendering.

This module is executed by GVHMR's own Python environment. It deliberately
reuses the repository's parser, preprocessing, config, and model code, then
stops as soon as ``hmr4d_results.pt`` is durable.
"""

from __future__ import annotations

import hydra
import torch
from pathlib import Path

from hmr4d.model.gvhmr.gvhmr_pl_demo import DemoPL
from hmr4d.utils.net_utils import detach_to_cpu
from hmr4d.utils.pylogger import Log
from tools.demo.demo import load_data_dict, parse_args_to_cfg, run_preprocess


@torch.no_grad()
def main() -> None:
    cfg = parse_args_to_cfg()
    paths = cfg.paths
    Log.info(f"[GPU]: {torch.cuda.get_device_name()}")
    run_preprocess(cfg)
    data = load_data_dict(cfg)
    if not Path(paths.hmr4d_results).exists():
        Log.info("[HMR4D] Predicting")
        model: DemoPL = hydra.utils.instantiate(cfg.model, _recursive_=False)
        model.load_pretrained_model(cfg.ckpt_path)
        model = model.eval().cuda()
        started = Log.sync_time()
        prediction = model.predict(data, static_cam=cfg.static_cam)
        prediction = detach_to_cpu(prediction)
        data_time = data["length"] / 30
        Log.info(
            f"[HMR4D] Elapsed: {Log.sync_time() - started:.2f}s "
            f"for data-length={data_time:.1f}s"
        )
        torch.save(prediction, paths.hmr4d_results)
    Log.info(f"[HMR4D] Motion saved: {paths.hmr4d_results}; preview rendering skipped")


if __name__ == "__main__":
    main()
