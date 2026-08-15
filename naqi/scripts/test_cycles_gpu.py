import bpy


scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 32
scene.cycles.use_denoising = False
preferences = bpy.context.preferences.addons["cycles"].preferences
preferences.compute_device_type = "CUDA"
preferences.get_devices()
for device in preferences.devices:
    device.use = device.type != "CPU"
scene.cycles.device = "GPU"

bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=6, radius=2.0, location=(0, 0, 0))
mesh = bpy.context.object
material = bpy.data.materials.new("GPUProbeMaterial")
material.diffuse_color = (0.2, 0.5, 0.9, 1.0)
mesh.data.materials.append(material)

camera_data = bpy.data.cameras.new("GPUProbeCamera")
camera = bpy.data.objects.new("GPUProbeCamera", camera_data)
bpy.context.collection.objects.link(camera)
camera.location = (0, -8, 2)
camera.rotation_euler = (1.35, 0, 0)
camera.data.lens = 50
scene.camera = camera

light_data = bpy.data.lights.new("GPUProbeLight", "AREA")
light_data.energy = 1500
light_data.shape = "DISK"
light_data.size = 5
light = bpy.data.objects.new("GPUProbeLight", light_data)
bpy.context.collection.objects.link(light)
light.location = (3, -4, 5)
light.rotation_euler = (0.5, 0, 0.5)

scene.render.resolution_x = 512
scene.render.resolution_y = 512
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = "/tmp/cycles_gpu_probe.png"
bpy.ops.render.render(write_still=True)
print({
    "scene_cycles_device": scene.cycles.device,
    "compute_device_type": preferences.compute_device_type,
    "devices": [(device.name, device.type, bool(device.use)) for device in preferences.devices],
})
