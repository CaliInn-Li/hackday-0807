# 第二个视频：动作提取与重定向核对

## 1. 原视频与 GVHMR 动作

- 原视频：854×480，24 fps，241 帧，约 10.042 秒。
- GVHMR 输出：HMR4D 结果转换为 SMPL22。
- SMPL22 动作数据：`video2_smpl22.npz`。
- 旋转数组：`[241, 22, 3, 3]`。
- 根节点平移：`[241, 3]`。
- 动作预览：`1_incam.mp4` 是相机坐标下的拟合结果，`2_global.mp4` 是世界坐标下的全局运动。

## 2. 正确的骨骼映射

SkinTokens 的匿名骨骼顺序是 Mixamo 语义顺序，不能直接按 `bone_N → SMPL[N]` 映射。

| 目标骨骼 | 语义 | SMPL22 索引 |
| --- | --- | ---: |
| bone_0 | Hips | 0 |
| bone_1 | Spine | 3 |
| bone_2 | Spine1 | 6 |
| bone_3 | Spine2 | 9 |
| bone_4 | Neck | 12 |
| bone_5 | Head | 15 |
| bone_6 | LeftShoulder | 13 |
| bone_7 | LeftArm | 16 |
| bone_8 | LeftForeArm | 18 |
| bone_9 | LeftHand | 20 |
| bone_10 | RightShoulder | 14 |
| bone_11 | RightArm | 17 |
| bone_12 | RightForeArm | 19 |
| bone_13 | RightHand | 21 |
| bone_14 | LeftUpLeg | 1 |
| bone_15 | LeftLeg | 4 |
| bone_16 | LeftFoot | 7 |
| bone_17 | LeftToeBase | 10 |
| bone_18 | RightUpLeg | 2 |
| bone_19 | RightLeg | 5 |
| bone_20 | RightFoot | 8 |
| bone_21 | RightToeBase | 11 |

## 3. 旋转、坐标与根节点处理

GVHMR/SMPL 坐标系是 X 右、Y 上、Z 前；Blender 坐标系是 X 右、Y 后、Z 上。每帧、每个关节先做：

```text
C = [[1, 0, 0],
     [0, 0,-1],
     [0, 1, 0]]
R_blender = C * R_smpl * Cᵀ
```

然后按目标骨骼的绑定姿态处理局部旋转：

```text
basis = rest_rotation⁻¹ * R_blender * rest_rotation
```

根节点平移使用相对首帧位移，并按目标角色高度与 SMPL 身高的比例缩放：

```text
displacement = C * (translation - translation_first_frame)
displacement_target = displacement * target_height / source_height
```

最终以 24 fps 写入 241 帧 Blender Action，再导出 GLB。

## 4. 已确认的旧错误

旧版本曾使用 `bone_N → SMPL[N]` 的身份映射。例如旧版本把 `bone_1`（Spine）错误地接到了 SMPL22 的 1 号关节（左髋）。这会造成躯干、肩膀、手臂和腿全部错位。

本目录中的 `*_corrected_*` 文件使用上表的修正映射；没有 `_corrected_` 后缀的旧文件保留作错误版本对照。

## 5. 边界

GVHMR 这里提供的是 22 个身体关节，不包括手指、弓箭等道具。骨架预览只显示重定向后的 22 根身体骨骼，用来先判断动作和映射是否正确。
