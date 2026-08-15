import bpy


preferences = bpy.context.preferences.addons.get("cycles").preferences
scene = bpy.context.scene
scene.render.engine = "CYCLES"
for device_type in ("OPTIX", "CUDA", "HIP", "ONEAPI"):
    try:
        preferences.compute_device_type = device_type
        preferences.get_devices()
        devices = [(device.name, device.type, bool(device.use)) for device in preferences.devices]
        scene.cycles.device = "GPU"
        print({"compute_device_type": device_type, "scene_cycles_device": scene.cycles.device, "devices": devices})
    except Exception as exc:
        print({"compute_device_type": device_type, "error": str(exc)})
