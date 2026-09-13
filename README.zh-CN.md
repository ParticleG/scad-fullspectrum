# scad-fullspectrum

[English](README.md) | 简体中文

将带有颜色的 OpenSCAD 文件转换为 **Snapmaker Orca / FullSpectrum 项目 3MF**，
让每个 `color()` 作用域中的几何体通过四个工具头中所装耗材的混合配方打印。

```
./scad2fs3mf part.scad -o part.3mf -c spools.json
# or, from the repository root / with the package on PYTHONPATH:
python3 -m scad_fullspectrum part.scad -o part.3mf -c spools.json
```

本工具使用 Python 3，仅依赖标准库，无需安装第三方 Python 包；
需要在 `PATH` 中提供 `openscad` 可执行文件。

## 工作流程

1. 使用 `openscad -o model.csg model.scad` 展开设计。
   OpenSCAD 的 3MF 导出器会丢弃颜色，AMF 导出器则不支持多体积对象，
   但导出的 CSG 会保留每个 `color([r, g, b, a]) { ... }` 作用域。
2. 按颜色拆分 CSG 树，每种颜色生成一个部件，并遵守 OpenSCAD 的布尔运算语义：
   `difference()` 的主体保留自身颜色，切除体则从各颜色对应的几何体中扣除；
   `intersection()` 保留用于限定交集范围的子节点；
   `hull()`/`minkowski()` 归属于其内部出现的第一种颜色。
3. 将每种颜色与已装载的耗材进行匹配。若与某种耗材足够接近
   （ΔE₀₀ ≤ `pure_threshold`），则直接使用该耗材；否则，
   在以 `step` 个百分点为步长的网格上搜索最多包含 `components` 种耗材的混合配方。
   根据所选混色模型（`average`、`pigment` 或 `transmission`，见下文）预测混合颜色，
   并使用 CIEDE2000 色差对配方排序。
4. 使用与切片器自身输出相同的项目结构写入文件：
   `3D/3dmodel.model` 保存根对象，每种颜色对应一个组件；
   `3D/Objects/<name>_1.model` 保存网格；
   `Metadata/model_settings.config` 中每种颜色对应一个携带 `extruder` 的 `<part>`；
   `Metadata/project_settings.config` 保存耗材颜色、混合配方定义，
   以及从模板项目复制的其他全部设置。

虚拟耗材 ID 排在实体耗材槽位之后：使用四卷耗材时，第 *k* 行混合配方对应挤出机
`4 + k`，与切片器加载 `mixed_filament_definitions` 时采用的约定完全一致。

## 配置

```json
{
  "base_filaments": [
    { "slot": 1, "color": "#FF00FF", "name": "Magenta" },
    { "slot": 2, "color": "#00FFFF", "name": "Cyan" },
    { "slot": 3, "color": "#808080", "name": "Grey" },
    { "slot": 4, "color": "#FFFF00", "name": "Yellow" }
  ],
  "uncolored": 3,
  "mix": { "components": 4, "step": 5, "pure_threshold": 1.0, "max_mixes": null, "model": "average" },
  "printer": { "bed": [270.0, 270.0] },
  "template": "templates/project_settings.config"
}
```

