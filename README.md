# 三色灯色差分析工具 · Signal Light ΔE Checker

一个桌面小工具：分别加载样品和对标品的照片，在灯罩上取色，计算两者的 CIE ΔE 2000 色差，并给出人眼可察觉程度的评价。适合三色灯（塔灯、信号灯）和 LED 灯罩的来料或样品颜色比对。

> **English:** A small Tkinter desktop tool that compares the colour of two lamp photos (sample vs. reference) and reports the CIEDE2000 colour difference with a plain-language rating.

## 功能

- 左右并排加载样品图和对标品图（jpg / png / bmp / tif）
- 两种取色方式：**圆形点击**（半径可调）和**矩形框选**
- **自动检测**：自动找出图中最亮的灯罩区域，排除过曝的中心后取颜色
- 显示双方的 RGB、CIELAB 数值和 ΔE 2000，并按色差大小分级评价
- 历史记录表，方便连续比对多组样品

## 色差评价标准

| ΔE 2000 | 评价 |
|---|---|
| < 1 | 人眼几乎无法察觉（优秀） |
| 1 – 2 | 人眼难以察觉（良好） |
| 2 – 3.5 | 可察觉轻微差异（可接受） |
| 3.5 – 5 | 明显可察觉（需注意） |
| 5 – 10 | 明显是不同颜色（差异较大） |
| ≥ 10 | 完全不同的颜色 |

这些阈值是通用的经验值。正式判定请以你们的检验标准为准。

## 安装与运行

需要 Python 3.10 或更高版本。

```bash
pip install -r requirements.txt
python color_diff_tool.py
```

Windows 上也可以双击 `start.bat` 启动。

## 注意事项

- 照片取色会受相机白平衡、曝光和环境光影响。两张照片要在**同一台相机、同样的设置和光照**下拍摄，结果才有可比性。
- 本工具按 sRGB 和 D65 白点换算 LAB，结果适合用来做相对比较，不能代替色差仪的测量。

## 许可证

[MIT](LICENSE)
