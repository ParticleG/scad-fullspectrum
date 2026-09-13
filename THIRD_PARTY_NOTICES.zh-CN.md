# 第三方声明

[English](THIRD_PARTY_NOTICES.md) | 简体中文

## FilamentMixerModel（颜料混色多项式）

`scad_fullspectrum/_pigment_model.py` 由 `FilamentMixerModel.hpp` 生成。
其中的颜料混色多项式被 OrcaSlicer、BambuStudio 和 Snapmaker Orca 等切片软件用于绘制耗材混色预览，
在这些项目中按 MIT 许可证分发。

以下版权声明与许可文本保留英文原文；中文说明不替代或修改这些许可条款。

```
FilamentMixer — Header-only C++ pigment color mixer

Copyright (c) 2026 Justin Hayes

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

使用 `tools/export_pigment_model.py <path/to/FilamentMixerModel.hpp>` 重新生成数据表。
