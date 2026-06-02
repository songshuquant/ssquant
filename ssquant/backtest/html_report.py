"""
HTML 交互式回测报告生成器
使用 Plotly 生成交互式图表，替代 matplotlib
支持多数据源、多品种回测结果展示
"""

import os
import json
import base64
from datetime import datetime
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np

# 自定义JSON编码器，处理NumPy和pandas数据类型
class NumpyEncoder(json.JSONEncoder):
    """处理 NumPy/pandas 数据类型的 JSON 序列化

    解决 pd.read_sql_query 读取整数类型（如成交价）时，
    返回 np.int64 导致 json.dumps 报错的问题。

    兼容性：Python 3.9+, NumPy 1.x/2.x, pandas 1.x/2.x
    """
    def default(self, obj):
        # NumPy 整数类型（np.integer 是所有 numpy 整数的基类）
        if isinstance(obj, np.integer):
            return int(obj)
        # NumPy 浮点类型（np.floating 是所有 numpy 浮点的基类）
        if isinstance(obj, np.floating):
            return float(obj)
        # NumPy 布尔类型
        if isinstance(obj, np.bool_):
            return bool(obj)
        # NumPy 数组
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        # pandas Timestamp 或其他带 isoformat 的时间类型
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        # 处理 pandas NA/NaN 值（需要 try-except 因为某些类型会报错）
        try:
            if pd.isna(obj):
                return None
        except (TypeError, ValueError):
            pass
        # 兜底：通过类型名称判断（处理某些版本差异导致的遗漏）
        type_name = type(obj).__name__.lower()
        if 'int' in type_name:
            try:
                return int(obj)
            except (TypeError, ValueError):
                pass
        if 'float' in type_name:
            try:
                return float(obj)
            except (TypeError, ValueError):
                pass
        return super().default(obj)

# Plotly 导入
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    print("警告: plotly 未安装，将使用简化版 HTML 报告")
    print("安装命令: pip install plotly")


