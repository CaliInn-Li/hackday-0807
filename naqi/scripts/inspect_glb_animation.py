import json
import struct
import sys
from pathlib import Path


def read_json(path):
    data = Path(path).read_bytes()
    if data[:4] != b"glTF":
        raise ValueError("not a GLB")
    json_length, json_type = struct.unpack_from("<II", data, 12)
    if json_type != 0x4E4F534A:
        raise ValueError("first GLB chunk is not JSON")
    return json.loads(data[20 : 20 + json_length].decode("utf-8").rstrip(" \x00"))


def main():
    document = read_json(sys.argv[1])
    skins = document.get("skins", [])
    meshes = document.get("meshes", [])
    animations = document.get("animations", [])
    durations = []
    for animation in animations:
        end = 0.0
        for sampler in animation.get("samplers", []):
            accessor = document["accessors"][sampler["input"]]
            if accessor.get("max"):
                end = max(end, float(accessor["max"][0]))
        durations.append(end)
    attributes = []
    for mesh in meshes:
        for primitive in mesh.get("primitives", []):
            attributes.append(sorted(primitive.get("attributes", {}).keys()))
    result = {
        "input": str(Path(sys.argv[1]).resolve()),
        "skins": len(skins),
        "skin_joint_counts": [len(skin.get("joints", [])) for skin in skins],
        "meshes": len(meshes),
        "primitive_attributes": attributes,
        "animations": len(animations),
        "animation_durations_seconds": durations,
        "animation_channels": [len(animation.get("channels", [])) for animation in animations],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