| 配置键 | 含义 |
| --- | --- |
| `base_filaments` | 实际装载的四卷耗材，按工具头顺序排列；`color` 为耗材的显示颜色 |
| `uncolored` | 不属于任何 `color()` 作用域的几何体如何处理：可填写十六进制颜色值或槽位索引；默认丢弃并发出警告 |
| `mix.components` | 每个配方最多包含的耗材种数，范围为 2–4；默认 4，省略该字段时同样为 4 |
| `mix.step` | 候选配方的百分比网格步长，默认 5 % |
| `mix.pure_threshold` | 直接使用某种耗材、不进行混合的 ΔE₀₀ 阈值，默认 1.0 |
| `mix.max_mixes` | 虚拟耗材数量上限；持续合并感知颜色最接近的配方，直到满足上限；报告中的混合颜色和 ΔE 始终对应最终实际分配的配方 |
| `mix.model` | 搜索和预测所用的混色模型：`average`、`pigment` 或 `transmission`；默认 `average`，详见[混色模型](#混色模型) |
| `printer.bed` | 打印平台尺寸；模型会居中放置 |
| `template` | 用于复制设置的 `project_settings.config` 或已切片的 `.3mf`，包括打印机、工艺、耗材预设、擦拭塔等 |
| `settings` | 合并到 `Metadata/project_settings.config` 中的任意覆盖设置 |

所有内置预设都允许最多四组分配方。配置省略 `mix.components` 或整个 `mix` 对象时，
也默认使用四组分上限；显式配置值和 `--components` 仍按优先级覆盖默认值。
这只是上限，并不要求每个配方都使用四卷耗材：更简单的配方仍可能胜出。
四组分搜索需要更多时间，尤其是在使用 `--step 1` 时，也可能增加工具头切换次数。
如果更看重搜索速度或减少工具头切换，可使用 `--components 2` 或 `3`。

### 预设

工具内置了多组耗材配置，无需配置文件即可开始使用：

```
./scad2fs3mf --list-presets
./scad2fs3mf part.scad -o part.3mf --preset translucent-cmyn
```

| 预设 | 槽位代码（1-4） | 耗材 | 模型 |
| --- | --- | --- | --- |
| `translucent-cmyn` | C M Y N | 半透明青色、品红色、黄色、中性灰色 | `transmission`（实验性） |
| `pla-cmyk` | C M Y K | 青色、品红色、黄色、黑色 | `pigment` |
| `pla-cmyw` | C M Y W | 青色、品红色、黄色、白色 | `pigment` |
| `pla-cmyn` | C M Y N | 青色、品红色、黄色、中性灰色 | `pigment` |
| `pla-rybw` | R Y B W | 红色、黄色、蓝色、白色 | `pigment` |

预设名称采用 `<material>-<codes>` 格式，代码按槽位顺序直接拼接，
例如 `pla-cmyk`、`pla-cmyw`、`pla-cmyn`、`pla-rybw`。
各字母含义为：`C` 青色、`M` 品红色、`Y` 黄色、`K` 黑色、`W` 白色、
`R` 红色、`B` 蓝色、`G` **绿色**、`N` **中性灰色**。
因此，即使六卷或八卷耗材组合同时包含绿色和灰色，也不会产生歧义；
更多槽位只需继续拼接字母。只有这些字母是保留代码，其他耗材名称
（例如本色耗材“natural”）应完整拼写。`presets.validate()` 会检查这一命名约定。

预设中的颜色只是理想化的占位值：请测量自己的耗材并替换这些值。

**覆盖预设。** 优先级为：预设 < 配置文件 < 显式命令行参数。
配置文件只替换其包含的键：`base_filaments` 是列表，因此文件若提供了自己的耗材，
就会*替换预设的全部耗材及槽位映射*；文件未提供的键继续沿用预设，
而 `mix` 按键逐项合并。若要保留预设耗材、只修改模型，可使用命令行参数或最小配置文件：

```
./scad2fs3mf part.scad -o part.3mf --preset pla-cmyk --mix-model average
echo '{"mix": {"model": "average"}}' > model-only.json
./scad2fs3mf part.scad -o part.3mf --preset pla-cmyk -c model-only.json
```

也可以从文件指定耗材，或使用 `-c` 后接预设名称来代替 `--preset`。
注意：文件中的四条耗材记录会覆盖预设中的记录。

```
./scad2fs3mf part.scad -o part.3mf --preset pla-cmyk -c my-spools.json
./scad2fs3mf part.scad -o part.3mf -c pla-rybw
```

目前尚未提供超过四卷耗材的内置组合。规划器已经接受 *N* 个连续槽位，
但随附模板中的数组仍按四槽位配置，因此更多槽位的项目需要使用从切片器导出的匹配设置模板。

`python3 -m scad_fullspectrum --print-example-config` 可输出基础配置示例。
`--help` 会列出可覆盖配置的参数，例如 `--components`、`--max-mixes`、
`--mix-model`、`--template`、`--uncolored` 等。
对于参数化设计，可以直接传入 OpenSCAD 参数定义：

```
python3 -m scad_fullspectrum examples/hue-wheel.scad -o wheel.3mf \
    -c examples/hue-wheel.json -D segments=60
```

### 模板项目

`templates/project_settings.config` 是完整的 Snapmaker U1 设置快照，
因此生成文件打开后会使用 U1 打印机、“0.08 High Quality”工艺和四种 PLA 耗材。
如果希望继承自己的预设，请传入从切片器保存的项目：

```
python3 -m scad_fullspectrum part.scad -o part.3mf -c spools.json --template my-project.3mf
```

## 示例

```
# built-in preset
./scad2fs3mf examples/hue-wheel.scad -o /tmp/wheel.3mf --preset pla-cmyw

# or a config file (examples/hue-wheel.json documents the file format)
./scad2fs3mf examples/hue-wheel.scad -o /tmp/wheel.3mf \
    -c examples/hue-wheel.json --report /tmp/wheel.json
```

报告会列出每种源颜色所选的挤出机、配方、预测混合颜色及其 ΔE₀₀。

## 颜色准确度

报告和命令行界面（CLI）摘要中的所有 ΔE₀₀ 都是**模型预测**：
它们比较源颜色与*所选模型*根据配方计算出的混合颜色，而不是对打印件的测量结果。
CLI 会输出摘要，包括中位数、最差值以及预测 ΔE 超过 10 的颜色数量；
`--report` 则提供逐颜色的详细信息。

`--mix-model`、`--step` 和 `--components` 可扩展或调整搜索空间。
下表使用随附示例中的耗材颜色，对 60 色色轮进行计算，并显式指定组分数，
使这些结果不依赖默认值；对于理想化的 `#00FF…` 颜色值，还需注意下文的限制。

| 设置 | 混合配方数 | ΔE 中位数 | 最差 ΔE | 预测 ΔE > 10 的颜色数 |
| --- | --- | --- | --- | --- |
| `average`，`--components 2 --step 5` | 40 | 6.4 | 22.1 | 20/60 |
| `average`，`--components 2 --step 1` | 49 | 6.2 | 22.1 | 20/60 |
| `pigment`，`--components 2 --step 5` | 42 | 4.0 | 21.2 | 19/60 |
| `pigment`，`--components 3 --step 1` | 50 | 3.8 | 21.2 | 19/60 |
| `transmission`（实验性），`--components 2 --step 5` | 42 | 1.2 | 8.0 | 0/60 |
| `transmission`（实验性），`--components 2 --step 1` | 57 | 0.3 | 1.6 | 0/60 |

`transmission` 各行仅说明该色轮在*这一公式内部*可达。
模型尚未校准（见下文），因此这些结果**不能证明**相应耗材可以实际打印出该色轮。
只有 `average` 和 `pigment` 各行采用了行为具有外部参考依据的模型进行比较。

使用随附示例复现这些结果：

```
./tools/bench_mixes.py examples/hue-wheel.scad --preset translucent-cmyn \
    --models -D segments=60
```

* 对于饱和色轮，在不透明模型下，`--step 1` 对准确度的提升很小：
  60 种颜色中只有 4 种的 ΔE 改善超过 0.5。
  它主要用于避免相邻颜色落到同一个 5 % 网格点上，共用槽位的颜色数由 17 降至 8。
* `--components 3` 对饱和色没有可测得的增益，但对低饱和度颜色影响很大：
  在不透明模型下，`#B0B0B0` 的 ΔE 从 14.9 降至 2.2，
  `#93A9D1` 从 9.7 降至 1.8。三组分配方能在 Snapmaker Orca 2.3.6 中正确加载和显示，
  但这只验证了解析和显示，并未验证混色运算。
* `--max-mixes N` 会合并最接近的配方。它用于减少工具头切换，而不是改善颜色。

`tools/bench_mixes.py part.scad spools.json --models` 会让一个设计遍历
模型、组分数、步长的各个组合，并输出相同形式的表格。

以下两点容易被误解，计算结果实际说明的是：

* *色域限制*：在**不透明**模型下，品红色、青色、黄色、灰色无法混出饱和红色或蓝色，
  对应 ΔE 为 13-22，因为不透明混色仍处于耗材颜色构成的凸包内。
  半透明耗材能否表现得更好，取决于实际打印件。
  实验性的 `transmission` 模式提示了可能的方向：叠放的半透明层通过滤光作用混色，
  而不是对颜色取平均；但它无法回答实际效果如何，本文也未将这些结果与打印实物核对。
* *四组分混色*：四卷耗材的颜色凸包是一个非退化四面体，
  因为 `#808080` 不在品红色、青色、黄色构成的平面上。
  因此，两组分和三组分配方只能到达其边和面，内部颜色需要全部四种耗材。
  对所计算的色轮，这一点没有影响：饱和色位于凸包表面，三组分和四组分都没有优于两组分。
  不要将这一结论推广到低饱和度或去饱和的设计。

请将耗材的*实测*十六进制颜色值填入 `base_filaments`。
类似 `#00FFFF` 的理想化数值会让预测结果偏乐观。

## 混色模型

| 模型 | 假设 | 适用场景 |
| --- | --- | --- |
| `average` | 在 sRGB 空间中进行加权平均 | 不透明耗材、快速计算；对饱和色结果较保守 |
| `pigment` | 使用切片器的四次颜料混色多项式（`FilamentMixerModel.hpp`，MIT 许可） | 预测切片器显示的色块：从 Snapmaker Orca 2.3.6 中采样了本工具所写配方的两个色块，各通道复现误差均不超过 2/255，其中一个逐字节完全一致 |
| `transmission`（**实验性**） | 将输入的显示用十六进制颜色值当作“单层”透射率，假设底衬为白色，并将零值通道按 `1e-6` 处理 | 在搜索配方时展示减色混合的*变化方向*，不能作为颜色保证 |

`transmission` 没有参考厚度、实测吸收数据或光照模型，
因此其 ΔE 仅反映公式内部的比较。相信其中任何数值之前，都应先打印混合色块进行校准。
CLI 会输出警告，`--report` 也会将此次运行标记为实验性。

所有模型都不等于物理测量：层高、不透明程度（TD）、清料、表面状态、底衬和观察光照，
都会改变打印结果。

## 半透明耗材

半透明耗材通过滤光而不是遮盖产生颜色，因此不透明材料的“对颜色取平均”思路并不适用。
本工具的能力边界如下：

* 可以在所选近似模型下对配方排序。
* 无法预测实物打印颜色：缺少吸收光谱、参考厚度、底衬和光照模型。
  `mix.model:
  "transmission"` 是实验性功能，应使用打印色块进行校准。

请按照打印件实际使用的观察方式进行校准：

1. **反射观察**（光从观察者一侧照射）：在目标厚度下测量纯色和混合色块，
   并保持底衬、光照和观察面一致。校准时保持配方分配固定，另留独立配方用于验证。
   仅凭显示用 HEX 值无法确定吸收或散射性质；修改 `mix.step` 或 `mix.components`
   只会改变搜索空间，而不会改变物理模型。
2. **透射／背光观察**（薄壁、灯罩、扩散罩等，是半透明 PLA 的已知用途）：
   评价的是穿过打印件的光，因此应在背光条件下校准，而不是依赖底衬。
   将相同的色块网格打印成薄壁，并从背面照明进行比较。
   反射性白色底衬会破坏这一观察方式，因此不要在此模式下强行加入白色底衬。

两种模式都需要注意：

* 交错薄层可能同时产生光谱滤波、散射和空间平均效应。
  层顺序、表面朝向和观察距离都很重要。
* 灰色耗材不一定是光谱中性的滤光材料。
  不透明白色耗材或底衬会改变光学系统，需要单独校准。
* 厚度会影响色相、明度和彩度，不能假定饱和度总会随厚度增加。
* 半透明材料上的清料／预挤出塔和空移造成的拖痕，比不透明材料更明显；
  请为擦拭参数留出充分余量。

### Panchroma CMYN 校准套件

无需调用颜色求解器，即可生成配方精确指定的测试项目：

```sh
python3 tools/make_panchroma_calibration.py calibration/runs/new-run
```

输出目录必须尚不存在。槽位顺序为 **1=Cyan（青色）、2=Magenta（品红色）、
3=Yellow（黄色）、4=Grey（灰色，N）**，第四槽位不是黑色。
脚本使用随附的 Snapmaker U1 0.4 mm 喷嘴打印机模板。
厂商 HEX／透光距离（Transmission Distance，TD）元数据来自
[Polymaker 的表格](https://wiki.polymaker.com/polymaker-products/more-about-our-products/hex-codes-and-transmission-distances)，
这些值既不是透射率光谱，也不是混合颜色的实测值。

[Snapmaker 的颜色参考](https://wiki.snapmaker.com/en/snapmaker_orca/full_spectrum_color_reference)
还提供了 39 个配方的照片，以及可下载的 177 色项目。
它是视觉参考，不是混合颜色的数值测量数据集。
其[耗材 TD 表](https://s3.us-west-2.amazonaws.com/snapmaker.com/download/manual/PLA+Full+Spectrum+Filament+Bundle+Hex+Code+%26+TD+Value+Table.pdf)
使用相同的 HEX 值，但 C/M/Y/Gray 的 TD 分别为 5.5/5.5/9.5/6.5，
而 Polymaker 给出的值为 8/7.8/14/11.5。
HEX 相同并不能证明这些产品或批次具有相同的光学特性，不能盲目套用另一种耗材的校准结果。

| 项目 | 试片数量 | 用途 |
| --- | --- | --- |
| `thickness-cyan`、`thickness-magenta`、`thickness-yellow`、`thickness-grey` | 每卷耗材 11 个 | 测量纯材料在 0.16 至 15.36 mm 厚度范围内的响应 |
| `mix-fit` | 35 个配方 + 2 个重复性对照 | 覆盖 1-4 组分、以 25% 为步长的完整配比网格，厚度为 3.2 mm |
| `mix-holdout` | 20 个 | 独立的两组分、三组分、四组分配方，不参与拟合 |
| `layer-order` | 6 个 | 比例相同、材料块顺序相反或交错排列的叠层；使用实体槽位，而非虚拟混色 |

请将 **3MF** 文件作为项目打开。SCAD 文件仅用于几何参考，
通过常规颜色求解 CLI 转换它们，无法保留已明确指定的虚拟配方。
SVG 布局图从上方标识试片，图的底部为前方，每个试片的左前角均有切角。
标签**不会打印**：取下试片前应先拍摄整板照片，再将 ID 转移到容器或非测量区域的边缘。
`samples.csv` 记录配比和布局；`measurements.csv` 除 ID 和观察模式外有意留空。
`manifest.json` 记录预期工艺和来源元数据，而不是实测结果。

**打印前：** 核对实际打印机、已装载耗材的槽位顺序和材料温度。
校准工艺明确设置为 0.08 mm 层高、0.16 mm 首层、100% 直线填充、不熨烫、不生成支撑。
校准与验证时应保持这些条件不变。检查擦拭塔间距和切片后的工具头分配，尤其注意薄试片。
虚拟配方百分比只是向切片器提出的请求，不是实测挤出比例；
请保留 G-code，并记录层数取整和首层效应。
层顺序对照采用 0.16 mm 厚的材料块：通常对应两个 0.08 mm 层，
但第一个材料块对应单个 0.16 mm 首层。
中央测量区域没有贯穿其中的永久底衬或标签几何体。

**测量：** 使用每个 20 x 20 mm 试片中央的 10 x 10 mm 区域。
测量实际厚度时，不要压坏薄试片。记录耗材批次、打印批次、观察面、旋转角度和光照条件。
将白底反射、黑底反射和背光透射分别保存为独立数据集。
每次读数都应重新定位并至少重复三次；选择部分对照试片重新打印，
以区分采集重复性和打印机重复性。
拍照时尽可能使用 RAW、固定曝光和白平衡、颜色参考、均匀光照，
并确保中央测量区域没有通道数值截断。
未经颜色校准的相机 RGB 不是绝对 Lab 测量，相机通道也无法还原完整光谱。
测量光谱透射率需要具备透射测量能力的分光光度计；对于散射样品，
还应注意总透射与直接透射的区别，以及测量孔径。

可先从实测配方的最近邻匹配，或实测配比网格内的插值开始。
不要让 `mix-holdout` 参与模型拟合，应单独报告其误差。
这套工具主要表征从上方观察的平面色块；其他厚度、侧壁、底衬材料和层顺序仍需分别验证。
它不会为 CLI 安装已校准的颜色模型。

For the generated i1Pro 2 recording sheet and field guide, see
[i1Pro 2 recording protocol](README.md#i1pro-2-recording-protocol).
For local experiment storage and measured-data promotion, see
[Calibration artifacts](README.md#calibration-artifacts).

## 注意事项

* `color([r, g, b, a])` 中的 Alpha 会被忽略，打印机不会直接复现该透明度参数。
* 无法对包含多种颜色的 `hull()`/`minkowski()` 进行有意义的按色拆分；
  整体使用其内部发现的第一种颜色打印。
* 每种颜色都会成为一个单独指定挤出机的部件，因此一百种颜色的设计意味着
  一百种虚拟耗材和大量工具头切换。可使用 `mix.max_mixes` 合并相似颜色。
* 混色通过薄层耗材交替堆叠产生光学效果。本工具报告的是模型预测，
  实物颜色还取决于耗材的不透明程度（TD）、层高、温度、速度和颜色下方的基底。
  建议从模板提供的 0.08 mm 工艺开始，在打印大型作品之前先打印色块进行校准。
* 构建版本 `01.10.01.50` 的 snapmaker-orca **CLI** 在加载 3MF 项目时会崩溃
  （`normalize_fdm`），因此请从图形界面（GUI）进行切片。

## 测试

```
python3 -m unittest discover -s tests
```

测试套件覆盖 CSG 解析与拆分（嵌套作用域、切除体、凸包、背景／根修饰符）、
配方行编码、求解器与规划规则，以及生成项目的结构、挤出机分配、设置覆盖和平台居中。
如果已安装 OpenSCAD，流水线测试还会实际运行 OpenSCAD。