class HTMLReportGenerator:
    """HTML 交互式报告生成器 - 支持多数据源"""

    # HTML 模板
    HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>回测报告 - {strategy_name}</title>
    {plotly_script_tag}
    {lwc_script_tag}
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{
            max-width: 1600px;
            margin: 0 auto;
        }}
        .header {{
            background: linear-gradient(135deg, #0f3460 0%, #533483 100%);
            border-radius: 16px;
            padding: 30px;
            margin-bottom: 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
        }}
        .header h1 {{
            font-size: 28px;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 15px;
        }}
        .header .logo {{
            font-size: 36px;
        }}
        .header .subtitle {{
            color: #a0a0a0;
            font-size: 14px;
        }}
        .header .brand {{
            float: right;
            text-align: right;
            color: #888;
            font-size: 12px;
        }}
        .header .brand a {{
            color: #64b5f6;
            text-decoration: none;
        }}

        /* 数据源切换标签 */
        .tabs {{
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }}
        .tab {{
            padding: 12px 24px;
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 14px;
        }}
        .tab:hover {{
            background: rgba(255,255,255,0.1);
        }}
        .tab.active {{
            background: linear-gradient(135deg, #0f3460 0%, #533483 100%);
            border-color: #64b5f6;
        }}
        .kline-tabs {{
            display: flex;
            gap: 8px;
            margin-bottom: 15px;
            flex-wrap: wrap;
        }}
        .kline-tabs .tab {{
            padding: 8px 16px;
            font-size: 12px;
        }}
        .tab-content {{
            display: none;
        }}
        .tab-content.active {{
            display: block;
        }}

        /* 综合绩效区域 */
        .summary-section {{
            background: rgba(255,255,255,0.03);
            border-radius: 16px;
            padding: 25px;
            margin-bottom: 20px;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        .summary-title {{
            font-size: 20px;
            margin-bottom: 20px;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 10px;
        }}

        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .metric-card {{
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 18px;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.1);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .metric-card:hover {{
            transform: translateY(-3px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.3);
        }}
        .metric-card .label {{
            font-size: 11px;
            color: #888;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .metric-card .value {{
            font-size: 22px;
            font-weight: 700;
        }}
        .metric-card .value.positive {{
            color: #4caf50;
        }}
        .metric-card .value.negative {{
            color: #f44336;
        }}
        .metric-card .value.neutral {{
            color: #64b5f6;
        }}
        .chart-container {{
            background: rgba(255,255,255,0.03);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 20px;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        .chart-title {{
            font-size: 18px;
            margin-bottom: 15px;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .chart-title .icon {{
            font-size: 24px;
        }}

        /* 数据源绩效对比表 */
        .comparison-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            margin-bottom: 20px;
        }}
        .comparison-table th {{
            background: rgba(255,255,255,0.1);
            padding: 12px 10px;
            text-align: right;
            font-weight: 600;
        }}
        .comparison-table th:first-child {{
            text-align: left;
        }}
        .comparison-table td {{
            padding: 10px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            text-align: right;
        }}
        .comparison-table td:first-child {{
            text-align: left;
            font-weight: 600;
            color: #64b5f6;
        }}
        .comparison-table tr:hover {{
            background: rgba(255,255,255,0.05);
        }}

        .trades-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}
        .trades-table th {{
            background: rgba(255,255,255,0.1);
            padding: 12px 8px;
            text-align: left;
            font-weight: 600;
            position: sticky;
            top: 0;
        }}
        .trades-table td {{
            padding: 10px 8px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }}
        .trades-table tr:hover {{
            background: rgba(255,255,255,0.05);
        }}
        .trades-table .profit {{
            color: #4caf50;
        }}
        .trades-table .loss {{
            color: #f44336;
        }}
        .table-wrapper {{
            border-radius: 8px;
        }}
        .table-wrapper::-webkit-scrollbar {{
            width: 8px;
        }}
        .table-wrapper::-webkit-scrollbar-track {{
            background: rgba(255,255,255,0.05);
        }}
        .table-wrapper::-webkit-scrollbar-thumb {{
            background: rgba(255,255,255,0.2);
            border-radius: 4px;
        }}

        /* 交易记录筛选器 */
        .trades-filter {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-bottom: 15px;
            padding: 15px;
            background: rgba(255,255,255,0.03);
            border-radius: 8px;
        }}
        .filter-group {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .filter-group label {{
            font-size: 12px;
            color: #aaa;
        }}
        .filter-group input, .filter-group select {{
            padding: 6px 10px;
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.15);
            border-radius: 4px;
            color: #fff;
            font-size: 12px;
        }}
        .filter-group input::placeholder {{
            color: #666;
        }}
        .filter-group select {{
            cursor: pointer;
        }}
        .filter-group select option {{
            background: #1a1a2e;
            color: #fff;
        }}
        .filter-btn {{
            padding: 6px 15px;
            background: linear-gradient(135deg, #0f3460 0%, #533483 100%);
            border: none;
            border-radius: 4px;
            color: #fff;
            font-size: 12px;
            cursor: pointer;
            transition: opacity 0.2s;
        }}
        .filter-btn:hover {{
            opacity: 0.8;
        }}
        .filter-btn.reset {{
            background: rgba(255,255,255,0.1);
        }}

        /* 分页器 */
        .pagination {{
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 8px;
            margin-top: 15px;
            flex-wrap: wrap;
        }}
        .pagination button {{
            padding: 8px 12px;
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.15);
            border-radius: 4px;
            color: #fff;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .pagination button:hover:not(:disabled) {{
            background: rgba(255,255,255,0.15);
        }}
        .pagination button:disabled {{
            opacity: 0.4;
            cursor: not-allowed;
        }}
        .pagination button.active {{
            background: linear-gradient(135deg, #0f3460 0%, #533483 100%);
            border-color: #64b5f6;
        }}
        .pagination .page-info {{
            font-size: 12px;
            color: #aaa;
            margin: 0 10px;
        }}
        .pagination .page-jump {{
            display: flex;
            align-items: center;
            gap: 5px;
        }}
        .pagination .page-jump input {{
            width: 50px;
            padding: 6px;
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.15);
            border-radius: 4px;
            color: #fff;
            font-size: 12px;
            text-align: center;
        }}
        .footer {{
            text-align: center;
            padding: 20px;
            color: #666;
            font-size: 12px;
        }}
        .footer a {{
            color: #64b5f6;
            text-decoration: none;
        }}
        .tag {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
        }}
        .tag.buy {{
            background: rgba(76, 175, 80, 0.2);
            color: #4caf50;
        }}
        .tag.sell {{
            background: rgba(244, 67, 54, 0.2);
            color: #f44336;
        }}
        .source-tag {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 10px;
            background: rgba(100, 181, 246, 0.2);
            color: #64b5f6;
            margin-right: 5px;
        }}

        /* 图例样式 */
        .legend {{
            display: flex;
            flex-wrap: wrap;
            gap: 15px;
            margin-bottom: 15px;
            padding: 10px;
            background: rgba(255,255,255,0.03);
            border-radius: 8px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
        }}
        .legend-color {{
            width: 20px;
            height: 3px;
            border-radius: 2px;
        }}

        @media (max-width: 768px) {{
            .metrics-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
            .header h1 {{
                font-size: 22px;
            }}
            .tabs {{
                flex-direction: column;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="brand">
                <div>🐿️ 松鼠QuantAi编写助手</div>
                <div><a href="https://ai.kanpan789.com" target="_blank">ai.kanpan789.com</a></div>
            </div>
            <h1>
                <span class="logo">📊</span>
                回测报告
            </h1>
            <div class="subtitle">
                {strategy_info} | 回测区间: {start_date} ~ {end_date} | 生成时间: {report_time}
            </div>
        </div>

        <!-- 综合绩效区域 -->
        <div class="summary-section">
            <div class="summary-title">
                <span>📈</span> 综合绩效摘要
            </div>
            <div class="metrics-grid">
                {combined_metrics_cards}
            </div>
            <div style="margin-top: 15px; padding: 10px 15px; background: rgba(76, 175, 80, 0.1); border-radius: 8px; font-size: 12px; color: #aaa; border-left: 3px solid #4caf50;">
                💡 <strong>说明：</strong>以上所有绩效指标均已扣除<span style="color: #81c784;">手续费</span>和<span style="color: #81c784;">滑点成本</span>（按配置的滑点跳数×最小变动价位计算）
            </div>
        </div>

        <!-- 数据源对比表 -->
        {source_comparison_section}

        <!-- 利润曲线图（从0开始，便于对比各数据源盈亏） -->
        <div class="chart-container">
            <div class="chart-title">
                <span class="icon">📈</span>
                利润曲线对比（盈亏走势）
                <span style="font-size: 12px; color: #888; margin-left: 10px;">点击图例可显示/隐藏曲线</span>
            </div>
            <div id="profit-chart"></div>
        </div>

        <!-- 综合回撤图 -->
        <div class="chart-container">
            <div class="chart-title">
                <span class="icon">📉</span>
                回撤分析
            </div>
            <div id="drawdown-chart"></div>
        </div>

        <!-- K线信号综合图（matplotlib 静态图，可导出） -->
        {signal_charts}

        <!-- K线图/TICK价格图与交易标记 -->
        <div class="chart-container">
            <div class="chart-title">
                <span class="icon" id="price-chart-icon">🕯️</span>
                <span id="price-chart-title">K线图与交易标记</span>
            </div>
            <div class="kline-tabs" id="kline-tabs"></div>
            <!-- 图表工具栏 -->
            <div style="display: flex; gap: 8px; margin: 8px 0; align-items: center;">
                <button onclick="resetChartView()" style="background: rgba(100,181,246,0.15); border: 1px solid rgba(100,181,246,0.3); color: #64b5f6; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; display: flex; align-items: center; gap: 4px;">
                    <span>📐</span> 自适应全部
                </button>
                <button onclick="scrollToStart()" style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: #ccc; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; display: flex; align-items: center; gap: 4px;">
                    <span>⏮</span> 最早
                </button>
                <button onclick="scrollToEnd()" style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: #ccc; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; display: flex; align-items: center; gap: 4px;">
                    <span>⏭</span> 最新
                </button>
                <button onclick="zoomIn()" style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: #ccc; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; display: flex; align-items: center; gap: 4px;">
                    <span>🔍+</span> 放大
                </button>
                <button onclick="zoomOut()" style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: #ccc; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; display: flex; align-items: center; gap: 4px;">
                    <span>🔍-</span> 缩小
                </button>
                <button onclick="openChartModal()" style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: #ccc; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; display: flex; align-items: center; gap: 4px;">
                    <span>⛶</span> 弹出
                </button>
                <button id="panorama-btn" onclick="openPanoramaModal()" style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: #ccc; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px; display: none; align-items: center; gap: 4px;">
                    <span>🖼️</span> 全景图
                </button>
                <span id="kline-range-info" style="color: #888; font-size: 11px; margin-left: auto;"></span>
            </div>
            <div id="kline-chart" style="height: 420px; position: relative;"></div>
            <!-- 导航器滑动窗口 -->
            <div id="kline-navigator-container" style="height: 80px; position: relative; margin-top: 2px; background: rgba(26,26,46,1); border-top: 1px solid rgba(255,255,255,0.05);">
                <div id="kline-navigator" style="height: 100%; width: 100%;"></div>
                <div id="kline-navigator-overlay" style="position: absolute; top: 0; height: 100%; background: rgba(100,181,246,0.12); border-left: 2px solid rgba(100,181,246,0.6); border-right: 2px solid rgba(100,181,246,0.6); cursor: grab; z-index: 10; box-sizing: border-box;"></div>
            </div>
            <div id="lwc-tooltip" style="position: fixed; display: none; background: rgba(30,30,45,0.95); border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; padding: 10px 14px; color: #e0e0e0; font-size: 12px; line-height: 1.6; pointer-events: none; z-index: 1000; box-shadow: 0 4px 12px rgba(0,0,0,0.4); max-width: 280px;"></div>
        </div>

        <!-- 全屏弹窗：K线大图模式 -->
        <div id="chart-modal" style="display: none; position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; background: rgba(18, 18, 30, 0.98); z-index: 2000; flex-direction: column;">
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 12px 20px; border-bottom: 1px solid rgba(255,255,255,0.1);">
                <span id="chart-modal-title" style="color: #e0e0e0; font-size: 16px; font-weight: 500;">K线图与交易标记</span>
                <button onclick="closeChartModal()" style="background: transparent; border: 1px solid rgba(255,255,255,0.15); color: #888; width: 32px; height: 32px; border-radius: 4px; font-size: 20px; cursor: pointer; display: flex; align-items: center; justify-content: center;">×</button>
            </div>
            <div style="flex: 1; display: flex; flex-direction: column; padding: 10px 20px 20px; overflow: hidden;">
                <div id="chart-modal-main" style="flex: 1; min-height: 0;"></div>
                <div id="chart-modal-nav-container" style="height: 80px; position: relative; margin-top: 2px; background: rgba(26,26,46,1); border-top: 1px solid rgba(255,255,255,0.05);">
                    <div id="chart-modal-nav" style="height: 100%; width: 100%;"></div>
                    <div id="chart-modal-nav-overlay" style="position: absolute; top: 0; height: 100%; background: rgba(100,181,246,0.12); border-left: 2px solid rgba(100,181,246,0.6); border-right: 2px solid rgba(100,181,246,0.6); cursor: grab; z-index: 10; box-sizing: border-box;"></div>
                </div>
            </div>
        </div>

        <!-- 各数据源详情标签页 -->
        {source_tabs}

        <!-- 各数据源详情内容 -->
        {source_details}

        <div class="footer">
            <p>由 <a href="https://gitee.com/ssquant/ssquant" target="_blank">松鼠Quant-ssquant框架</a> 生成</p>
            <p>⚠️ 历史回测不代表未来表现，投资有风险，入市需谨慎</p>
        </div>
    </div>

    <script>
        // 图表颜色
        var colors = ['#64b5f6', '#4caf50', '#ff9800', '#e91e63', '#9c27b0', '#00bcd4', '#8bc34a', '#ff5722'];

        // 利润曲线数据（从0开始，便于对比）
        var profitDataSources = {profit_data_sources};
        var combinedProfitData = {combined_profit_data};
        var combinedGrossProfitData = {combined_gross_profit_data};
        var priceDataSources = {price_data_sources};

        // 绘制利润曲线
        var profitTraces = [];

        // 添加各数据源的利润曲线
        profitDataSources.forEach(function(source, idx) {{
            var color = colors[idx % colors.length];
            profitTraces.push({{
                x: source.dates,
                y: source.values,
                type: 'scatter',
                mode: 'lines',
                name: source.name,
                line: {{
                    color: color,
                    width: 1.5
                }},
                opacity: 0.7
            }});
        }});

        // 添加综合交易盈亏曲线（未扣手续费，黄色虚线）
        if (combinedGrossProfitData.dates && combinedGrossProfitData.dates.length > 0) {{
            profitTraces.push({{
                x: combinedGrossProfitData.dates,
                y: combinedGrossProfitData.values,
                type: 'scatter',
                mode: 'lines',
                name: '交易盈亏(未扣手续费)',
                line: {{
                    color: '#ffd54f',
                    width: 2,
                    dash: 'dash'
                }},
                opacity: 0.8
            }});
        }}

        // 添加综合净利润曲线（扣除手续费，白色实线）
        if (combinedProfitData.dates && combinedProfitData.dates.length > 0) {{
            profitTraces.push({{
                x: combinedProfitData.dates,
                y: combinedProfitData.values,
                type: 'scatter',
                mode: 'lines',
                name: '净利润(扣除手续费)',
                line: {{
                    color: '#ffffff',
                    width: 2.5
                }}
            }});
        }}

        // 添加价格曲线（使用右侧Y轴，默认隐藏）
        var priceColors = ['#90caf9', '#a5d6a7', '#ffcc80', '#f48fb1', '#ce93d8'];
        priceDataSources.forEach(function(source, idx) {{
            var color = priceColors[idx % priceColors.length];
            profitTraces.push({{
                x: source.dates,
                y: source.values,
                type: 'scatter',
                mode: 'lines',
                name: source.name,
                yaxis: 'y2',
                line: {{
                    color: color,
                    width: 1,
                    dash: 'dot'
                }},
                opacity: 0.6,
                visible: 'legendonly'  // 默认隐藏，点击图例可显示
            }});
        }});

        // 使用最长数据源的时间作为统一的 X 轴类别
        var allDates = [];
        profitDataSources.forEach(function(source) {{
            source.dates.forEach(function(d) {{
                if (allDates.indexOf(d) === -1) allDates.push(d);
            }});
        }});
        allDates.sort();

        var profitLayout = {{
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor: 'rgba(0,0,0,0)',
            font: {{ color: '#e0e0e0' }},
            xaxis: {{
                type: 'category',
                categoryorder: 'array',
                categoryarray: allDates,
                gridcolor: 'rgba(255,255,255,0.1)',
                nticks: 10,
                tickangle: -30
            }},
            yaxis: {{
                gridcolor: 'rgba(255,255,255,0.1)',
                tickformat: ',.0f',
                title: '利润(元)',
                zeroline: true,
                zerolinecolor: 'rgba(255,255,255,0.3)',
                zerolinewidth: 1,
                side: 'left'
            }},
            yaxis2: {{
                gridcolor: 'rgba(255,255,255,0.05)',
                tickformat: ',.2f',
                title: '价格/相对值',
                overlaying: 'y',
                side: 'right',
                showgrid: false
            }},
            margin: {{ l: 70, r: 70, t: 30, b: 60 }},
            hovermode: 'x unified',
            hoverlabel: {{
                bgcolor: '#fff',
                font: {{ color: '#333', size: 13 }},
                bordercolor: '#ccc'
            }},
            showlegend: true,
            legend: {{
                orientation: 'h',
                yanchor: 'bottom',
                y: 1.02,
                xanchor: 'left',
                x: 0,
                font: {{ size: 11 }}
            }},
            dragmode: 'pan'
        }};

        var profitConfig = {{
            scrollZoom: true,
            displayModeBar: true,
            modeBarButtonsToRemove: ['select2d', 'lasso2d'],
            displaylogo: false
        }};

        Plotly.newPlot('profit-chart', profitTraces, profitLayout, profitConfig);

        // 回撤数据
        var drawdownDataSources = {drawdown_data_sources};
        var combinedDrawdownData = {combined_drawdown_data};

        // 绘制回撤图
        var drawdownTraces = [];

        // 添加各数据源的回撤曲线
        drawdownDataSources.forEach(function(source, idx) {{
            var color = colors[idx % colors.length];
            drawdownTraces.push({{
                x: source.dates,
                y: source.values,
                type: 'scatter',
                mode: 'lines',
                name: source.name,
                line: {{
                    color: color,
                    width: 1
                }},
                opacity: 0.5
            }});
        }});

        // 添加综合回撤曲线
        if (combinedDrawdownData.dates && combinedDrawdownData.dates.length > 0) {{
            drawdownTraces.push({{
                x: combinedDrawdownData.dates,
                y: combinedDrawdownData.values,
                type: 'scatter',
                mode: 'lines',
                name: '综合回撤',
                fill: 'tozeroy',
                fillcolor: 'rgba(244, 67, 54, 0.3)',
                line: {{
                    color: '#f44336',
                    width: 2
                }}
            }});
        }}

        // 使用最长数据源的时间作为统一的 X 轴类别
        var allDrawdownDates = [];
        drawdownDataSources.forEach(function(source) {{
            source.dates.forEach(function(d) {{
                if (allDrawdownDates.indexOf(d) === -1) allDrawdownDates.push(d);
            }});
        }});
        allDrawdownDates.sort();

        var drawdownLayout = {{
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor: 'rgba(0,0,0,0)',
            font: {{ color: '#e0e0e0' }},
            xaxis: {{
                type: 'category',
                categoryorder: 'array',
                categoryarray: allDrawdownDates,
                gridcolor: 'rgba(255,255,255,0.1)',
                nticks: 10,
                tickangle: -30
            }},
            yaxis: {{
                gridcolor: 'rgba(255,255,255,0.1)',
                tickformat: '.2f',
                title: '回撤 (%)',
                autorange: 'reversed'
            }},
            margin: {{ l: 70, r: 30, t: 30, b: 60 }},
            hovermode: 'x unified',
            hoverlabel: {{
                bgcolor: '#fff',
                font: {{ color: '#333', size: 13 }},
                bordercolor: '#ccc'
            }},
            showlegend: false,
            dragmode: 'pan'
        }};

        var drawdownConfig = {{
            scrollZoom: true,
            displayModeBar: true,
            modeBarButtonsToRemove: ['select2d', 'lasso2d'],
            displaylogo: false
        }};

        Plotly.newPlot('drawdown-chart', drawdownTraces, drawdownLayout, drawdownConfig);

        // 标签页切换功能
        function switchTab(tabId) {{
            // 隐藏所有标签内容
            document.querySelectorAll('.tab-content').forEach(function(content) {{
                content.classList.remove('active');
            }});
            // 取消所有标签的激活状态
            document.querySelectorAll('.tab').forEach(function(tab) {{
                tab.classList.remove('active');
            }});
            // 显示选中的标签内容
            var content = document.getElementById('content-' + tabId);
            if (content) {{
                content.classList.add('active');
            }}
            // 激活选中的标签
            var tab = document.querySelector('[onclick="switchTab(\\'' + tabId + '\\')"]');
            if (tab) {{
                tab.classList.add('active');
            }}
        }}

        // K线图数据
        var klineDataSources = {kline_data_sources};
        var currentKlineIndex = 0;

        // 生成 K线切换标签
        function generateKlineTabs() {{
            var tabsHtml = '';
            klineDataSources.forEach(function(source, idx) {{
                var activeClass = idx === 0 ? 'active' : '';
                tabsHtml += '<div class="tab ' + activeClass + '" onclick="switchKline(' + idx + ')">' + source.name + '</div>';
            }});
            document.getElementById('kline-tabs').innerHTML = tabsHtml;
        }}

        // 切换 K线数据源
        function switchKline(idx) {{
            currentKlineIndex = idx;
            // 更新标签状态
            var tabs = document.querySelectorAll('#kline-tabs .tab');
            tabs.forEach(function(tab, i) {{
                if (i === idx) {{
                    tab.classList.add('active');
                }} else {{
                    tab.classList.remove('active');
                }}
            }});
            // 更新图表标题
            updateChartTitle(idx);
            // 重新绘制图表
            drawKlineChart(idx);
        }}

        // Lightweight Charts™ 图表实例与 resize 句柄
        var _lwcChart = null;
        var _lwcResizeHandler = null;
        var _lwcCrosshairSub = null;
        // 导航器相关
        var _lwcNavChart = null;
        var _lwcNavSeries = null;
        var _lwcNavRangeSub = null;
        var _lwcNavDragging = false;
        var _lwcNavDragStartX = 0;
        var _lwcNavDragStartLeft = 0;
        var _lwcNavDragStartWidth = 0;
        var _lwcNavMouseMoveHandler = null;
        var _lwcNavMouseUpHandler = null;
        // 弹窗大图相关
        var _modalChart = null;
        var _modalNavChart = null;
        var _modalResizeHandler = null;
        var _modalRangeSub = null;
        var _modalTooltipEl = null;
        var _modalMouseMoveHandler = null;
        var _modalMouseUpHandler = null;

        // 格式化 LWC 时间字符串（时间戳已做 +8h 偏移，使用 UTC 方法显示）
        function _fmtLwcTime(ts) {{
            if (!ts) return '';
            var d = new Date(ts * 1000);
            var pad = function(n) {{ return n < 10 ? '0' + n : n; }};
            // 使用 UTC 方法：时间戳已含 +8h 偏移，UTC 显示即北京时间
            return d.getUTCFullYear() + '-' + pad(d.getUTCMonth()+1) + '-' + pad(d.getUTCDate()) +
                   ' ' + pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes());
        }}

        // 更新图表标题（根据是TICK还是K线）
        function updateChartTitle(idx) {{
            if (klineDataSources.length === 0) return;
            var source = klineDataSources[idx];
            var isTick = source.is_tick;
            var iconEl = document.getElementById('price-chart-icon');
            var titleEl = document.getElementById('price-chart-title');
            if (iconEl && titleEl) {{
                if (isTick) {{
                    iconEl.textContent = '📈';
                    titleEl.textContent = 'TICK价格图与交易标记';
                }} else {{
                    iconEl.textContent = '🕯️';
                    titleEl.textContent = 'K线图与交易标记';
                }}
            }}
        }}

        // 绘制 K线图 / TICK价格线图（Lightweight Charts™）
        function drawKlineChart(idx) {{
            if (klineDataSources.length === 0) return;

            var container = document.getElementById('kline-chart');
            if (!container) return;

            // 销毁旧图表与 crosshair 订阅
            if (_lwcCrosshairSub) {{
                try {{ _lwcCrosshairSub(); }} catch(e) {{}}
                _lwcCrosshairSub = null;
            }}
            if (_lwcChart) {{
                _lwcChart.remove();
                _lwcChart = null;
            }}
            container.innerHTML = '';

            // 销毁旧导航器
            if (_lwcNavRangeSub) {{
                try {{ _lwcNavRangeSub(); }} catch(e) {{}}
                _lwcNavRangeSub = null;
            }}
            if (_lwcNavChart) {{
                _lwcNavChart.remove();
                _lwcNavChart = null;
            }}
            var navContainer = document.getElementById('kline-navigator');
            if (navContainer) navContainer.innerHTML = '';

            // tooltip 元素
            var tooltipEl = document.getElementById('lwc-tooltip');

            var source = klineDataSources[idx];

            var chart = LightweightCharts.createChart(container, {{
                width: container.clientWidth || 800,
                height: 500,
                layout: {{
                    background: {{ type: 'solid', color: 'rgba(26, 26, 46, 1)' }},
                    textColor: '#e0e0e0',
                }},
                grid: {{
                    vertLines: {{ color: 'rgba(255, 255, 255, 0.1)' }},
                    horzLines: {{ color: 'rgba(255, 255, 255, 0.1)' }},
                }},
                crosshair: {{
                    mode: LightweightCharts.CrosshairMode.Normal,
                }},
                rightPriceScale: {{
                    borderColor: 'rgba(255, 255, 255, 0.1)',
                }},
                timeScale: {{
                    borderColor: 'rgba(255, 255, 255, 0.1)',
                    timeVisible: true,
                    secondsVisible: false,
                    barSpacing: 1,
                    rightOffset: 2,
                }},
                handleScroll: {{ vertTouchDrag: false }},
            }});

            _lwcChart = chart;

            var series;
            try {{
                if (source.is_tick) {{
                    series = chart.addLineSeries({{
                        color: '#64b5f6',
                        lineWidth: 1.5,
                        title: source.name + ' 价格',
                    }});
                    console.log('LWC Line data count:', source.data ? source.data.length : 0);
                    if (source.data && source.data.length > 0) {{
                        console.log('LWC First data point:', source.data[0]);
                        series.setData(source.data);
                    }}
                }} else {{
                    series = chart.addCandlestickSeries({{
                        upColor: '#26a69a', downColor: '#ef5350',
                        borderUpColor: '#26a69a', borderDownColor: '#ef5350',
                        wickUpColor: '#26a69a', wickDownColor: '#ef5350',
                    }});
                    console.log('LWC Candle data count:', source.data ? source.data.length : 0);
                    if (source.data && source.data.length > 0) {{
                        console.log('LWC First data point:', source.data[0]);
                        series.setData(source.data);
                    }}
                }}

                if (source.markers && source.markers.length > 0) {{
                    console.log('LWC Markers count:', source.markers.length);
                    console.log('LWC First marker:', source.markers[0]);
                    series.setMarkers(source.markers);
                }} else {{
                    console.log('LWC No markers for', source.name);
                }}
            }} catch (e) {{
                console.error('LWC Error:', e);
            }}

            // 延迟 fitContent，确保容器尺寸已稳定（避免初始宽度为 0 或不正确导致范围计算错误）
            setTimeout(function() {{
                chart.timeScale().fitContent();
            }}, 100);

            // 更新数据范围信息
            updateKlineRangeInfo(source);

            // ===== 导航器（时间轴滑动窗口）=====
            (function setupNavigator() {{
                var navContainer = document.getElementById('kline-navigator');
                var navOverlay = document.getElementById('kline-navigator-overlay');
                if (!navContainer || !navOverlay || !source.data || source.data.length === 0) return;

                navContainer.innerHTML = '';

                var navChart = LightweightCharts.createChart(navContainer, {{
                    width: navContainer.clientWidth || 800,
                    height: 80,
                    layout: {{
                        background: {{ type: 'solid', color: 'rgba(26, 26, 46, 1)' }},
                        textColor: '#888888',
                    }},
                    grid: {{
                        vertLines: {{ color: 'transparent' }},
                        horzLines: {{ color: 'transparent' }},
                    }},
                    crosshair: {{
                        mode: LightweightCharts.CrosshairMode.Normal,
                        vertLine: {{ visible: false, labelVisible: false }},
                        horzLine: {{ visible: false, labelVisible: false }},
                    }},
                    rightPriceScale: {{
                        visible: false,
                        borderVisible: false,
                    }},
                    leftPriceScale: {{
                        visible: false,
                        borderVisible: false,
                    }},
                    timeScale: {{
                        visible: true,
                        borderVisible: true,
                        borderColor: 'rgba(255, 255, 255, 0.1)',
                        timeVisible: true,
                        secondsVisible: false,
                    }},
                    handleScroll: false,
                    handleScale: false,
                }});

                _lwcNavChart = navChart;

                // 导航器用 area series 显示收盘价走势
                var navData = source.data.map(function(d) {{
                    return {{ time: d.time, value: d.close !== undefined ? d.close : d.value }};
                }});
                var navSeries = navChart.addAreaSeries({{
                    lineColor: 'rgba(100, 181, 246, 0.5)',
                    topColor: 'rgba(100, 181, 246, 0.2)',
                    bottomColor: 'rgba(100, 181, 246, 0.0)',
                    lineWidth: 1,
                    lastValueVisible: false,
                    priceLineVisible: false,
                }});
                navSeries.setData(navData);
                _lwcNavSeries = navSeries;

                navChart.timeScale().fitContent();

                // 更新 overlay 位置和大小
                function updateOverlay() {{
                    if (!_lwcChart || !_lwcNavChart) return;
                    var logicalRange = _lwcChart.timeScale().getVisibleLogicalRange();
                    if (!logicalRange) return;
                    var total = source.data.length;
                    if (total <= 1) return;
                    var fromPct = Math.max(0, Math.min(1, logicalRange.from / (total - 1)));
                    var toPct = Math.max(0, Math.min(1, logicalRange.to / (total - 1)));
                    var leftPct = fromPct * 100;
                    var widthPct = (toPct - fromPct) * 100;
                    navOverlay.style.left = leftPct + '%';
                    navOverlay.style.width = widthPct + '%';
                    navOverlay.style.display = widthPct > 0.5 ? 'block' : 'none';
                }}

                // 监听主图可见范围变化
                _lwcNavRangeSub = chart.timeScale().subscribeVisibleLogicalRangeChange(function() {{
                    requestAnimationFrame(updateOverlay);
                }});

                // 初始更新
                setTimeout(updateOverlay, 150);

                // overlay 拖拽逻辑
                navOverlay.addEventListener('mousedown', function(e) {{
                    _lwcNavDragging = true;
                    _lwcNavDragStartX = e.clientX;
                    _lwcNavDragStartLeft = parseFloat(navOverlay.style.left) || 0;
                    _lwcNavDragStartWidth = parseFloat(navOverlay.style.width) || 10;
                    navOverlay.style.cursor = 'grabbing';
                    e.preventDefault();
                }});

                if (_lwcNavMouseMoveHandler) {{
                    window.removeEventListener('mousemove', _lwcNavMouseMoveHandler);
                }}
                if (_lwcNavMouseUpHandler) {{
                    window.removeEventListener('mouseup', _lwcNavMouseUpHandler);
                }}

                _lwcNavMouseMoveHandler = function(e) {{
                    if (!_lwcNavDragging || !_lwcChart || !source.data || source.data.length === 0) return;
                    var navRect = navContainer.getBoundingClientRect();
                    var deltaPx = e.clientX - _lwcNavDragStartX;
                    var deltaPct = (deltaPx / navRect.width) * 100;
                    var newLeft = _lwcNavDragStartLeft + deltaPct;
                    var width = _lwcNavDragStartWidth;
                    // 边界限制
                    if (newLeft < 0) newLeft = 0;
                    if (newLeft + width > 100) newLeft = 100 - width;
                    navOverlay.style.left = newLeft + '%';

                    // 同步到主图
                    var total = source.data.length;
                    var fromIdx = Math.round((newLeft / 100) * (total - 1));
                    var toIdx = Math.round(((newLeft + width) / 100) * (total - 1));
                    _lwcChart.timeScale().setVisibleLogicalRange({{ from: fromIdx, to: toIdx }});
                }};

                _lwcNavMouseUpHandler = function() {{
                    if (_lwcNavDragging) {{
                        _lwcNavDragging = false;
                        navOverlay.style.cursor = 'grab';
                    }}
                }};

                window.addEventListener('mousemove', _lwcNavMouseMoveHandler);
                window.addEventListener('mouseup', _lwcNavMouseUpHandler);
            }})();

            // ===== 自定义 tooltip：K线信息 + 交易标记信息 =====
            if (tooltipEl) {{
                // 建立时间 -> K线数据 和 marker 的映射（不依赖 param.seriesData）
                var klineMap = {{}};
                if (source.data && source.data.length > 0) {{
                    source.data.forEach(function(d) {{
                        var t = typeof d.time === 'number' ? Math.floor(d.time) : d.time;
                        klineMap[t] = d;
                    }});
                }}
                var markerMap = {{}};
                if (source.markers && source.markers.length > 0) {{
                    source.markers.forEach(function(m) {{
                        markerMap[m.time] = m;
                    }});
                }}

                _lwcCrosshairSub = chart.subscribeCrosshairMove(function(param) {{
                    try {{
                        if (!param.point || param.time === undefined || param.time === null) {{
                            tooltipEl.style.display = 'none';
                            return;
                        }}

                        var html = '';
                        var ts = param.time;
                        // 统一转为整数秒时间戳
                        if (typeof ts === 'object' && ts.year !== undefined) {{
                            ts = Math.floor(new Date(ts.year, ts.month - 1, ts.day).getTime() / 1000);
                        }} else if (typeof ts === 'number') {{
                            ts = Math.floor(ts);
                        }} else if (typeof ts === 'string') {{
                            ts = Math.floor(new Date(ts).getTime() / 1000);
                        }}

                        // K线 / 价格信息（直接从 klineMap 查，不依赖 param.seriesData）
                        var dataPoint = klineMap[ts];
                        if (dataPoint) {{
                            if (!source.is_tick && dataPoint.open !== undefined) {{
                                html += '<div style="font-weight:bold;margin-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.15);padding-bottom:4px;">' + _fmtLwcTime(ts) + '</div>';
                                html += '<div>开: <span style="color:#e0e0e0">' + Number(dataPoint.open).toFixed(2) + '</span></div>';
                                html += '<div>高: <span style="color:#26a69a">' + Number(dataPoint.high).toFixed(2) + '</span></div>';
                                html += '<div>低: <span style="color:#ef5350">' + Number(dataPoint.low).toFixed(2) + '</span></div>';
                                html += '<div>收: <span style="color:#e0e0e0">' + Number(dataPoint.close).toFixed(2) + '</span></div>';
                            }} else if (source.is_tick && dataPoint.value !== undefined) {{
                                html += '<div style="font-weight:bold;margin-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.15);padding-bottom:4px;">' + _fmtLwcTime(ts) + '</div>';
                                html += '<div>价格: <span style="color:#64b5f6">' + Number(dataPoint.value).toFixed(2) + '</span></div>';
                            }}
                        }}

                        // 交易标记信息
                        var marker = markerMap[ts];
                        if (marker && marker.tooltip) {{
                            var mcolor = marker.color || '#e0e0e0';
                            html += '<div style="margin-top:6px;border-top:1px solid rgba(255,255,255,0.15);padding-top:4px;">';
                            html += '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + mcolor + ';margin-right:6px;"></span>';
                            html += '<span style="color:' + mcolor + ';font-weight:bold;">' + marker.tooltip + '</span>';
                            html += '</div>';
                        }}

                        if (html) {{
                            tooltipEl.innerHTML = html;
                            tooltipEl.style.display = 'block';
                            var rect = container.getBoundingClientRect();
                            var left = rect.left + param.point.x + 16;
                            var top = rect.top + param.point.y + 16;
                            if (left + 260 > window.innerWidth) left = rect.left + param.point.x - 260;
                            if (top + 140 > window.innerHeight) top = rect.top + param.point.y - 140;
                            if (left < 10) left = 10;
                            if (top < 10) top = 10;
                            tooltipEl.style.left = left + 'px';
                            tooltipEl.style.top = top + 'px';
                        }} else {{
                            tooltipEl.style.display = 'none';
                        }}
                    }} catch (err) {{
                        console.error('LWC tooltip error:', err);
                        tooltipEl.style.display = 'none';
                    }}
                }});
            }}

            // 响应窗口大小变化
            if (_lwcResizeHandler) {{
                window.removeEventListener('resize', _lwcResizeHandler);
            }}
            _lwcResizeHandler = function() {{
                if (_lwcChart && container) {{
                    _lwcChart.applyOptions({{ width: container.clientWidth }});
                    // 窗口大小变化后重新调整时间轴范围，确保全部数据可见
                    _lwcChart.timeScale().fitContent();
                }}
                var navContainer = document.getElementById('kline-navigator');
                if (_lwcNavChart && navContainer) {{
                    _lwcNavChart.applyOptions({{ width: navContainer.clientWidth }});
                    _lwcNavChart.timeScale().fitContent();
                }}
            }};
            window.addEventListener('resize', _lwcResizeHandler);
        }}

        // 重置视图：显示全部数据和信号
        function resetChartView() {{
            if (_lwcChart) {{
                _lwcChart.timeScale().fitContent();
                // 同时重置价格轴的缩放（如果有）
                _lwcChart.priceScale().applyOptions({{ autoScale: true }});
            }}
        }}

        // 跳转到数据最左侧（最早的数据），保持当前缩放级别
        function scrollToStart() {{
            if (_lwcChart) {{
                var logicalRange = _lwcChart.timeScale().getVisibleLogicalRange();
                if (logicalRange) {{
                    var visibleBars = logicalRange.to - logicalRange.from;
                    _lwcChart.timeScale().setVisibleLogicalRange({{ from: 0, to: visibleBars }});
                }}
            }}
        }}

        // 跳转到数据最右侧（最新的数据）
        function scrollToEnd() {{
            if (_lwcChart) {{
                _lwcChart.timeScale().scrollToRealTime();
            }}
        }}

        // 放大：减少可见 bar 数量（绕开滚轮上限）
        function zoomIn() {{
            if (!_lwcChart) return;
            var range = _lwcChart.timeScale().getVisibleLogicalRange();
            if (!range) return;
            var center = (range.from + range.to) / 2;
            var half = (range.to - range.from) / 4;
            _lwcChart.timeScale().setVisibleLogicalRange({{ from: center - half, to: center + half }});
        }}

        // 缩小：增加可见 bar 数量
        function zoomOut() {{
            if (!_lwcChart) return;
            var range = _lwcChart.timeScale().getVisibleLogicalRange();
            if (!range) return;
            var center = (range.from + range.to) / 2;
            var span = (range.to - range.from);
            _lwcChart.timeScale().setVisibleLogicalRange({{ from: center - span, to: center + span }});
        }}

        // ===== 全屏弹窗：大图模式 =====
        function openChartModal() {{
            if (klineDataSources.length === 0 || currentKlineIndex >= klineDataSources.length) return;
            var source = klineDataSources[currentKlineIndex];

            var modal = document.getElementById('chart-modal');
            var mainContainer = document.getElementById('chart-modal-main');
            var navContainerEl = document.getElementById('chart-modal-nav');
            var navOverlay = document.getElementById('chart-modal-nav-overlay');
            if (!modal || !mainContainer || !navContainerEl || !navOverlay) return;

            // 标题
            var titleEl = document.getElementById('chart-modal-title');
            if (titleEl) titleEl.textContent = (source.is_tick ? 'TICK价格图' : 'K线图') + ' - ' + source.name;

            modal.style.display = 'flex';
            document.body.style.overflow = 'hidden';

            // 清理旧实例
            closeChartModalCleanup();

            // 延迟创建图表：等 flex 布局完成后再获取容器尺寸
            // 双重 requestAnimationFrame 确保浏览器已完成重排
            requestAnimationFrame(function() {{
                requestAnimationFrame(function() {{
                    // 重新获取 overlay（closeChartModalCleanup 可能已替换它）
                    var freshNavOverlay = document.getElementById('chart-modal-nav-overlay');
                    openChartModalRender(source, mainContainer, navContainerEl, freshNavOverlay);
                }});
            }});
        }}

        function openChartModalRender(source, mainContainer, navContainerEl, navOverlay) {{
            // 始终重新获取 overlay，避免引用被替换的旧元素
            navOverlay = document.getElementById('chart-modal-nav-overlay') || navOverlay;
            if (!source || !mainContainer || !navContainerEl || !navOverlay) return;

            // 保险：如果容器尺寸仍为 0，再次延迟
            if (mainContainer.clientWidth === 0 || mainContainer.clientHeight === 0) {{
                console.warn('弹窗容器尺寸为0，再次延迟渲染');
                setTimeout(function() {{
                    openChartModalRender(source, mainContainer, navContainerEl, navOverlay);
                }}, 100);
                return;
            }}

            // 创建 tooltip
            if (!_modalTooltipEl) {{
                _modalTooltipEl = document.createElement('div');
                _modalTooltipEl.style.cssText = 'position:fixed;display:none;background:rgba(30,30,45,0.95);border:1px solid rgba(255,255,255,0.15);border-radius:6px;padding:10px 14px;color:#e0e0e0;font-size:12px;line-height:1.6;pointer-events:none;z-index:3000;box-shadow:0 4px 12px rgba(0,0,0,0.4);max-width:280px;';
                document.body.appendChild(_modalTooltipEl);
            }}

            // === 主图 ===
            var chart = LightweightCharts.createChart(mainContainer, {{
                width: mainContainer.clientWidth,
                height: mainContainer.clientHeight,
                layout: {{ background: {{ type: 'solid', color: 'rgba(26, 26, 46, 1)' }}, textColor: '#e0e0e0' }},
                grid: {{ vertLines: {{ color: 'rgba(255, 255, 255, 0.1)' }}, horzLines: {{ color: 'rgba(255, 255, 255, 0.1)' }} }},
                crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
                rightPriceScale: {{ borderColor: 'rgba(255, 255, 255, 0.1)' }},
                timeScale: {{ borderColor: 'rgba(255, 255, 255, 0.1)', timeVisible: true, secondsVisible: false, barSpacing: 1, rightOffset: 2 }},
                handleScroll: {{ vertTouchDrag: false }},
            }});
            _modalChart = chart;

            var series;
            if (source.is_tick) {{
                series = chart.addLineSeries({{ color: '#64b5f6', lineWidth: 1.5, title: source.name + ' 价格' }});
                if (source.data && source.data.length > 0) series.setData(source.data);
            }} else {{
                series = chart.addCandlestickSeries({{
                    upColor: '#26a69a', downColor: '#ef5350',
                    borderUpColor: '#26a69a', borderDownColor: '#ef5350',
                    wickUpColor: '#26a69a', wickDownColor: '#ef5350',
                }});
                if (source.data && source.data.length > 0) series.setData(source.data);
            }}
            if (source.markers && source.markers.length > 0) series.setMarkers(source.markers);

            // === 导航器 ===
            navContainerEl.innerHTML = '';
            var navChart = LightweightCharts.createChart(navContainerEl, {{
                width: navContainerEl.clientWidth || 800,
                height: 80,
                layout: {{ background: {{ type: 'solid', color: 'rgba(26, 26, 46, 1)' }}, textColor: '#888888' }},
                grid: {{ vertLines: {{ color: 'transparent' }}, horzLines: {{ color: 'transparent' }} }},
                crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal, vertLine: {{ visible: false, labelVisible: false }}, horzLine: {{ visible: false, labelVisible: false }} }},
                rightPriceScale: {{ visible: false, borderVisible: false }},
                leftPriceScale: {{ visible: false, borderVisible: false }},
                timeScale: {{ visible: true, borderVisible: true, borderColor: 'rgba(255, 255, 255, 0.1)', timeVisible: true, secondsVisible: false }},
                handleScroll: false,
                handleScale: false,
            }});
            _modalNavChart = navChart;

            var navData = source.data.map(function(d) {{ return {{ time: d.time, value: d.close !== undefined ? d.close : d.value }}; }});
            var navSeries = navChart.addAreaSeries({{
                lineColor: 'rgba(100, 181, 246, 0.5)', topColor: 'rgba(100, 181, 246, 0.2)',
                bottomColor: 'rgba(100, 181, 246, 0.0)', lineWidth: 1,
                lastValueVisible: false, priceLineVisible: false,
            }});
            navSeries.setData(navData);
            navChart.timeScale().fitContent();

            // overlay 同步
            function updateModalOverlay() {{
                if (!_modalChart || !_modalNavChart || !source.data) return;
                var logicalRange = _modalChart.timeScale().getVisibleLogicalRange();
                if (!logicalRange) return;
                var total = source.data.length;
                if (total <= 1) return;
                var fromPct = Math.max(0, Math.min(1, logicalRange.from / (total - 1)));
                var toPct = Math.max(0, Math.min(1, logicalRange.to / (total - 1)));
                navOverlay.style.left = (fromPct * 100) + '%';
                navOverlay.style.width = ((toPct - fromPct) * 100) + '%';
                navOverlay.style.display = (toPct - fromPct) * 100 > 0.5 ? 'block' : 'none';
            }}

            _modalRangeSub = chart.timeScale().subscribeVisibleLogicalRangeChange(function() {{
                requestAnimationFrame(updateModalOverlay);
            }});
            setTimeout(updateModalOverlay, 500);

            // overlay 拖拽
            var dragging = false, dragStartX = 0, dragStartLeft = 0, dragStartWidth = 0;
            navOverlay.addEventListener('mousedown', function(e) {{
                dragging = true; dragStartX = e.clientX;
                dragStartLeft = parseFloat(navOverlay.style.left) || 0;
                dragStartWidth = parseFloat(navOverlay.style.width) || 10;
                navOverlay.style.cursor = 'grabbing'; e.preventDefault();
            }});

            _modalMouseMoveHandler = function(e) {{
                if (!dragging || !_modalChart || !source.data || source.data.length === 0) return;
                var navRect = navContainerEl.getBoundingClientRect();
                var deltaPct = ((e.clientX - dragStartX) / navRect.width) * 100;
                var newLeft = dragStartLeft + deltaPct;
                var width = dragStartWidth;
                if (newLeft < 0) newLeft = 0;
                if (newLeft + width > 100) newLeft = 100 - width;
                navOverlay.style.left = newLeft + '%';
                var total = source.data.length;
                var fromIdx = Math.round((newLeft / 100) * (total - 1));
                var toIdx = Math.round(((newLeft + width) / 100) * (total - 1));
                _modalChart.timeScale().setVisibleLogicalRange({{ from: fromIdx, to: toIdx }});
            }};
            _modalMouseUpHandler = function() {{ if (dragging) {{ dragging = false; navOverlay.style.cursor = 'grab'; }} }};

            window.addEventListener('mousemove', _modalMouseMoveHandler);
            window.addEventListener('mouseup', _modalMouseUpHandler);

            // tooltip
            var klineMap = {{}};
            if (source.data && source.data.length > 0) {{
                source.data.forEach(function(d) {{ klineMap[typeof d.time === 'number' ? Math.floor(d.time) : d.time] = d; }});
            }}
            var markerMap = {{}};
            if (source.markers && source.markers.length > 0) {{
                source.markers.forEach(function(m) {{ markerMap[m.time] = m; }});
            }}

            chart.subscribeCrosshairMove(function(param) {{
                try {{
                    if (!param.point || param.time === undefined || param.time === null) {{
                        _modalTooltipEl.style.display = 'none'; return;
                    }}
                    var ts = param.time;
                    if (typeof ts === 'object' && ts.year !== undefined) {{
                        ts = Math.floor(new Date(ts.year, ts.month - 1, ts.day).getTime() / 1000);
                    }} else if (typeof ts === 'number') {{ ts = Math.floor(ts); }}
                    else if (typeof ts === 'string') {{ ts = Math.floor(new Date(ts).getTime() / 1000); }}

                    var html = '';
                    var dataPoint = klineMap[ts];
                    if (dataPoint) {{
                        if (!source.is_tick && dataPoint.open !== undefined) {{
                            html += '<div style="font-weight:bold;margin-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.15);padding-bottom:4px;">' + _fmtLwcTime(ts) + '</div>';
                            html += '<div>开: ' + Number(dataPoint.open).toFixed(2) + '</div>';
                            html += '<div>高: ' + Number(dataPoint.high).toFixed(2) + '</div>';
                            html += '<div>低: ' + Number(dataPoint.low).toFixed(2) + '</div>';
                            html += '<div>收: ' + Number(dataPoint.close).toFixed(2) + '</div>';
                        }} else if (source.is_tick && dataPoint.value !== undefined) {{
                            html += '<div style="font-weight:bold;margin-bottom:6px;border-bottom:1px solid rgba(255,255,255,0.15);padding-bottom:4px;">' + _fmtLwcTime(ts) + '</div>';
                            html += '<div>价格: ' + Number(dataPoint.value).toFixed(2) + '</div>';
                        }}
                    }}
                    var marker = markerMap[ts];
                    if (marker && marker.tooltip) {{
                        html += '<div style="margin-top:6px;border-top:1px solid rgba(255,255,255,0.15);padding-top:4px;">';
                        html += '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + (marker.color || '#e0e0e0') + ';margin-right:6px;"></span>';
                        html += '<span style="color:' + (marker.color || '#e0e0e0') + ';font-weight:bold;">' + marker.tooltip + '</span></div>';
                    }}
                    if (html) {{
                        _modalTooltipEl.innerHTML = html;
                        _modalTooltipEl.style.display = 'block';
                        var rect = mainContainer.getBoundingClientRect();
                        var left = rect.left + param.point.x + 16;
                        var top = rect.top + param.point.y + 16;
                        if (left + 260 > window.innerWidth) left = rect.left + param.point.x - 260;
                        if (top + 140 > window.innerHeight) top = rect.top + param.point.y - 140;
                        if (left < 10) left = 10; if (top < 10) top = 10;
                        _modalTooltipEl.style.left = left + 'px';
                        _modalTooltipEl.style.top = top + 'px';
                    }} else {{
                        _modalTooltipEl.style.display = 'none';
                    }}
                }} catch (err) {{
                    _modalTooltipEl.style.display = 'none';
                }}
            }});

            // resize
            _modalResizeHandler = function() {{
                if (_modalChart && mainContainer) {{
                    _modalChart.applyOptions({{ width: mainContainer.clientWidth, height: mainContainer.clientHeight }});
                    _modalChart.timeScale().fitContent();
                }}
                if (_modalNavChart && navContainerEl) {{
                    _modalNavChart.applyOptions({{ width: navContainerEl.clientWidth }});
                    _modalNavChart.timeScale().fitContent();
                }}
            }};
            window.addEventListener('resize', _modalResizeHandler);

            // fitContent：让 LWC 自动调整显示范围（数据量大时从右侧显示最大可容纳范围）
            setTimeout(function() {{
                chart.timeScale().fitContent();
            }}, 100);
        }}

        function closeChartModal() {{
            var modal = document.getElementById('chart-modal');
            if (modal) modal.style.display = 'none';
            document.body.style.overflow = '';
            closeChartModalCleanup();
        }}

        function closeChartModalCleanup() {{
            if (_modalRangeSub) {{ try {{ _modalRangeSub(); }} catch(e) {{}} _modalRangeSub = null; }}
            if (_modalChart) {{ _modalChart.remove(); _modalChart = null; }}
            if (_modalNavChart) {{ _modalNavChart.remove(); _modalNavChart = null; }}
            if (_modalResizeHandler) {{ window.removeEventListener('resize', _modalResizeHandler); _modalResizeHandler = null; }}
            if (_modalMouseMoveHandler) {{ window.removeEventListener('mousemove', _modalMouseMoveHandler); _modalMouseMoveHandler = null; }}
            if (_modalMouseUpHandler) {{ window.removeEventListener('mouseup', _modalMouseUpHandler); _modalMouseUpHandler = null; }}
            if (_modalTooltipEl) {{ _modalTooltipEl.remove(); _modalTooltipEl = null; }}
            var navContainerEl = document.getElementById('chart-modal-nav');
            if (navContainerEl) navContainerEl.innerHTML = '';
            // 克隆 overlay 以清除所有旧的事件监听器
            var navOverlay = document.getElementById('chart-modal-nav-overlay');
            if (navOverlay && navOverlay.parentNode) {{
                var newOverlay = navOverlay.cloneNode(true);
                newOverlay.style.left = '0%';
                newOverlay.style.width = '100%';
                newOverlay.style.display = 'block';
                navOverlay.parentNode.replaceChild(newOverlay, navOverlay);
            }}
        }}

        // 更新数据范围信息提示
        function updateKlineRangeInfo(source) {{
            var infoEl = document.getElementById('kline-range-info');
            if (!infoEl || !source || !source.data || source.data.length === 0) return;
            var total = source.data.length;
            var first = source.data[0];
            var last = source.data[total - 1];
            var firstDate = new Date(first.time * 1000);
            var lastDate = new Date(last.time * 1000);
            var fmt = function(d) {{
                return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0');
            }};
            var freq = 'K线';
            if (source.is_tick) {{
                freq = 'Tick';
            }} else if (source.data.length > 1) {{
                var intervals = [];
                for (var i = 1; i < Math.min(source.data.length, 20); i++) {{
                    intervals.push(source.data[i].time - source.data[i-1].time);
                }}
                intervals.sort(function(a, b) {{ return a - b; }});
                var medianInterval = intervals[Math.floor(intervals.length / 2)];
                if (medianInterval < 120) freq = '分钟';
                else if (medianInterval < 7200) freq = '小时';
                else freq = '日线';
            }}
            infoEl.textContent = '数据: ' + fmt(firstDate) + ' ~ ' + fmt(lastDate) + ' 共 ' + total.toLocaleString() + ' 根 ' + freq + '，数据量较大时可通过缩放/平移查看全部';
        }}

        // 初始化 K线图/TICK价格图
        if (klineDataSources.length > 0) {{
            generateKlineTabs();
            updateChartTitle(0);
            drawKlineChart(0);
        }}

        // ========== 交易记录分页和筛选功能 ==========
        var tradesData = {{}};  // 存储所有交易数据
        var filteredData = {{}};  // 存储筛选后的数据
        var pageSize = 50;  // 每页显示条数
        var currentPages = {{}};  // 各数据源当前页码

        // 初始化交易记录
        function initTradesTable(sourceIdx) {{
            var tbody = document.getElementById('trades-tbody-' + sourceIdx);
            if (!tbody) return;

            // 保存原始数据
            var rows = tbody.querySelectorAll('tr');
            tradesData[sourceIdx] = [];

            // 判断是否是汇总表格（通过表头列数判断）
            var table = document.getElementById('trades-table-' + sourceIdx);
            var isCombined = table && table.querySelector('thead th:nth-child(3)') && table.querySelector('thead th:nth-child(3)').textContent === '数据源';

            rows.forEach(function(row) {{
                var cells = row.querySelectorAll('td');
                tradesData[sourceIdx].push({{
                    element: row.cloneNode(true),
                    time: cells[1] ? cells[1].textContent : '',
                    action: isCombined ? (cells[3] ? cells[3].textContent : '') : (cells[2] ? cells[2].textContent : ''),
                    price: isCombined ? (cells[4] ? cells[4].textContent : '') : (cells[3] ? cells[3].textContent : ''),
                    profit: isCombined ? (cells[6] ? cells[6].textContent : '') : (cells[5] ? cells[5].textContent : '')
                }});
            }});

            filteredData[sourceIdx] = tradesData[sourceIdx].slice();
            currentPages[sourceIdx] = 1;

            renderPage(sourceIdx);
        }}

        // 渲染当前页
        function renderPage(sourceIdx) {{
            var tbody = document.getElementById('trades-tbody-' + sourceIdx);
            if (!tbody) return;

            var data = filteredData[sourceIdx] || [];
            var totalPages = Math.ceil(data.length / pageSize) || 1;
            var currentPage = currentPages[sourceIdx] || 1;

            // 确保当前页在有效范围内
            if (currentPage > totalPages) currentPage = totalPages;
            if (currentPage < 1) currentPage = 1;
            currentPages[sourceIdx] = currentPage;

            // 计算显示范围
            var startIdx = (currentPage - 1) * pageSize;
            var endIdx = Math.min(startIdx + pageSize, data.length);

            // 清空表格
            tbody.innerHTML = '';

            // 显示当前页数据
            for (var i = startIdx; i < endIdx; i++) {{
                var row = data[i].element.cloneNode(true);
                row.cells[0].textContent = i + 1;  // 更新序号
                tbody.appendChild(row);
            }}

            // 更新分页信息
            var currentPageSpan = document.querySelector('.current-page-' + sourceIdx);
            var totalPagesSpan = document.querySelector('.total-pages-' + sourceIdx);
            var tradesCountSpan = document.querySelector('.trades-count-' + sourceIdx);

            if (currentPageSpan) currentPageSpan.textContent = currentPage;
            if (totalPagesSpan) totalPagesSpan.textContent = totalPages;
            if (tradesCountSpan) tradesCountSpan.textContent = data.length;

            // 更新分页按钮状态
            updatePaginationButtons(sourceIdx, currentPage, totalPages);
        }}

        // 更新分页按钮状态
        function updatePaginationButtons(sourceIdx, currentPage, totalPages) {{
            var pagination = document.getElementById('pagination-' + sourceIdx);
            if (!pagination) return;

            var buttons = pagination.querySelectorAll('button');
            buttons[0].disabled = currentPage === 1;  // 首页
            buttons[1].disabled = currentPage === 1;  // 上一页
            buttons[2].disabled = currentPage === totalPages;  // 下一页
            buttons[3].disabled = currentPage === totalPages;  // 末页
        }}

        // 获取总页数
        function getTotalPages(sourceIdx) {{
            var data = filteredData[sourceIdx] || [];
            return Math.ceil(data.length / pageSize) || 1;
        }}

        // 跳转到指定页
        function goToPage(sourceIdx, page) {{
            var totalPages = getTotalPages(sourceIdx);
            if (page < 1) page = 1;
            if (page > totalPages) page = totalPages;
            currentPages[sourceIdx] = page;
            renderPage(sourceIdx);
        }}

        // 上一页
        function prevPage(sourceIdx) {{
            goToPage(sourceIdx, (currentPages[sourceIdx] || 1) - 1);
        }}

        // 下一页
        function nextPage(sourceIdx) {{
            goToPage(sourceIdx, (currentPages[sourceIdx] || 1) + 1);
        }}

        // 跳转到输入的页码
        function jumpToPage(sourceIdx) {{
            var input = document.querySelector('.page-input-' + sourceIdx);
            if (input && input.value) {{
                goToPage(sourceIdx, parseInt(input.value));
                input.value = '';
            }}
        }}

        // 应用筛选
        function applyTradesFilter(sourceIdx) {{
            var timeFilter = document.querySelector('.filter-time-' + sourceIdx);
            var priceFilter = document.querySelector('.filter-price-' + sourceIdx);
            var actionFilter = document.querySelector('.filter-action-' + sourceIdx);
            var profitFilter = document.querySelector('.filter-profit-' + sourceIdx);

            var timeValue = timeFilter ? timeFilter.value.trim().toLowerCase() : '';
            var priceValue = priceFilter ? priceFilter.value.trim() : '';
            var actionValue = actionFilter ? actionFilter.value : '';
            var profitValue = profitFilter ? profitFilter.value : '';

            var originalData = tradesData[sourceIdx] || [];

            filteredData[sourceIdx] = originalData.filter(function(item) {{
                // 时间筛选
                if (timeValue && item.time.toLowerCase().indexOf(timeValue) === -1) {{
                    return false;
                }}
                // 价格筛选
                if (priceValue && item.price.indexOf(priceValue) === -1) {{
                    return false;
                }}
                // 操作筛选
                if (actionValue && item.action.indexOf(actionValue) === -1) {{
                    return false;
                }}
                // 盈亏筛选
                if (profitValue) {{
                    var profitText = item.profit.replace(/[,\s]/g, '');
                    var profitNum = parseFloat(profitText);
                    if (profitValue === 'profit' && (isNaN(profitNum) || profitNum <= 0)) {{
                        return false;
                    }}
                    if (profitValue === 'loss' && (isNaN(profitNum) || profitNum >= 0)) {{
                        return false;
                    }}
                }}
                return true;
            }});

            currentPages[sourceIdx] = 1;
            renderPage(sourceIdx);
        }}

        // 重置筛选
        function resetTradesFilter(sourceIdx) {{
            var timeFilter = document.querySelector('.filter-time-' + sourceIdx);
            var priceFilter = document.querySelector('.filter-price-' + sourceIdx);
            var actionFilter = document.querySelector('.filter-action-' + sourceIdx);
            var profitFilter = document.querySelector('.filter-profit-' + sourceIdx);

            if (timeFilter) timeFilter.value = '';
            if (priceFilter) priceFilter.value = '';
            if (actionFilter) actionFilter.value = '';
            if (profitFilter) profitFilter.value = '';

            filteredData[sourceIdx] = tradesData[sourceIdx].slice();
            currentPages[sourceIdx] = 1;
            renderPage(sourceIdx);
        }}

        // 页面加载后初始化所有交易表格
        document.addEventListener('DOMContentLoaded', function() {{
            // 查找所有交易表格并初始化（支持数字索引和字符串索引如 combined）
            var tables = document.querySelectorAll('[id^="trades-table-"]');
            tables.forEach(function(table) {{
                var idx = table.id.replace('trades-table-', '');
                if (idx) {{
                    initTradesTable(idx);
                }}
            }});
        }});

        // 全景图弹窗
        function openPanoramaModal() {{
            if (!window._signalChartsData || window._signalChartsData.length === 0) return;
            var modal = document.getElementById('panorama-modal');
            var container = document.getElementById('panorama-content');
            if (!modal || !container) return;
            container.innerHTML = '';
            window._signalChartsData.forEach(function(chart, idx) {{
                var item = document.createElement('div');
                item.style.cssText = 'margin-bottom:16px; background:rgba(26,26,46,0.8); border-radius:8px; padding:12px; border:1px solid rgba(255,255,255,0.05);';
                item.innerHTML = '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">'
                    + '<span style="color:#e0e0e0; font-size:14px; font-weight:500;">' + chart.symbol + ' ' + chart.kline_period + ' 交易信号全景</span>'
                    + '<button onclick="downloadSignalChart(' + idx + ')" style="background:rgba(100,181,246,0.15); border:1px solid rgba(100,181,246,0.3); color:#64b5f6; padding:4px 12px; border-radius:4px; cursor:pointer; font-size:12px;">⬇️ 下载图片</button>'
                    + '</div>'
                    + '<img src="data:image/png;base64,' + chart.base64_image + '" data-filename="' + chart.filename + '" style="width:100%; border-radius:4px; cursor:pointer;" title="右键点击图片可另存为">';
                container.appendChild(item);
            }});
            modal.style.display = 'flex';
            document.body.style.overflow = 'hidden';
        }}
        function closePanoramaModal() {{
            var modal = document.getElementById('panorama-modal');
            if (modal) modal.style.display = 'none';
            document.body.style.overflow = '';
        }}
        // 下载信号图
        function downloadSignalChart(index) {{
            var data = window._signalChartsData && window._signalChartsData[index];
            if (!data) return;
            var link = document.createElement('a');
            link.href = 'data:image/png;base64,' + data.base64_image;
            link.download = data.filename || 'signal_chart.png';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        }}
        // 页面加载后：如果有信号图则显示全景图按钮
        document.addEventListener('DOMContentLoaded', function() {{
            var btn = document.getElementById('panorama-btn');
            if (btn && window._signalChartsData && window._signalChartsData.length > 0) {{
                btn.style.display = 'flex';
            }}
        }});
    </script>
</body>
</html>'''

    def __init__(self, logger=None):
        """初始化报告生成器

        Args:
            logger: 日志管理器实例
        """
        self.logger = logger

    def log(self, message: str):
        """记录日志"""
        if self.logger:
            self.logger.log_message(message)
        else:
            print(message)

    def _load_plotly_js(self) -> str:
        """从本地加载 plotly.min.js，如果本地文件不存在则使用 CDN 备用

        Returns:
            完整的 script 标签（内联 JS 或 CDN 引用）
        """
        # CDN 备用地址
        CDN_URL = "https://cdn.bootcdn.net/ajax/libs/plotly.js/2.27.0/plotly.min.js"

        # 获取当前文件所在目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # 构建 plotly.min.js 的路径 (相对于 ssquant/backtest/ -> ssquant/assets/)
        plotly_path = os.path.join(current_dir, '..', 'assets', 'plotly.min.js')
        plotly_path = os.path.normpath(plotly_path)

        try:
            with open(plotly_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.log(f"已从本地加载 plotly.min.js: {plotly_path}")
            # 返回内联 script 标签
            return f'<script>{content}</script>'
        except FileNotFoundError:
            self.log(f"本地 plotly.min.js 未找到，使用 CDN 备用: {CDN_URL}")
            # 返回 CDN 引用的 script 标签
            return f'<script src="{CDN_URL}"></script>'
        except Exception as e:
            self.log(f"加载本地 plotly.min.js 失败 ({e})，使用 CDN 备用")
            # 返回 CDN 引用的 script 标签
            return f'<script src="{CDN_URL}"></script>'

    def _load_lightweight_charts_js(self) -> str:
        """加载 TradingView Lightweight Charts™（K线图专用，高性能）

        Returns:
            Lightweight Charts™ CDN script 标签
        """
        CDN_URL = "https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.1/dist/lightweight-charts.standalone.production.js"
        return f'<script src="{CDN_URL}"></script>'

    def _generate_signal_charts(self, results: Dict, output_dir: str) -> List[Dict]:
        """为每个数据源生成 matplotlib K线+交易信号图，返回 base64 编码的图片列表

        Args:
            results: 回测结果字典
            output_dir: 输出目录

        Returns:
            每个元素包含 symbol、kline_period、base64_image 的字典列表
        """
        from .backtest_visualization import BacktestVisualizer

        charts = []
        visualizer = BacktestVisualizer(logger=self.logger)

        for key, result in results.items():
            if key == 'performance':
                continue
            if not isinstance(result, dict):
                continue

            symbol = result.get('symbol', 'unknown')
            kline_period = result.get('kline_period', '')

            # 构造 _generate_price_chart 需要的 result 字典
            klines = result.get('data', pd.DataFrame()).copy()
            # 兼容：如果 datetime 是索引，转为一列
            if isinstance(klines.index, pd.DatetimeIndex) and 'datetime' not in klines.columns:
                klines['datetime'] = klines.index
            elif 'datetime' not in klines.columns and len(klines.columns) > 0:
                # 尝试用第一列作为时间
                klines['datetime'] = klines.index

            trades = result.get('trades', []) or []
            if not trades:
                self.log(f"跳过信号图 ({symbol} {kline_period}): 无交易记录")
                continue
            if klines.empty:
                self.log(f"跳过信号图 ({symbol} {kline_period}): K线数据为空")
                continue

            chart_result = {
                'symbol': symbol,
                'kline_period': kline_period,
                'trades': trades,
                'klines': klines,
                'total_net_profit': result.get('total_net_profit', 0),
                'win_rate': result.get('win_rate', 0),
                'max_drawdown_pct': result.get('max_drawdown_pct', 0),
                'initial_capital': result.get('initial_capital', 100000.0),
            }

            # 生成图片路径
            chart_path = os.path.join(output_dir, f"{symbol}_{kline_period}_signal_chart.png")

            try:
                success = visualizer._generate_price_chart(chart_result, chart_path)
                if success and os.path.exists(chart_path):
                    with open(chart_path, 'rb') as f:
                        img_data = base64.b64encode(f.read()).decode('utf-8')
                    charts.append({
                        'symbol': symbol,
                        'kline_period': kline_period,
                        'base64_image': img_data,
                        'filename': f"{symbol}_{kline_period}_signal_chart.png"
                    })
                    self.log(f"信号图已生成: {chart_path}")
                else:
                    self.log(f"信号图生成失败: {symbol} {kline_period} (trades={len(trades)}, klines shape={klines.shape})")
            except Exception as e:
                import traceback
                self.log(f"生成信号图时出错 ({symbol} {kline_period}): {e}")
                self.log(traceback.format_exc())

        return charts

    def _render_signal_charts_html(self, chart_list: List[Dict]) -> str:
        """将信号图 base64 列表渲染为隐藏的 JS 数据 + 全景图弹窗容器。

        图片默认不显示，通过点击工具栏"全景图"按钮在弹窗中查看。

        Args:
            chart_list: _generate_signal_charts 返回的列表

        Returns:
            HTML 字符串（含 JS 数据定义和隐藏弹窗）
        """
        if not chart_list:
            return '<script>window._signalChartsData = [];</script>'

        # 序列化数据为 JSON-safe 字符串
        import json
        data_js = json.dumps(chart_list, ensure_ascii=False)

        html_parts = []
        html_parts.append(f'<script>window._signalChartsData = {data_js};</script>')
        html_parts.append('<!-- 全景图弹窗 -->')
        html_parts.append('<div id="panorama-modal" style="display:none; position:fixed; top:0; left:0; width:100vw; height:100vh; background:rgba(18,18,30,0.98); z-index:2500; flex-direction:column;">')
        html_parts.append('    <div style="display:flex; justify-content:space-between; align-items:center; padding:12px 20px; border-bottom:1px solid rgba(255,255,255,0.1);">')
        html_parts.append('        <span style="color:#e0e0e0; font-size:16px; font-weight:500;">📊 K线信号综合图（可右键保存或点击下方按钮下载）</span>')
        html_parts.append('        <button onclick="closePanoramaModal()" style="background:transparent; border:1px solid rgba(255,255,255,0.15); color:#888; width:32px; height:32px; border-radius:4px; font-size:20px; cursor:pointer; display:flex; align-items:center; justify-content:center;">×</button>')
        html_parts.append('    </div>')
        html_parts.append('    <div id="panorama-content" style="flex:1; overflow-y:auto; padding:20px; max-width:1400px; margin:0 auto; width:100%;"></div>')
        html_parts.append('</div>')

        return '\n'.join(html_parts)

    def generate_report(self, results: Dict, multi_data_source=None, output_dir: str = "backtest_results") -> str:
        """生成 HTML 回测报告

        Args:
            results: 回测结果字典
            multi_data_source: 多数据源实例
            output_dir: 输出目录

        Returns:
            报告文件路径
        """
        # 检查是否禁用报告生成
        if os.environ.get('NO_VISUALIZATION', '').lower() == 'true':
            self.log("报告生成已被禁用 (NO_VISUALIZATION=True)")
            return None

        if os.environ.get('NO_CONSOLE_LOG', '').lower() == 'true':
            return None

        # 创建输出目录
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # 过滤结果，只保留有效的数据源结果
        filtered_results = {k: v for k, v in results.items()
                          if k != 'performance' and isinstance(v, dict) and 'trades' in v}

        if not filtered_results:
            self.log("没有可用的回测结果")
            return None

        self.log(f"找到 {len(filtered_results)} 个数据源的结果")

        # 提取所有数据源信息
        source_infos = []
        for key, result in filtered_results.items():
            source_infos.append({
                'key': key,
                'symbol': result.get('symbol', 'unknown'),
                'kline_period': result.get('kline_period', ''),
                'result': result
            })

        # 策略信息
        strategy_info = ' | '.join([f"{s['symbol']} {s['kline_period']}" for s in source_infos])

        # 计算综合指标
        combined_metrics = self._calculate_combined_metrics(filtered_results)

        # 获取各数据源的利润曲线（从0开始，便于对比）
        profit_data_sources = self._get_profit_data_sources(filtered_results)

        # 计算综合利润曲线（净利润：扣除成本）
        combined_profit_data = self._get_combined_profit_data(filtered_results)

        # 计算综合交易盈亏曲线（未扣手续费）
        combined_gross_profit_data = self._get_combined_gross_profit_data(filtered_results)

        # 获取价格曲线数据（用于右侧Y轴显示）
        price_data_sources = self._get_price_data_sources(filtered_results)

        # 计算各数据源的回撤（基于权益曲线计算，更准确）
        drawdown_data_sources = self._get_drawdown_from_results(filtered_results)

        # 计算综合回撤（基于综合权益）
        combined_drawdown_data = self._get_combined_drawdown(filtered_results)

        # 提取 K线数据和交易标记
        kline_data_sources = self._get_kline_data_sources(filtered_results)

        # 生成信号图（matplotlib K线+交易标记静态图）
        signal_chart_list = self._generate_signal_charts(filtered_results, output_dir)
        signal_charts_html = self._render_signal_charts_html(signal_chart_list)

        # 生成各部分 HTML
        combined_metrics_cards = self._generate_metrics_cards(combined_metrics)
        source_comparison_section = self._generate_source_comparison(filtered_results)
        source_tabs = self._generate_source_tabs(source_infos)
        source_details = self._generate_source_details(source_infos, combined_metrics)

        # 获取日期范围
        if combined_profit_data['dates']:
            start_date = combined_profit_data['dates'][0]
            end_date = combined_profit_data['dates'][-1]
        else:
            start_date = '-'
            end_date = '-'

        # 加载 plotly.js（本地优先，CDN 备用）
        plotly_script_tag = self._load_plotly_js()
        lwc_script_tag = self._load_lightweight_charts_js()

        # 填充模板
        html = self.HTML_TEMPLATE.format(
            strategy_name=strategy_info,
            strategy_info=strategy_info,
            start_date=start_date,
            end_date=end_date,
            report_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            combined_metrics_cards=combined_metrics_cards,
            source_comparison_section=source_comparison_section,
            source_tabs=source_tabs,
            source_details=source_details,
            profit_data_sources=json.dumps(profit_data_sources, cls=NumpyEncoder),
            combined_profit_data=json.dumps(combined_profit_data, cls=NumpyEncoder),
            combined_gross_profit_data=json.dumps(combined_gross_profit_data, cls=NumpyEncoder),
            price_data_sources=json.dumps(price_data_sources, cls=NumpyEncoder),
            drawdown_data_sources=json.dumps(drawdown_data_sources, cls=NumpyEncoder),
            combined_drawdown_data=json.dumps(combined_drawdown_data, cls=NumpyEncoder),
            kline_data_sources=json.dumps(kline_data_sources, cls=NumpyEncoder),
            plotly_script_tag=plotly_script_tag,
            lwc_script_tag=lwc_script_tag,
            signal_charts=signal_charts_html
        )

        # 保存文件
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        first_symbol = source_infos[0]['symbol']
        output_path = os.path.join(output_dir, f"{first_symbol}_report_{timestamp}.html")

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)

        self.log(f"HTML 报告已保存到: {output_path}")
        return output_path

    def _calculate_combined_metrics(self, results: Dict) -> Dict:
        """计算综合绩效指标"""
        metrics = {
            'initial_capital': 0,
            'final_equity': 0,
            'total_net_profit': 0,
            'total_trades': 0,
            'win_trades': 0,
            'loss_trades': 0,
            'win_rate': 0,
            'max_drawdown_pct': 0,
            'annual_return': 0,
            'sharpe_ratio': 0,
            'profit_factor': 0,
            'total_commission': 0,
            'total_slippage': 0,
            'total_amount_profit': 0,
        }

        all_sharpe = []
        all_annual_return = []

        for key, result in results.items():
            capital = result.get('initial_capital', 100000)
            metrics['initial_capital'] += capital
            metrics['final_equity'] += result.get('final_equity', capital)
            metrics['total_net_profit'] += result.get('total_net_profit', 0)
            metrics['total_trades'] += result.get('total_trades', 0)
            metrics['win_trades'] += result.get('win_trades', 0)
            metrics['loss_trades'] += result.get('loss_trades', 0)
            metrics['total_commission'] += result.get('total_commission', 0)
            metrics['total_slippage'] += result.get('total_slippage', 0)
            metrics['total_amount_profit'] += result.get('total_amount_profit', 0)

            if result.get('sharpe_ratio'):
                all_sharpe.append((result.get('sharpe_ratio', 0), capital))
            if result.get('annual_return'):
                all_annual_return.append((result.get('annual_return', 0), capital))

        # 基于综合权益曲线计算最大回撤（而非单品种最大值）
        combined_equity = self._get_combined_equity_curve(results)
        if not combined_equity.empty and combined_equity.max() > 0:
            combined_equity = combined_equity.clip(lower=0.01)
            cummax = combined_equity.cummax()
            drawdown = cummax - combined_equity
            metrics['max_drawdown'] = drawdown.max()
            metrics['max_drawdown_pct'] = (drawdown / cummax).max() * 100
        else:
            metrics['max_drawdown'] = 0
            metrics['max_drawdown_pct'] = 0

        # 计算胜率
        if metrics['total_trades'] > 0:
            metrics['win_rate'] = metrics['win_trades'] / metrics['total_trades'] * 100

        # 计算收益率
        if metrics['initial_capital'] > 0:
            metrics['total_return'] = (metrics['final_equity'] - metrics['initial_capital']) / metrics['initial_capital'] * 100
        else:
            metrics['total_return'] = 0

        # 加权平均夏普比率和年化收益率
        if all_sharpe:
            total_weight = sum(w for _, w in all_sharpe)
            metrics['sharpe_ratio'] = sum(v * w for v, w in all_sharpe) / total_weight if total_weight > 0 else 0

        if all_annual_return:
            total_weight = sum(w for _, w in all_annual_return)
            metrics['annual_return'] = sum(v * w for v, w in all_annual_return) / total_weight if total_weight > 0 else 0

        # 盈亏比
        first_result = list(results.values())[0]
        metrics['profit_factor'] = first_result.get('profit_factor', 0)

        return metrics

    def _get_profit_data_sources(self, results: Dict) -> List[Dict]:
        """获取各数据源的利润曲线数据（从0开始，便于对比）"""
        profit_sources = []

        for key, result in results.items():
            if 'equity_curve' not in result:
                continue

            equity_curve = result['equity_curve']
            if not isinstance(equity_curve, pd.Series) or equity_curve.empty:
                continue

            # 获取初始资金
            initial_capital = result.get('initial_capital', 100000)

            # 计算利润曲线（权益 - 初始资金）
            profit_curve = equity_curve - initial_capital

            # 转换为列表（保留原始数据）
            dates = [d.strftime('%Y-%m-%d %H:%M') if hasattr(d, 'strftime') else str(d) for d in profit_curve.index]
            values = profit_curve.values.tolist()

            name = f"{result.get('symbol', '')} {result.get('kline_period', '')}"

            profit_sources.append({
                'name': name,
                'dates': dates,
                'values': values,
                'initial_capital': initial_capital
            })

        return profit_sources

    def _get_price_data_sources(self, results: Dict) -> List[Dict]:
        """获取各数据源的价格曲线数据（归一化为相对值，起点=100）"""
        price_sources = []
        num_sources = len(results)

        for key, result in results.items():
            if 'data' not in result:
                continue

            data = result['data']
            if not isinstance(data, pd.DataFrame) or data.empty:
                continue

            # 获取收盘价列
            if 'close' in data.columns:
                close_prices = data['close']
            elif 'LastPrice' in data.columns:
                close_prices = data['LastPrice']
            else:
                continue

            # 转换为列表
            dates = [d.strftime('%Y-%m-%d %H:%M') if hasattr(d, 'strftime') else str(d) for d in close_prices.index]

            # 多数据源时使用归一化（相对值，起点=100）
            if num_sources > 1:
                first_price = close_prices.iloc[0] if close_prices.iloc[0] != 0 else 1
                normalized_prices = (close_prices / first_price * 100).values.tolist()
                values = normalized_prices
                is_normalized = True
            else:
                # 单数据源直接使用原始价格
                values = close_prices.values.tolist()
                is_normalized = False

            name = f"{result.get('symbol', '')} {result.get('kline_period', '')}"

            price_sources.append({
                'name': f"{name} 价格" if not is_normalized else f"{name} 相对值",
                'dates': dates,
                'values': values,
                'is_normalized': is_normalized
            })

        return price_sources

    def _get_combined_profit_data(self, results: Dict) -> Dict:
        """获取综合利润曲线数据（所有数据源的利润相加）

        对于多周期数据，使用交集（intersection）只保留共同时间点，
        避免 ffill 导致的水平线延伸问题。
        """
        all_profit_curves = []

        for key, result in results.items():
            if 'equity_curve' in result and isinstance(result['equity_curve'], pd.Series):
                initial_capital = result.get('initial_capital', 100000)
                profit_curve = result['equity_curve'] - initial_capital
                all_profit_curves.append(profit_curve)

        if not all_profit_curves:
            return {'dates': [], 'values': []}

        # 合并利润曲线
        if len(all_profit_curves) == 1:
            combined = all_profit_curves[0]
        else:
            # 使用交集：只保留所有数据源都有数据的时间点
            common_indices = all_profit_curves[0].index
            for curve in all_profit_curves[1:]:
                common_indices = common_indices.intersection(curve.index)

            # 如果没有共同时间点，使用最短周期的数据
            if len(common_indices) == 0:
                # 找到数据点最多的曲线作为基准
                base_curve = max(all_profit_curves, key=len)
                combined = base_curve.copy()
                for curve in all_profit_curves:
                    if curve is not base_curve:
                        # 只在有数据的时间点相加
                        aligned = curve.reindex(base_curve.index)
                        combined = combined + aligned.fillna(0)
            else:
                # 在共同时间点上相加
                combined = pd.Series(0.0, index=common_indices)
                for curve in all_profit_curves:
                    combined = combined + curve.reindex(common_indices)

        # 不做降采样，保留原始数据
        dates = [d.strftime('%Y-%m-%d %H:%M') if hasattr(d, 'strftime') else str(d) for d in combined.index]
        values = combined.values.tolist()

        return {'dates': dates, 'values': values}

    def _get_combined_gross_profit_data(self, results: Dict) -> Dict:
        """获取综合交易盈亏曲线数据（未扣手续费）"""
        all_gross_curves = []

        for key, result in results.items():
            if 'gross_equity_curve' in result and isinstance(result['gross_equity_curve'], pd.Series):
                initial_capital = result.get('initial_capital', 100000)
                gross_profit_curve = result['gross_equity_curve'] - initial_capital
                all_gross_curves.append(gross_profit_curve)

        if not all_gross_curves:
            return {'dates': [], 'values': []}

        # 合并交易盈亏曲线
        if len(all_gross_curves) == 1:
            combined = all_gross_curves[0]
        else:
            # 使用交集：只保留所有数据源都有数据的时间点
            common_indices = all_gross_curves[0].index
            for curve in all_gross_curves[1:]:
                common_indices = common_indices.intersection(curve.index)

            if len(common_indices) == 0:
                base_curve = max(all_gross_curves, key=len)
                combined = base_curve.copy()
                for curve in all_gross_curves:
                    if curve is not base_curve:
                        aligned = curve.reindex(base_curve.index)
                        combined = combined + aligned.fillna(0)
            else:
                combined = pd.Series(0.0, index=common_indices)
                for curve in all_gross_curves:
                    combined = combined + curve.reindex(common_indices)

        dates = [d.strftime('%Y-%m-%d %H:%M') if hasattr(d, 'strftime') else str(d) for d in combined.index]
        values = combined.values.tolist()

        return {'dates': dates, 'values': values}

    def _get_drawdown_from_results(self, results: Dict) -> List[Dict]:
        """从回测结果计算各数据源的回撤数据（基于权益曲线）"""
        drawdown_sources = []

        for key, result in results.items():
            if 'equity_curve' not in result:
                continue

            equity_curve = result['equity_curve']
            if not isinstance(equity_curve, pd.Series) or equity_curve.empty:
                continue

            # 计算回撤百分比
            cummax = equity_curve.cummax()
            drawdown_pct = (cummax - equity_curve) / cummax * 100
            drawdown_pct = drawdown_pct.fillna(0)

            # 转换为列表（保留原始数据）
            dates = [d.strftime('%Y-%m-%d %H:%M') if hasattr(d, 'strftime') else str(d) for d in drawdown_pct.index]
            values = drawdown_pct.values.tolist()

            name = f"{result.get('symbol', '')} {result.get('kline_period', '')}"

            drawdown_sources.append({
                'name': name,
                'dates': dates,
                'values': values
            })

        return drawdown_sources

    def _get_combined_equity_curve(self, results: Dict) -> pd.Series:
        """获取综合权益曲线（所有数据源权益相加）"""
        all_equity_curves = []

        for key, result in results.items():
            if 'equity_curve' in result and isinstance(result['equity_curve'], pd.Series):
                all_equity_curves.append(result['equity_curve'])

        if not all_equity_curves:
            return pd.Series(dtype=float)

        # 合并权益曲线
        if len(all_equity_curves) == 1:
            combined = all_equity_curves[0]
        else:
            # 使用交集：只保留所有数据源都有数据的时间点
            common_indices = all_equity_curves[0].index
            for curve in all_equity_curves[1:]:
                common_indices = common_indices.intersection(curve.index)

            # 如果没有共同时间点，使用最长周期的数据
            if len(common_indices) == 0:
                base_curve = max(all_equity_curves, key=len)
                combined = base_curve.copy()
                for curve in all_equity_curves:
                    if curve is not base_curve:
                        aligned = curve.reindex(base_curve.index)
                        combined = combined + aligned.fillna(method='ffill').fillna(method='bfill')
            else:
                # 在共同时间点上相加
                combined = pd.Series(0.0, index=common_indices)
                for curve in all_equity_curves:
                    combined = combined + curve.reindex(common_indices)

        return combined

    def _get_combined_drawdown(self, results: Dict) -> Dict:
        """计算综合回撤（基于综合权益曲线）

        对于多周期数据，使用交集（intersection）只保留共同时间点。
        """
        combined = self._get_combined_equity_curve(results)

        if combined.empty:
            return {'dates': [], 'values': []}

        # 计算回撤
        cummax = combined.cummax()
        drawdown_pct = (cummax - combined) / cummax * 100
        drawdown_pct = drawdown_pct.fillna(0)

        # 不做降采样，保留原始数据
        dates = [d.strftime('%Y-%m-%d %H:%M') if hasattr(d, 'strftime') else str(d) for d in drawdown_pct.index]
        values = drawdown_pct.values.tolist()

        return {'dates': dates, 'values': values}

    @staticmethod
    def _dt_to_lwc_ts(dt_raw):
        """将 datetime 转为秒级时间戳（Lightweight Charts™ 使用）。

        对 naive datetime 直接取 timestamp() 的整数值；
        若运行时不在东八区，后续可在调用处统一加时区偏移。
        """
        if dt_raw is None:
            return 0
        if hasattr(dt_raw, 'timestamp'):
            return int(dt_raw.timestamp())
        try:
            return int(pd.to_datetime(dt_raw).timestamp())
        except Exception:
            return 0

    def _get_kline_data_sources(self, results: Dict) -> List[Dict]:
        """提取各数据源的 K线/TICK 数据和交易标记（Lightweight Charts™ 格式）"""
        kline_sources = []

        for key, result in results.items():
            data = result.get('data')
            if data is None or not isinstance(data, pd.DataFrame) or data.empty:
                continue

            df = data.copy()
            kline_period = result.get('kline_period', '')
            is_tick = kline_period.lower() == 'tick' or 'LastPrice' in df.columns

            # 提取秒级时间戳（Lightweight Charts™ 原生支持 UTCTimestamp number）
            if isinstance(df.index, pd.DatetimeIndex):
                times = [self._dt_to_lwc_ts(d) for d in df.index]
            elif 'datetime' in df.columns:
                times = [self._dt_to_lwc_ts(d) for d in df['datetime']]
            else:
                times = list(range(len(df)))

            if is_tick:
                if 'LastPrice' in df.columns:
                    price_vals = df['LastPrice'].tolist()
                elif 'close' in df.columns:
                    price_vals = df['close'].tolist()
                else:
                    continue

                chart_data = [{'time': t, 'value': float(v)} for t, v in zip(times, price_vals) if pd.notna(v)]
            else:
                required_cols = ['open', 'high', 'low', 'close']
                if not all(col in df.columns for col in required_cols):
                    continue

                chart_data = [
                    {
                        'time': t,
                        'open': float(o),
                        'high': float(h),
                        'low': float(l),
                        'close': float(c)
                    }
                    for t, o, h, l, c in zip(times, df['open'], df['high'], df['low'], df['close'])
                    if pd.notna(o) and pd.notna(h) and pd.notna(l) and pd.notna(c)
                ]

            # LWC 要求数据严格按时间升序排列
            chart_data = sorted(chart_data, key=lambda x: x['time'])

            # 构建 K 线时间查找数组，用于将交易时间对齐到最近的 K 线时间点
            # （LWC 的 marker 必须精确匹配 series 中的某个 data time）
            valid_times = [d['time'] for d in chart_data]
            times_arr = np.array(valid_times)

            def _align_marker_time(ts):
                ts = int(ts)
                if len(times_arr) == 0:
                    return ts
                idx = np.searchsorted(times_arr, ts)
                if idx == 0:
                    return int(times_arr[0])
                if idx >= len(times_arr):
                    return int(times_arr[-1])
                before = int(times_arr[idx - 1])
                after = int(times_arr[idx])
                return after if (after - ts) < (ts - before) else before

            # 提取交易标记（统一为 Lightweight Charts™ marker 格式）
            trades = result.get('trades', [])
            markers = []

            def _add_marker(ts, action, price, volume, raw_suffix=''):
                _tooltip = f"{action} {volume}手 @ {float(price):.2f}"
                if raw_suffix:
                    _tooltip += raw_suffix
                if action == '开多':
                    markers.append({
                        'time': ts, 'position': 'belowBar', 'color': '#4caf50',
                        'shape': 'arrowUp', 'text': '', 'size': 2, 'tooltip': _tooltip
                    })
                elif action == '平空':
                    markers.append({
                        'time': ts, 'position': 'belowBar', 'color': '#4caf50',
                        'shape': 'arrowUp', 'text': '', 'size': 2, 'tooltip': _tooltip
                    })
                elif action == '平空开多':
                    markers.append({
                        'time': ts, 'position': 'belowBar', 'color': '#00bcd4',
                        'shape': 'circle', 'text': '', 'size': 2, 'tooltip': _tooltip
                    })
                elif action == '开空':
                    markers.append({
                        'time': ts, 'position': 'aboveBar', 'color': '#f44336',
                        'shape': 'arrowDown', 'text': '', 'size': 2, 'tooltip': _tooltip
                    })
                elif action == '平多':
                    markers.append({
                        'time': ts, 'position': 'aboveBar', 'color': '#f44336',
                        'shape': 'arrowDown', 'text': '', 'size': 2, 'tooltip': _tooltip
                    })
                elif action == '平多开空':
                    markers.append({
                        'time': ts, 'position': 'aboveBar', 'color': '#ff9800',
                        'shape': 'circle', 'text': '', 'size': 2, 'tooltip': _tooltip
                    })

            # reverse_pos 拆成两腿的合并处理
            n_tr = len(trades)
            paired_leg_indices = set()
            if n_tr > 0:
                order_by_time = sorted(
                    range(n_tr),
                    key=lambda i: (pd.to_datetime(trades[i].get('datetime'), errors='coerce'), i),
                )
                k = 0
                while k < len(order_by_time) - 1:
                    ia = order_by_time[k]
                    ib = order_by_time[k + 1]
                    ta, tb = trades[ia], trades[ib]
                    a1 = str(ta.get('action', '') or '').strip()
                    a2 = str(tb.get('action', '') or '').strip()
                    t1 = self._dt_to_lwc_ts(ta.get('datetime'))
                    t2 = self._dt_to_lwc_ts(tb.get('datetime'))
                    if t1 != t2:
                        k += 1
                        continue
                    p1 = float(ta.get('price', 0) or 0)
                    p2 = float(tb.get('price', 0) or 0)
                    px = (p1 + p2) / 2 if p1 and p2 else (p1 or p2)
                    rp1 = float(ta.get('raw_price', p1) or p1)
                    rp2 = float(tb.get('raw_price', p2) or p2)
                    raw_px = (rp1 + rp2) / 2 if rp1 and rp2 else (rp1 or rp2)
                    try:
                        _tick_half = 0.5 * float(self.price_tick) if hasattr(self, 'price_tick') else 0.0
                        _show_raw_pair = abs(raw_px - px) > _tick_half
                    except Exception:
                        _show_raw_pair = False
                    _raw_suffix_pair = f" (实际@{raw_px:.2f})" if _show_raw_pair else ""
                    vol = int(ta.get('volume', 0) or 0) or int(tb.get('volume', 0) or 0) or 1
                    if a1 == '平多' and a2 == '开空':
                        paired_leg_indices.add(ia)
                        paired_leg_indices.add(ib)
                        _tooltip = f"平多开空 {vol}手 @ {px:.2f}{_raw_suffix_pair}"
                        markers.append({
                            'time': t1, 'position': 'aboveBar', 'color': '#ff9800',
                            'shape': 'circle', 'text': '', 'size': 2, 'tooltip': _tooltip
                        })
                        k += 2
                        continue
                    if a1 == '平空' and a2 == '开多':
                        paired_leg_indices.add(ia)
                        paired_leg_indices.add(ib)
                        _tooltip = f"平空开多 {vol}手 @ {px:.2f}{_raw_suffix_pair}"
                        markers.append({
                            'time': t1, 'position': 'belowBar', 'color': '#00bcd4',
                            'shape': 'circle', 'text': '', 'size': 2, 'tooltip': _tooltip
                        })
                        k += 2
                        continue
                    k += 1

            for i, trade in enumerate(trades):
                if i in paired_leg_indices:
                    continue
                ts = _align_marker_time(self._dt_to_lwc_ts(trade.get('datetime')))
                price = trade.get('price', 0)
                raw_price = trade.get('raw_price', price)
                try:
                    _show_raw = abs(float(raw_price) - float(price)) > 0.5 * float(self.price_tick) if hasattr(self, 'price_tick') else abs(float(raw_price) - float(price)) > 0.0
                except Exception:
                    _show_raw = False
                _raw_suffix = f" (实际@{float(raw_price):.2f})" if _show_raw else ""
                action = str(trade.get('action', '') or '').strip()
                volume = trade.get('volume', 1)
                _add_marker(ts, action, price, volume, _raw_suffix)

            name = f"{result.get('symbol', '')} {kline_period}"

            kline_sources.append({
                'name': name,
                'key': key,
                'is_tick': is_tick,
                'data': chart_data,
                'markers': markers,
            })

        return kline_sources

    def _generate_source_comparison(self, results: Dict) -> str:
        """生成数据源对比表格"""
        if len(results) <= 1:
            return ''

        rows = []
        headers = ['数据源', '初始资金', '期末权益', '总收益率', '手续费', '滑点', '交易次数', '胜率', '最大回撤', '夏普比率']

        # 用于计算综合绩效的累加变量
        total_initial = 0
        total_final = 0
        total_trades = 0
        total_win_trades = 0
        total_commission_all = 0
        total_slippage_all = 0
        max_drawdown_all = 0
        all_sharpe = []

        for key, result in results.items():
            symbol = result.get('symbol', '')
            period = result.get('kline_period', '')
            name = f"{symbol} {period}"

            initial = result.get('initial_capital', 100000)
            final = result.get('final_equity', initial)
            total_return = (final - initial) / initial * 100 if initial > 0 else 0
            trades = result.get('total_trades', 0)
            win_trades = result.get('win_trades', 0)
            win_rate = result.get('win_rate', 0) * 100 if result.get('win_rate', 0) <= 1 else result.get('win_rate', 0)
            max_dd = result.get('max_drawdown_pct', 0)
            sharpe = result.get('sharpe_ratio', 0)
            commission = result.get('total_commission', 0)
            slippage = result.get('total_slippage', 0)

            # 累加综合数据
            total_initial += initial
            total_final += final
            total_trades += trades
            total_win_trades += win_trades
            total_commission_all += commission
            total_slippage_all += slippage
            if sharpe:
                all_sharpe.append((sharpe, initial))

            return_class = 'profit' if total_return > 0 else 'loss' if total_return < 0 else ''

            row = f'''
            <tr>
                <td>{name}</td>
                <td>{initial:,.0f}</td>
                <td>{final:,.0f}</td>
                <td class="{return_class}">{total_return:+.2f}%</td>
                <td>{commission:,.2f}</td>
                <td>{slippage:,.2f}</td>
                <td>{trades}</td>
                <td>{win_rate:.1f}%</td>
                <td class="loss">-{max_dd:.2f}%</td>
                <td>{sharpe:.2f}</td>
            </tr>'''
            rows.append(row)

        # 基于综合权益曲线计算综合最大回撤（而非单品种最大值）
        combined_equity = self._get_combined_equity_curve(results)
        if not combined_equity.empty and combined_equity.max() > 0:
            combined_equity = combined_equity.clip(lower=0.01)
            cummax = combined_equity.cummax()
            drawdown = cummax - combined_equity
            max_drawdown_all = (drawdown / cummax).max() * 100
        else:
            max_drawdown_all = 0

        # 计算综合绩效
        combined_return = (total_final - total_initial) / total_initial * 100 if total_initial > 0 else 0
        combined_win_rate = total_win_trades / total_trades * 100 if total_trades > 0 else 0
        combined_sharpe = sum(v * w for v, w in all_sharpe) / sum(w for _, w in all_sharpe) if all_sharpe else 0
        combined_return_class = 'profit' if combined_return > 0 else 'loss' if combined_return < 0 else ''

        # 添加综合绩效行
        combined_row = f'''
            <tr style="background: rgba(100, 181, 246, 0.15); font-weight: 600;">
                <td>📊 综合绩效</td>
                <td>{total_initial:,.0f}</td>
                <td>{total_final:,.0f}</td>
                <td class="{combined_return_class}">{combined_return:+.2f}%</td>
                <td>{total_commission_all:,.2f}</td>
                <td>{total_slippage_all:,.2f}</td>
                <td>{total_trades}</td>
                <td>{combined_win_rate:.1f}%</td>
                <td class="loss">-{max_drawdown_all:.2f}%</td>
                <td>{combined_sharpe:.2f}</td>
            </tr>'''
        rows.append(combined_row)

        header_html = ''.join([f'<th>{h}</th>' for h in headers])

        return f'''
        <div class="summary-section">
            <div class="summary-title">
                <span>📋</span> 数据源绩效对比
            </div>
            <table class="comparison-table">
                <thead><tr>{header_html}</tr></thead>
                <tbody>{''.join(rows)}</tbody>
            </table>
        </div>'''

    def _generate_source_tabs(self, source_infos: List[Dict]) -> str:
        """生成数据源标签页"""
        if len(source_infos) <= 1:
            return ''

        tabs = []
        # 汇总标签默认激活
        tabs.append(f'<div class="tab active" onclick="switchTab(\'combined\')">📊 汇总</div>')
        for info in source_infos:
            name = f"{info['symbol']} {info['kline_period']}"
            tabs.append(f'<div class="tab" onclick="switchTab(\'{info["key"]}\')">{name}</div>')

        return f'''
        <div class="summary-section">
            <div class="summary-title">
                <span>📂</span> 各数据源详情
            </div>
            <div class="tabs">
                {''.join(tabs)}
            </div>
        </div>'''

    def _generate_source_details(self, source_infos: List[Dict], combined_metrics: Dict = None) -> str:
        """生成各数据源的详细内容（含汇总页）"""
        details = []
        has_combined = len(source_infos) > 1 and combined_metrics is not None

        # 生成汇总页
        if has_combined:
            all_trades = []
            for info in source_infos:
                symbol = info['symbol']
                period = info['kline_period']
                for trade in info['result'].get('trades', []):
                    trade_copy = dict(trade)
                    trade_copy['_source_symbol'] = symbol
                    trade_copy['_source_period'] = period
                    all_trades.append(trade_copy)
            all_trades.sort(key=lambda t: t.get('datetime', ''))

            metrics_cards = self._generate_metrics_cards(combined_metrics)
            trades_rows = self._generate_combined_trades_rows(all_trades)

            combined_html = f'''
            <div id="content-combined" class="tab-content active">
                <div class="chart-container">
                    <div class="chart-title">
                        <span class="icon">📊</span>
                        📊 综合绩效指标
                    </div>
                    <div class="metrics-grid">
                        {metrics_cards}
                    </div>
                </div>

                <div class="chart-container">
                    <div class="chart-title">
                        <span class="icon">📋</span>
                        交易记录汇总 (<span class="trades-count-combined">{len(all_trades)}</span>笔)
                    </div>

                    <!-- 筛选器 -->
                    <div class="trades-filter">
                        <div class="filter-group">
                            <label>时间:</label>
                            <input type="text" class="filter-time-combined" placeholder="如: 2025-01-02">
                        </div>
                        <div class="filter-group">
                            <label>价格:</label>
                            <input type="text" class="filter-price-combined" placeholder="如: 3300">
                        </div>
                        <div class="filter-group">
                            <label>操作:</label>
                            <select class="filter-action-combined">
                                <option value="">全部</option>
                                <option value="开多">开多</option>
                                <option value="平多">平多</option>
                                <option value="开空">开空</option>
                                <option value="平空">平空</option>
                                <option value="平多开空">平多开空</option>
                                <option value="平空开多">平空开多</option>
                            </select>
                        </div>
                        <div class="filter-group">
                            <label>盈亏:</label>
                            <select class="filter-profit-combined">
                                <option value="">全部</option>
                                <option value="profit">盈利</option>
                                <option value="loss">亏损</option>
                            </select>
                        </div>
                        <button class="filter-btn" onclick="applyTradesFilter('combined')">筛选</button>
                        <button class="filter-btn reset" onclick="resetTradesFilter('combined')">重置</button>
                    </div>

                    <div class="table-wrapper">
                        <table class="trades-table" id="trades-table-combined">
                            <thead>
                                <tr>
                                    <th>#</th>
                                    <th>时间</th>
                                    <th>数据源</th>
                                    <th>操作</th>
                                    <th>价格</th>
                                    <th>数量</th>
                                    <th>盈亏</th>
                                    <th>手续费</th>
                                    <th>净盈亏</th>
                                </tr>
                            </thead>
                            <tbody id="trades-tbody-combined">
                                {trades_rows}
                            </tbody>
                        </table>
                    </div>

                    <!-- 分页器 -->
                    <div class="pagination" id="pagination-combined">
                        <button onclick="goToPage('combined', 1)">首页</button>
                        <button onclick="prevPage('combined')">上一页</button>
                        <span class="page-info">第 <span class="current-page-combined">1</span> / <span class="total-pages-combined">1</span> 页</span>
                        <button onclick="nextPage('combined')">下一页</button>
                        <button onclick="goToPage('combined', getTotalPages('combined'))">末页</button>
                        <div class="page-jump">
                            <input type="number" class="page-input-combined" min="1" placeholder="页码">
                            <button onclick="jumpToPage('combined')">跳转</button>
                        </div>
                    </div>
                </div>
            </div>'''
            details.append(combined_html)

        for i, info in enumerate(source_infos):
            active = 'active' if (not has_combined and i == 0) else ''
            result = info['result']

            # 生成该数据源的指标卡片
            source_metrics = self._extract_source_metrics(result)
            metrics_cards = self._generate_metrics_cards(source_metrics)

            # 生成该数据源的交易记录
            trades = result.get('trades', [])
            trades_rows = self._generate_trades_rows(trades, info['symbol'])

            detail_html = f'''
            <div id="content-{info['key']}" class="tab-content {active}">
                <div class="chart-container">
                    <div class="chart-title">
                        <span class="icon">📊</span>
                        {info['symbol']} {info['kline_period']} 绩效指标
                    </div>
                    <div class="metrics-grid">
                        {metrics_cards}
                    </div>
                </div>

                <div class="chart-container">
                    <div class="chart-title">
                        <span class="icon">📋</span>
                        交易记录 (<span class="trades-count-{i}">{len(trades)}</span>笔)
                    </div>

                    <!-- 筛选器 -->
                    <div class="trades-filter">
                        <div class="filter-group">
                            <label>时间:</label>
                            <input type="text" class="filter-time-{i}" placeholder="如: 2025-01-02">
                        </div>
                        <div class="filter-group">
                            <label>价格:</label>
                            <input type="text" class="filter-price-{i}" placeholder="如: 3300">
                        </div>
                        <div class="filter-group">
                            <label>操作:</label>
                            <select class="filter-action-{i}">
                                <option value="">全部</option>
                                <option value="开多">开多</option>
                                <option value="平多">平多</option>
                                <option value="开空">开空</option>
                                <option value="平空">平空</option>
                                <option value="平多开空">平多开空</option>
                                <option value="平空开多">平空开多</option>
                            </select>
                        </div>
                        <div class="filter-group">
                            <label>盈亏:</label>
                            <select class="filter-profit-{i}">
                                <option value="">全部</option>
                                <option value="profit">盈利</option>
                                <option value="loss">亏损</option>
                            </select>
                        </div>
                        <button class="filter-btn" onclick="applyTradesFilter({i})">筛选</button>
                        <button class="filter-btn reset" onclick="resetTradesFilter({i})">重置</button>
                    </div>

                    <div class="table-wrapper">
                        <table class="trades-table" id="trades-table-{i}">
                            <thead>
                                <tr>
                                    <th>#</th>
                                    <th>时间</th>
                                    <th>操作</th>
                                    <th>价格</th>
                                    <th>数量</th>
                                    <th>盈亏</th>
                                    <th>手续费</th>
                                    <th>净盈亏</th>
                                </tr>
                            </thead>
                            <tbody id="trades-tbody-{i}">
                                {trades_rows}
                            </tbody>
                        </table>
                    </div>

                    <!-- 分页器 -->
                    <div class="pagination" id="pagination-{i}">
                        <button onclick="goToPage({i}, 1)">首页</button>
                        <button onclick="prevPage({i})">上一页</button>
                        <span class="page-info">第 <span class="current-page-{i}">1</span> / <span class="total-pages-{i}">1</span> 页</span>
                        <button onclick="nextPage({i})">下一页</button>
                        <button onclick="goToPage({i}, getTotalPages({i}))">末页</button>
                        <div class="page-jump">
                            <input type="number" class="page-input-{i}" min="1" placeholder="页码">
                            <button onclick="jumpToPage({i})">跳转</button>
                        </div>
                    </div>
                </div>
            </div>'''
            details.append(detail_html)

        return '\n'.join(details)

    def _extract_source_metrics(self, result: Dict) -> Dict:
        """提取单个数据源的指标"""
        initial = result.get('initial_capital', 100000)
        final = result.get('final_equity', initial)
        total_return = (final - initial) / initial * 100 if initial > 0 else 0

        return {
            'initial_capital': initial,
            'final_equity': final,
            'total_return': total_return,
            'total_net_profit': result.get('total_net_profit', 0),
            'total_trades': result.get('total_trades', 0),
            'win_rate': result.get('win_rate', 0) * 100 if result.get('win_rate', 0) <= 1 else result.get('win_rate', 0),
            'max_drawdown_pct': result.get('max_drawdown_pct', 0),
            'annual_return': result.get('annual_return', 0),
            'sharpe_ratio': result.get('sharpe_ratio', 0),
            'profit_factor': result.get('profit_factor', 0),
            'total_commission': result.get('total_commission', 0),
            'total_slippage': result.get('total_slippage', 0),
            'total_amount_profit': result.get('total_amount_profit', 0),
        }

    def _generate_metrics_cards(self, metrics: Dict) -> str:
        """生成指标卡片 HTML"""
        cards = []

        metric_configs = [
            ('initial_capital', '初始资金', ',.0f', 'neutral'),
            ('final_equity', '期末权益', ',.0f', None),
            ('total_return', '总收益率', '+.2f', None, '%'),
            ('total_amount_profit', '交易盈亏(未扣手续费)', ',.2f', None),
            ('total_commission', '总手续费', ',.2f', 'neutral'),
            ('total_slippage', '总滑点成本', ',.2f', 'neutral'),
            ('total_net_profit', '净利润(扣除手续费)', ',.2f', None),
            ('total_trades', '总交易次数', 'd', 'neutral'),
            ('win_rate', '胜率', '.2f', None, '%'),
            ('max_drawdown_pct', '最大回撤', '.2f', 'negative', '%'),
            ('annual_return', '年化收益率', '+.2f', None, '%'),
            ('sharpe_ratio', '夏普比率', '.2f', None),
            ('profit_factor', '盈亏比', '.2f', None),
        ]

        for config in metric_configs:
            key = config[0]
            label = config[1]
            fmt = config[2]
            force_class = config[3] if len(config) > 3 else None
            suffix = config[4] if len(config) > 4 else ''

            value = metrics.get(key, 0)

            try:
                if 'd' in fmt:
                    formatted_value = f"{int(value):,}"
                else:
                    formatted_value = f"{value:{fmt}}"
            except:
                formatted_value = str(value)

            formatted_value += suffix

            if force_class:
                value_class = force_class
            elif key in ['total_return', 'annual_return', 'total_net_profit', 'total_amount_profit']:
                value_class = 'positive' if value > 0 else 'negative' if value < 0 else 'neutral'
            elif key == 'win_rate':
                value_class = 'positive' if value >= 50 else 'negative'
            elif key == 'sharpe_ratio':
                value_class = 'positive' if value > 1 else 'neutral' if value > 0 else 'negative'
            elif key == 'profit_factor':
                value_class = 'positive' if value > 1 else 'negative'
            else:
                value_class = 'neutral'

            card_html = f'''
            <div class="metric-card">
                <div class="label">{label}</div>
                <div class="value {value_class}">{formatted_value}</div>
            </div>'''
            cards.append(card_html)

        return '\n'.join(cards)

    def _generate_trades_rows(self, trades: List[Dict], symbol: str = '') -> str:
        """生成交易记录表格行"""
        rows = []

        for i, trade in enumerate(trades, 1):
            datetime_str = str(trade.get('datetime', ''))
            action = trade.get('action', '')
            price = trade.get('price', 0)
            # v0.4.6：raw_price 与 price 不同时在表格里同时显示，便于用户对账
            raw_price = trade.get('raw_price', price)
            try:
                _show_raw = abs(float(raw_price) - float(price)) > 1e-6
            except Exception:
                _show_raw = False
            price_cell = f"{price:,.2f}" + (f" <span style=\"color:#999;font-size:0.85em\">(实际{float(raw_price):,.2f})</span>" if _show_raw else "")
            volume = trade.get('volume', 1)

            amount_profit = trade.get('amount_profit', 0)
            commission = trade.get('commission', 0)
            net_profit = trade.get('net_profit', 0)

            if action in ['开多', '平空', '平空开多']:
                tag_class = 'buy'
            else:
                tag_class = 'sell'

            if action in ['平多', '平空', '平多开空', '平空开多']:
                profit_class = 'profit' if net_profit > 0 else 'loss'
                profit_str = f"{amount_profit:+,.2f}"
                net_profit_str = f"{net_profit:+,.2f}"
            else:
                profit_class = ''
                profit_str = '-'
                net_profit_str = '-'

            row_html = f'''
            <tr>
                <td>{i}</td>
                <td>{datetime_str}</td>
                <td><span class="tag {tag_class}">{action}</span></td>
                <td>{price_cell}</td>
                <td>{volume}</td>
                <td class="{profit_class}">{profit_str}</td>
                <td>{commission:,.2f}</td>
                <td class="{profit_class}">{net_profit_str}</td>
            </tr>'''
            rows.append(row_html)

        return '\n'.join(rows)

    def _generate_combined_trades_rows(self, trades: List[Dict]) -> str:
        """生成汇总交易记录表格行（带数据源标识）"""
        rows = []

        for i, trade in enumerate(trades, 1):
            datetime_str = str(trade.get('datetime', ''))
            action = trade.get('action', '')
            price = trade.get('price', 0)
            raw_price = trade.get('raw_price', price)
            try:
                _show_raw = abs(float(raw_price) - float(price)) > 1e-6
            except Exception:
                _show_raw = False
            price_cell = f"{price:,.2f}" + (f" <span style=\"color:#999;font-size:0.85em\">(实际{float(raw_price):,.2f})</span>" if _show_raw else "")
            volume = trade.get('volume', 1)

            amount_profit = trade.get('amount_profit', 0)
            commission = trade.get('commission', 0)
            net_profit = trade.get('net_profit', 0)

            if action in ['开多', '平空', '平空开多']:
                tag_class = 'buy'
            else:
                tag_class = 'sell'

            if action in ['平多', '平空', '平多开空', '平空开多']:
                profit_class = 'profit' if net_profit > 0 else 'loss'
                profit_str = f"{amount_profit:+,.2f}"
                net_profit_str = f"{net_profit:+,.2f}"
            else:
                profit_class = ''
                profit_str = '-'
                net_profit_str = '-'

            source_name = f"{trade.get('_source_symbol', '')} {trade.get('_source_period', '')}"

            row_html = f'''
            <tr>
                <td>{i}</td>
                <td>{datetime_str}</td>
                <td><span class="source-tag">{source_name}</span></td>
                <td><span class="tag {tag_class}">{action}</span></td>
                <td>{price_cell}</td>
                <td>{volume}</td>
                <td class="{profit_class}">{profit_str}</td>
                <td>{commission:,.2f}</td>
                <td class="{profit_class}">{net_profit_str}</td>
            </tr>'''
            rows.append(row_html)

        return '\n'.join(rows)


# 兼容旧接口
def generate_html_report(results: Dict, multi_data_source=None, output_dir: str = "backtest_results") -> str:
    """生成 HTML 报告的便捷函数"""
    generator = HTMLReportGenerator()
    return generator.generate_report(results, multi_data_source, output_dir)
