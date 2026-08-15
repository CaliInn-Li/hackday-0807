import json
import torch


checkpoint = torch.load(
    "/home/naqi/SkinTokens/experiments/articulation_xl_quantization_256_token_4/grpo_1400.ckpt",
    map_location="cpu",
    weights_only=False,
)
print(json.dumps({
    "tokenizer_config": checkpoint["hyper_parameters"]["tokenizer_config"],
    "predict_transform": checkpoint["hyper_parameters"]["transform_config"].get("predict_transform"),
}, ensure_ascii=False, default=str, indent=2))
