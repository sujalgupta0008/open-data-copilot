import os
import re
import io
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.colors import HexColor, white, black
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, PageBreak, Image, KeepTogether
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing, Line, String, Rect, Circle
from reportlab.graphics.charts.barcharts import VerticalBarChart, HorizontalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.widgets.markers import makeMarker

def _sanitize(text: str) -> str:
    if not text:
        return ""
    # Escape for reportlab Paragraph xml
    return text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def chart_spec_to_drawing(chart_spec: Dict[str,Any], width: int = 460, height: int = 220) -> Drawing:
    """
    Convert generic chart specifications (ECharts/Plotly/Vega-like) to ReportLab vector drawing.
    Supports: line, bar, horizontal bar, area, scatter, histogram, box plot, grouped/stacked bar
    """
    chart_type = (chart_spec.get("chart_type") or chart_spec.get("type") or "bar").lower()
    config = chart_spec.get("configuration") or chart_spec.get("config") or chart_spec
    data = config.get("data") or chart_spec.get("data") or []
    xKey = config.get("xKey") or chart_spec.get("xKey") or None
    yKey = config.get("yKey") or chart_spec.get("yKey") or None

    d = Drawing(width, height)
    # Title background
    d.add(Rect(0, height-20, width, 20, fillColor=HexColor('#f1f5f9'), strokeColor=HexColor('#e2e8f0')))

    title = chart_spec.get("title") or chart_spec.get("name") or config.get("title") or f"{chart_type.title()} Chart"
    d.add(String(width/2, height-14, _sanitize(title[:60]), textAnchor="middle", fontSize=8, fontName="Helvetica-Bold", fillColor=HexColor('#0f172a')))

    chart_width = width - 40
    chart_height = height - 60
    chart_x = 30
    chart_y = 30

    # Normalize data
    if not data or not isinstance(data, list):
        d.add(String(width/2, height/2, "No data available", textAnchor="middle", fontSize=9, fillColor=HexColor('#64748b')))
        return d

    # Limit to 12 points for readability
    sample = data[:12]
    # Extract labels and values
    labels = []
    values = []
    grouped = False
    grouped_keys = []
    # Detect grouped/stacked: data has multiple y keys or chart_spec indicates stacked
    if chart_type in ["grouped_bar", "stacked_bar", "grouped", "stacked"]:
        grouped = True
        # Assume yKeys list
        yKeys = config.get("yKeys") or config.get("yKey") or []
        if isinstance(yKeys, str):
            yKeys = [yKeys]
        if not yKeys and sample and isinstance(sample[0], dict):
            # Infer numeric keys excluding xKey
            yKeys = [k for k in sample[0].keys() if k != xKey][:3]
        grouped_keys = yKeys[:3] if yKeys else ["value1","value2"]
        labels = [str(r.get(xKey, f"Item {i}"))[:12] for i, r in enumerate(sample)]
        # Build grouped values: list per group
        grouped_values = []
        for gk in grouped_keys:
            gv = []
            for r in sample:
                v = r.get(gk)
                try:
                    gv.append(float(v) if v is not None else 0)
                except:
                    gv.append(0)
            grouped_values.append(gv)
        # Render grouped bar via VerticalBarChart
        try:
            bc = VerticalBarChart()
            bc.x = chart_x
            bc.y = chart_y
            bc.width = chart_width
            bc.height = chart_height
            bc.data = grouped_values
            bc.categoryAxis.categoryNames = labels
            bc.categoryAxis.labels.dx = 0
            bc.categoryAxis.labels.dy = -12
            bc.categoryAxis.labels.angle = 20
            bc.categoryAxis.labels.fontSize = 6
            bc.valueAxis.valueMin = 0
            bc.valueAxis.labels.fontSize = 6
            bc.barLabels.fontSize = 5
            bc.bars[0].fillColor = HexColor('#6d6af0')
            if len(bc.bars) >1:
                bc.bars[1].fillColor = HexColor('#06b6d4')
            if len(bc.bars) >2:
                bc.bars[2].fillColor = HexColor('#f59e0b')
            d.add(bc)
            # Legend
            for idx, gk in enumerate(grouped_keys):
                col = [HexColor('#6d6af0'), HexColor('#06b6d4'), HexColor('#f59e0b')][idx %3]
                d.add(Rect(width-110+ idx*35, height-32, 8, 8, fillColor=col, strokeColor=col))
                d.add(String(width-100+ idx*35, height-30, gk[:10], fontSize=6, fillColor=HexColor('#334155')))
            return d
        except Exception as e:
            pass
        # Fallback to simple
        chart_type = "bar"

    # Standard single series
    if xKey and yKey:
        labels = [str(r.get(xKey, ""))[:12] for r in sample]
        for r in sample:
            v = r.get(yKey)
            try:
                values.append(float(v) if v is not None else 0)
            except:
                values.append(0)
    else:
        # Generic: if data is list of dicts with values, take first keys
        if sample and isinstance(sample[0], dict):
            keys = list(sample[0].keys())
            xKey = keys[0]
            yKey = keys[1] if len(keys)>1 else keys[0]
            labels = [str(r.get(xKey, ""))[:12] for r in sample]
            for r in sample:
                v = r.get(yKey)
                try:
                    values.append(float(v) if v is not None else 0)
                except:
                    values.append(0)
        elif sample and isinstance(sample[0], (list, tuple)):
            labels = [str(i) for i,_ in enumerate(sample)]
            values = [float(v) if isinstance(v,(int,float)) else 0 for v in sample]
        else:
            d.add(String(width/2, height/2, "Invalid chart data format", textAnchor="middle", fontSize=8, fillColor=HexColor('#64748b')))
            return d

    if not values:
        d.add(String(width/2, height/2, "Empty series", textAnchor="middle", fontSize=8))
        return d

    # Clamp values for display
    max_v = max(values) if values else 1
    min_v = min(values) if values else 0
    # Ensure some range
    if max_v == min_v:
        max_v = min_v + 1

    # Choose rendering based on chart_type
    try:
        if chart_type in ["bar", "histogram"]:
            bc = VerticalBarChart()
            bc.x = chart_x
            bc.y = chart_y
            bc.width = chart_width
            bc.height = chart_height
            bc.data = [values]
            bc.categoryAxis.categoryNames = labels
            bc.categoryAxis.labels.dx = 0
            bc.categoryAxis.labels.dy = -15
            bc.categoryAxis.labels.angle = 25
            bc.categoryAxis.labels.fontSize = 6
            bc.valueAxis.valueMin = min(0, min_v)
            bc.valueAxis.valueMax = max_v * 1.1
            bc.valueAxis.labels.fontSize = 6
            bc.bars[0].fillColor = HexColor('#6d6af0')
            bc.barLabels.fontSize = 5
            d.add(bc)
        elif chart_type in ["horizontal_bar", "hbar"]:
            bc = HorizontalBarChart()
            bc.x = chart_x
            bc.y = chart_y
            bc.width = chart_width
            bc.height = chart_height
            bc.data = [values]
            bc.categoryAxis.categoryNames = labels
            bc.categoryAxis.labels.fontSize = 6
            bc.valueAxis.valueMin = min(0, min_v)
            bc.valueAxis.valueMax = max_v * 1.1
            bc.valueAxis.labels.fontSize = 6
            bc.bars[0].fillColor = HexColor('#06b6d4')
            d.add(bc)
        elif chart_type in ["line", "area"]:
            lp = LinePlot()
            lp.x = chart_x
            lp.y = chart_y
            lp.width = chart_width
            lp.height = chart_height
            lp.data = [list(enumerate(values))]
            lp.lines[0].strokeColor = HexColor('#6d6af0')
            lp.lines[0].strokeWidth = 2
            if chart_type == "area":
                # Simulate fill by adding polygon under line (simplified)
                from reportlab.graphics.shapes import Polygon
                pts = []
                for i, v in enumerate(values):
                    x = chart_x + (i/(len(values)-1 if len(values)>1 else 1))*chart_width
                    y = chart_y + (v - min_v)/(max_v-min_v if max_v!=min_v else 1)*chart_height
                    pts.extend([x,y])
                # Add baseline closing
                pts.extend([chart_x+chart_width, chart_y, chart_x, chart_y])
                # Use transparent fill
                poly = Polygon(pts, fillColor=HexColor('#e0e7ff'), strokeColor=None)
                # Add before line
                d.add(poly)
                d.add(lp)
            else:
                d.add(lp)
            # X labels
            for i, lab in enumerate(labels):
                x = chart_x + (i/(len(labels)-1 if len(labels)>1 else 1))*chart_width
                d.add(String(x, chart_y-12, lab, textAnchor="middle", fontSize=6, fillColor=HexColor('#64748b')))
            # Y axis labels
            for idx, val in enumerate([min_v, (min_v+max_v)/2, max_v]):
                y = chart_y + (idx/2)*chart_height
                d.add(String(chart_x-5, y, str(round(val,1)), textAnchor="end", fontSize=6, fillColor=HexColor('#64748b')))
        elif chart_type in ["scatter"]:
            # Simple scatter: x vs y
            d.add(String(chart_x, chart_y+chart_height+6, "Scatter: "+yKey+" vs "+xKey, fontSize=7, fillColor=HexColor('#475569')))
            # Normalize both axes if data had x numeric? Use values as y, index as x
            for i, v in enumerate(values):
                x = chart_x + (i/(len(values)-1 if len(values)>1 else 1))*chart_width
                y = chart_y + (v - min_v)/(max_v-min_v if max_v!=min_v else 1)*chart_height
                d.add(Circle(x, y, 4, fillColor=HexColor('#6d6af0'), strokeColor=white))
            # Axes
            d.add(Line(chart_x, chart_y, chart_x+chart_width, chart_y, strokeColor=HexColor('#cbd5e1')))
            d.add(Line(chart_x, chart_y, chart_x, chart_y+chart_height, strokeColor=HexColor('#cbd5e1')))
            for lab in labels[::max(1, len(labels)//4)]:
                idx = labels.index(lab)
                x = chart_x + (idx/(len(labels)-1 if len(labels)>1 else 1))*chart_width
                d.add(String(x, chart_y-12, lab, textAnchor="middle", fontSize=5))
        elif chart_type == "box_plot":
            # Simplified box plot: show median, quartiles for values distribution
            try:
                import numpy as np
                vals = np.array(values, dtype=float)
                q1, median, q3 = np.percentile(vals, [25,50,75])
                vmin, vmax = float(np.min(vals)), float(np.max(vals))
                # Draw box
                box_x = chart_x + chart_width*0.3
                box_w = chart_width*0.4
                # Scale y to value
                def y_for(val):
                    return chart_y + (val - min_v)/(max_v-min_v)*chart_height
                # Box rect from q1 to q3
                y_q1, y_q3 = y_for(q1), y_for(q3)
                y_med = y_for(median)
                y_min, y_max = y_for(vmin), y_for(vmax)
                # Box
                d.add(Rect(box_x, min(y_q1,y_q3), box_w, abs(y_q3-y_q1), fillColor=HexColor('#e0e7ff'), strokeColor=HexColor('#6d6af0')))
                # Median line
                d.add(Line(box_x, y_med, box_x+box_w, y_med, strokeColor=HexColor('#dc2626'), strokeWidth=2))
                # Whiskers
                d.add(Line(box_x+box_w/2, y_min, box_x+box_w/2, y_q1, strokeColor=HexColor('#64748b')))
                d.add(Line(box_x+box_w/2, y_q3, box_x+box_w/2, y_max, strokeColor=HexColor('#64748b')))
                d.add(Line(box_x+box_w*0.25, y_min, box_x+box_w*0.75, y_min, strokeColor=HexColor('#64748b')))
                d.add(Line(box_x+box_w*0.25, y_max, box_x+box_w*0.75, y_max, strokeColor=HexColor('#64748b')))
                # Labels
                d.add(String(box_x+box_w+6, y_med, f"Median {median:.1f}", fontSize=6, fillColor=HexColor('#334155')))
                d.add(String(chart_x, chart_y+chart_height+2, "Box Plot: "+yKey, fontSize=7, fillColor=HexColor('#475569')))
            except Exception as e:
                # fallback to bar
                bc = VerticalBarChart()
                bc.x = chart_x
                bc.y = chart_y
                bc.width = chart_width
                bc.height = chart_height
                bc.data = [values]
                bc.categoryAxis.categoryNames = labels
                bc.categoryAxis.labels.fontSize = 6
                bc.bars[0].fillColor = HexColor('#6d6af0')
                d.add(bc)
        else:
            # Fallback generic bar
            bc = VerticalBarChart()
            bc.x = chart_x
            bc.y = chart_y
            bc.width = chart_width
            bc.height = chart_height
            bc.data = [values]
            bc.categoryAxis.categoryNames = labels
            bc.categoryAxis.labels.fontSize = 6
            bc.bars[0].fillColor = HexColor('#6d6af0')
            d.add(bc)
    except Exception as e:
        d.add(String(width/2, height/2, f"Chart render error: {str(e)[:40]}", textAnchor="middle", fontSize=6, fillColor=HexColor('#dc2626')))

    # Axis frame
    d.add(Rect(chart_x, chart_y, chart_width, chart_height, fillColor=None, strokeColor=HexColor('#e2e8f0')))

    return d

def interpret_chart(chart_spec: Dict[str,Any]) -> str:
    data = chart_spec.get("configuration", {}).get("data") or chart_spec.get("data") or []
    title = chart_spec.get("title") or chart_spec.get("configuration", {}).get("title") or "Chart"
    chart_type = chart_spec.get("chart_type") or chart_spec.get("type") or "bar"
    if not data:
        return f"{title} shows no data. No evidence for inference."
    try:
        # Simple interpretation: peak, trough, trend
        if isinstance(data, list) and data and isinstance(data[0], dict):
            cfg = chart_spec.get("configuration", {})
            xKey = cfg.get("xKey")
            yKey = cfg.get("yKey")
            if xKey and yKey and all(xKey in r and yKey in r for r in data[:3]):
                vals = [(r[xKey], float(r[yKey])) for r in data if r.get(yKey) is not None]
                if vals:
                    max_item = max(vals, key=lambda x: x[1])
                    min_item = min(vals, key=lambda x: x[1])
                    return f"{title}: highest is {max_item[0]} ({max_item[1]:.2f}), lowest is {min_item[0]} ({min_item[1]:.2f}) across {len(vals)} points. Evidence from DuckDB execution; association not causation."
        return f"{title} displays {len(data)} records as {chart_type}. Review evidence table for exact values and provenance."
    except Exception:
        return f"{title}: {len(data)} records visualized as {chart_type}."

def build_single_report_story(report, dataset, content: Dict[str,Any], charts: List[Dict[str,Any]] = None) -> List[Any]:
    """
    Build ReportLab story for single report with dynamic structure:
    Title, Executive Summary, Business Question, Dataset Overview, Data Quality, Methodology, Key Findings, Charts+Interpretations, Statistical Validation, Drivers, Risks/Limitations, Recommendations, Evidence/Provenance, Question Coverage.
    """
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title2', parent=styles['Title'], fontSize=18, leading=22, textColor=HexColor('#0b0d18'), alignment=TA_LEFT, spaceAfter=6)
    h1 = ParagraphStyle('H1', parent=styles['Heading1'], fontSize=13, leading=16, textColor=HexColor('#0b0d18'), spaceBefore=12, spaceAfter=6)
    h2 = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=11, leading=14, textColor=HexColor('#1e293b'), spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle('Body', parent=styles['Normal'], fontSize=9, leading=13, textColor=HexColor('#334155'))
    small = ParagraphStyle('Small', parent=body, fontSize=8, leading=11, textColor=HexColor('#64748b'))
    bullet_style = ParagraphStyle('Bullet', parent=body, fontSize=9, leading=12, leftIndent=12, bulletIndent=0, spaceBefore=2, spaceAfter=2)

    story = []
    # Header brand
    story.append(Paragraph(f"Open Data Copilot — Report", ParagraphStyle('Brand', parent=body, fontSize=9, leading=11, textColor=HexColor('#6d6af0'), fontName='Helvetica-Bold')))
    story.append(Paragraph(_sanitize(report.title), title_style))
    ov = content.get('dataset_overview',{})
    dq = content.get('data_quality',{})
    story.append(Paragraph(f"Dataset: <b>{_sanitize(ov.get('name', getattr(dataset,'name','')))}</b> &nbsp;|&nbsp; {ov.get('rows','')} rows × {ov.get('columns','')} cols &nbsp;|&nbsp; Quality {dq.get('score','')}/100 &nbsp;|&nbsp; Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", small))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=0.7, color=HexColor('#e2e8f0')))
    story.append(Spacer(1, 6))

    # Title Section (already)
    # Executive Summary
    if content.get("executive_summary"):
        story.append(Paragraph("Executive Summary", h1))
        story.append(Paragraph(_sanitize(content.get("executive_summary","")[:1200]), body))
        story.append(Spacer(1, 4))

    # Business Question
    if content.get("business_question"):
        story.append(Paragraph("Business Question", h1))
        story.append(Paragraph(_sanitize(content.get("business_question","")), body))
        story.append(Spacer(1, 4))

    # Dataset Overview
    if content.get("dataset_overview"):
        ov = content.get("dataset_overview",{})
        story.append(Paragraph("Dataset Overview", h1))
        ov_rows = [["Dataset", _sanitize(str(ov.get("name","")))], ["Rows", str(ov.get("rows",""))], ["Columns", str(ov.get("columns",""))], ["File Type", str(ov.get("file_type",""))]]
        if ov.get("version_number"):
            ov_rows.append(["Version", f"V{ov.get('version_number')} ({str(ov.get('version_id',''))[:8]})"])
        if ov.get("created_at"):
            ov_rows.append(["Created", str(ov.get("created_at",""))[:19]])
        t_ov = Table([["Field","Value"]] + ov_rows, colWidths=[40*mm, 110*mm])
        t_ov.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), HexColor('#0b0d18')),
            ('TEXTCOLOR', (0,0), (-1,0), white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('GRID', (0,0), (-1,-1), 0.4, HexColor('#e2e8f0')),
            ('BACKGROUND', (0,1), (-1,-1), HexColor('#f8fafc')),
            ('LEFTPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))
        story.append(t_ov)
        story.append(Spacer(1, 4))

    # Data Quality
    story.append(Paragraph("Data Quality", h1))
    dq = content.get("data_quality",{})
    if isinstance(dq, dict) and dq.get("factors"):
        factors = dq["factors"]
        qdata = [[_sanitize(str(k)), _sanitize(str(v))] for k,v in factors.items()]
        t = Table([["Metric","Value"]] + qdata, colWidths=[70*mm, 80*mm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), HexColor('#0b0d18')),
            ('TEXTCOLOR', (0,0), (-1,0), white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('GRID', (0,0), (-1,-1), 0.4, HexColor('#e2e8f0')),
            ('BACKGROUND', (0,1), (-1,-1), HexColor('#f8fafc')),
            ('LEFTPADDING', (0,0), (-1,-1), 4),
            ('RIGHTPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))
        story.append(t)
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"Overall quality score: <b>{dq.get('score','')}/100</b>", body))
    else:
        story.append(Paragraph("Quality details not available; see profile insights.", small))
    story.append(Spacer(1, 4))

    # Methodology
    story.append(Paragraph("Methodology", h1))
    meth = content.get("analysis_methodology") or content.get("methodology") or "Statistical profiling via Pandas, SQL validated & executed in DuckDB; statistical validation deterministic. Charts derived from execution results."
    story.append(Paragraph(_sanitize(meth), body))
    story.append(Spacer(1, 4))

    # Key Findings
    kf = content.get("key_findings") or content.get("insights")
    if kf:
        story.append(Paragraph("Key Findings", h1))
        for ins in kf[:8]:
            if isinstance(ins, str):
                story.append(Paragraph(f"• {_sanitize(ins)}", bullet_style))
            elif isinstance(ins, dict):
                title = _sanitize(ins.get('title',''))
                desc = _sanitize(ins.get('description','')[:400])
                story.append(Paragraph(f"<b>{title}</b> — {desc}", body))
            story.append(Spacer(1, 2))
        story.append(Spacer(1, 2))

    # Charts + Interpretations + Provenance
    if charts:
        story.append(Paragraph("Charts & Interpretation", h1))
        for idx, chart in enumerate(charts, start=1):
            cht_title = chart.get("title") or chart.get("configuration",{}).get("title") or f"Chart {idx}"
            story.append(Paragraph(f"{idx}. {_sanitize(cht_title)}", h2))
            # Convert to drawing
            drawing = chart_spec_to_drawing(chart, width=470, height=240)
            story.append(drawing)
            story.append(Spacer(1, 3))
            # Short Interpretation
            interp = chart.get("interpretation") or interpret_chart(chart)
            story.append(Paragraph(f"<b>Interpretation:</b> {_sanitize(interp)}", body))
            story.append(Spacer(1, 2))
            # Provenance/Evidence Reference
            prov = chart.get("provenance") or content.get("provenance") or "Evidence: DuckDB execution result"
            ev = content.get("evidence",{})
            ev_ref = ""
            if isinstance(ev, dict) and ev.get("generated_code"):
                ev_ref = f" | SQL: {ev.get('generated_code','')[:80]}..."
            story.append(Paragraph(f"<b>Provenance:</b> {_sanitize(prov+ev_ref)} | Chart {idx} of {len(charts)}", small))
            story.append(Spacer(1, 6))
            story.append(HRFlowable(width="100%", thickness=0.3, color=HexColor('#e2e8f0')))
            story.append(Spacer(1, 4))
    else:
        # If no charts provided but content has evidence with columns, still note
        if content.get("evidence") and isinstance(content.get("evidence"), dict) and content["evidence"].get("result_columns"):
            story.append(Paragraph("Charts & Interpretation", h1))
            story.append(Paragraph("No chart configuration stored; evidence table available in Evidence/Provenance section.", small))
            story.append(Spacer(1, 4))

    # Statistical Validation
    if content.get("statistical_validation"):
        sv = content["statistical_validation"]
        story.append(Paragraph("Statistical Validation", h1))
        story.append(Paragraph(f"Method: {_sanitize(str(sv.get('method','')))} | Significance: {_sanitize(str(sv.get('significance','')))} | p={sv.get('p_value','')} | Effect: {sv.get('effect_size','')} ({_sanitize(str(sv.get('effect_size_interpretation','')))})", body))
        if sv.get("confidence_interval"):
            story.append(Paragraph(f"Confidence Interval: {_sanitize(str(sv.get('confidence_interval')))}", small))
        if sv.get("limitations"):
            story.append(Paragraph(f"Limitations: {_sanitize('; '.join([str(x) for x in sv.get('limitations',[])[:3]]))}", small))
        story.append(Spacer(1, 4))

    # Drivers
    if content.get("driver_analysis"):
        da = content["driver_analysis"]
        story.append(Paragraph("Drivers & Root Cause", h1))
        if isinstance(da, dict):
            story.append(Paragraph(_sanitize(da.get("summary","")[:600]), body))
            if da.get("method"):
                story.append(Paragraph(f"Method: {_sanitize(da.get('method',''))}", small))
            if da.get("drivers"):
                for drv in da["drivers"][:3]:
                    story.append(Paragraph(f"• {drv.get('driver_value','')} — change {drv.get('change','')} ({drv.get('contribution_pct','')}% )", bullet_style))
        else:
            story.append(Paragraph(_sanitize(str(da)[:600]), body))
        story.append(Spacer(1, 3))
    if content.get("drivers"):
        story.append(Paragraph("Drivers", h1))
        for d in content["drivers"][:3]:
            story.append(Paragraph(_sanitize(str(d)[:300]), body))
        story.append(Spacer(1, 3))

    # Risks / Limitations (also assumptions)
    story.append(Paragraph("Risks & Limitations", h1))
    al = content.get("assumptions_and_limitations") or content.get("assumptions") or content.get("limitations") or []
    if isinstance(al, list) and al:
        for lim in al[:6]:
            story.append(Paragraph(f"• {_sanitize(str(lim)[:300])}", bullet_style))
    elif isinstance(al, str):
        story.append(Paragraph(_sanitize(al[:600]), body))
    else:
        story.append(Paragraph("No explicit limitations documented; see Data Quality and Methodology.", small))
    story.append(Spacer(1, 3))

    # Recommendations
    if content.get("recommendations") or content.get("recommendation"):
        rec = content.get("recommendations") or content.get("recommendation")
        story.append(Paragraph("Recommendations", h1))
        if isinstance(rec, dict):
            story.append(Paragraph(f"<b>{_sanitize(rec.get('title',''))}</b>", body))
            story.append(Paragraph(_sanitize(rec.get('recommendation','')), body))
            if rec.get("rationale"):
                story.append(Paragraph(f"Rationale: {_sanitize(rec.get('rationale',''))}", small))
            if rec.get("supporting_evidence"):
                story.append(Paragraph(f"Evidence: {_sanitize('; '.join([str(x) for x in rec.get('supporting_evidence',[])[:3]]))}", small))
            if rec.get("limitations"):
                story.append(Paragraph(f"Limitations: {_sanitize('; '.join([str(x) for x in rec.get('limitations',[])[:2]]))}", small))
            if rec.get("requires_validation"):
                story.append(Paragraph("Requires human/business validation before operational action.", ParagraphStyle('Warn', parent=small, textColor=HexColor('#b45309'))))
        else:
            story.append(Paragraph(_sanitize(str(rec)[:600]), body))
        story.append(Spacer(1, 4))

    # Evidence / Provenance
    if content.get("evidence"):
        ev = content["evidence"]
        story.append(Paragraph("Evidence & Provenance", h1))
        if isinstance(ev, dict):
            if ev.get("generated_code"):
                story.append(Paragraph("Generated SQL (validated & executed in DuckDB)", h2))
                story.append(Paragraph(f"<font name=\"Courier\" size=\"7\">{_sanitize(ev.get('generated_code','')[:600])}</font>", ParagraphStyle('MonoSmall', parent=small, fontName='Courier', fontSize=7, leading=9, textColor=HexColor('#334155'))))
                story.append(Spacer(1, 2))
            if ev.get("result_columns"):
                story.append(Paragraph(f"Result Columns: {_sanitize(', '.join([str(c) for c in ev.get('result_columns',[])[:6]]))} | Rows: {ev.get('row_count', len(ev.get('result_rows',[])))}", small))
                story.append(Spacer(1, 2))
                if ev.get("result_rows"):
                    cols = ev.get("result_columns", [])[:4]
                    if cols:
                        header = [_sanitize(str(c)[:15]) for c in cols]
                        rows_ev = []
                        for r in ev["result_rows"][:3]:
                            rows_ev.append([_sanitize(str(r.get(c, ""))[:18]) for c in cols])
                        if rows_ev:
                            t_ev = Table([header] + rows_ev, colWidths=[ (150/len(cols))*mm ]*len(cols))
                            t_ev.setStyle(TableStyle([
                                ('BACKGROUND', (0,0), (-1,0), HexColor('#0b0d18')),
                                ('TEXTCOLOR', (0,0), (-1,0), white),
                                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                                ('FONTSIZE', (0,0), (-1,-1), 7),
                                ('GRID', (0,0), (-1,-1), 0.3, HexColor('#e2e8f0')),
                                ('ROWBACKGROUNDS', (0,1), (-1,-1), [HexColor('#ffffff'), HexColor('#f8fafc')]),
                                ('LEFTPADDING', (0,0), (-1,-1), 3),
                                ('BOTTOMPADDING', (0,0), (-1,-1), 2.5),
                            ]))
                            story.append(t_ev)
                            story.append(Spacer(1, 2))
            if content.get("provenance"):
                story.append(Paragraph(f"Provenance: {_sanitize(content.get('provenance','')[:500])}", small))
            if content.get("generated_at"):
                story.append(Paragraph(f"Generated: {_sanitize(content.get('generated_at',''))}", small))
            if content.get("dataset_version_number"):
                story.append(Paragraph(f"Dataset Version: V{content.get('dataset_version_number')} ({_sanitize(str(content.get('dataset_version',''))[:8])})", small))
            story.append(Spacer(1, 4))
        else:
            story.append(Paragraph(_sanitize(str(ev)[:600]), body))
            story.append(Spacer(1, 3))

    # Question Coverage
    if content.get("question_coverage") or content.get("coverage"):
        cov = content.get("question_coverage") or content.get("coverage")
        story.append(Paragraph("Question Coverage", h1))
        if isinstance(cov, dict):
            story.append(Paragraph(f"Requested: {len(cov.get('requested_requirements', cov.get('requested',[])))} | Completed: {len(cov.get('completed_requirements', cov.get('completed',[])))} | Coverage: {cov.get('coverage_ratio', cov.get('coverage',0))*100:.0f}% | Status: {cov.get('execution_status','')} | Completeness: {cov.get('analysis_completeness','')}", body))
            if cov.get("missing_requirements") or cov.get("missing"):
                miss = cov.get("missing_requirements") or cov.get("missing") or []
                if miss:
                    story.append(Paragraph(f"Missing: {_sanitize(', '.join([str(x) for x in miss[:5]]))}", small))
            # Detailed requirement contracts if present
            if content.get("requirement_contracts"):
                for rc in content["requirement_contracts"][:6]:
                    story.append(Paragraph(f"• {rc.get('id','')}: {rc.get('status','')} — {_sanitize(rc.get('description','')[:80])}", small))
        else:
            story.append(Paragraph(_sanitize(str(cov)[:500]), body))
        story.append(Spacer(1, 4))

    # Generic fallback sections if not already present
    if content.get("kpis"):
        story.append(Paragraph("Key Metrics (actual, from execution)", h1))
        kpi_rows = [[_sanitize(str(k)), _sanitize(str(v))] for k,v in content["kpis"].items()]
        t2 = Table([["KPI","Value"]] + kpi_rows, colWidths=[70*mm, 80*mm])
        t2.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), HexColor('#0b0d18')),
            ('TEXTCOLOR', (0,0), (-1,0), white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('GRID', (0,0), (-1,-1), 0.4, HexColor('#e2e8f0')),
            ('BACKGROUND', (0,1), (-1,-1), HexColor('#ffffff')),
            ('LEFTPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))
        story.append(t2)
        story.append(Spacer(1, 4))

    if content.get("column_stats"):
        story.append(Paragraph("Column Overview", h1))
        rows = [["Column","Type","Null %","Unique","Mean"]]
        for c in content["column_stats"][:20]:
            rows.append([_sanitize(str(c.get('name',''))[:18]), _sanitize(str(c.get('type',''))[:12]), f"{c.get('null_pct',0):.1f}%" if isinstance(c.get('null_pct'), (int,float)) else str(c.get('null_pct','')), str(c.get('unique','')), (f"{c.get('mean'):.2f}" if isinstance(c.get('mean'), (int,float)) else "—")])
        t3 = Table(rows, colWidths=[35*mm, 35*mm, 25*mm, 25*mm, 30*mm])
        t3.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), HexColor('#0b0d18')),
            ('TEXTCOLOR', (0,0), (-1,0), white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 7),
            ('GRID', (0,0), (-1,-1), 0.3, HexColor('#e2e8f0')),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [HexColor('#ffffff'), HexColor('#f8fafc')]),
            ('LEFTPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2.5),
        ]))
        story.append(t3)
        story.append(Spacer(1, 4))

    # Footer continuity
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor('#e2e8f0')))
    story.append(Paragraph(f"Generated by Open Data Copilot — {datetime.now(timezone.utc).isoformat()} — Report ID {report.id} — Dataset {dataset.id}", small))
    story.append(Paragraph("Privacy: When AI_PROVIDER=openai, schema summaries may be sent to LLM; full raw dataset never sent. Deterministic mode is local.", ParagraphStyle('Privacy', parent=small, fontSize=7, leading=9, textColor=HexColor('#94a3b8'))))

    return story

def build_combined_story(report, dataset, content: Dict[str,Any], source_reports: List[Any]) -> List[Any]:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title2', parent=styles['Title'], fontSize=20, leading=24, textColor=HexColor('#0b0d18'), alignment=TA_LEFT, spaceAfter=6)
    h1 = ParagraphStyle('H1', parent=styles['Heading1'], fontSize=13, leading=16, textColor=HexColor('#0b0d18'), spaceBefore=12, spaceAfter=6)
    h2 = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=11, leading=14, textColor=HexColor('#1e293b'), spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle('Body', parent=styles['Normal'], fontSize=9, leading=13, textColor=HexColor('#334155'))
    small = ParagraphStyle('Small', parent=body, fontSize=8, leading=11, textColor=HexColor('#64748b'))
    bullet_style = ParagraphStyle('Bullet', parent=body, fontSize=9, leading=12, leftIndent=12, bulletIndent=0, spaceBefore=2, spaceAfter=2)

    story = []
    # COVER PAGE
    story.append(Paragraph("OPEN DATA COPILOT", ParagraphStyle('CoverBrand', parent=body, fontSize=10, leading=12, textColor=HexColor('#6d6af0'), fontName='Helvetica-Bold')))
    story.append(Spacer(1, 12))
    story.append(Paragraph("Combined Intelligence Report", title_style))
    story.append(Paragraph(f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", body))
    story.append(Paragraph(f"Report Count: {len(source_reports)}", body))
    datasets_involved = list(set([r.dataset_id for r in source_reports]))
    story.append(Paragraph(f"Datasets: {', '.join(datasets_involved[:3])}", small))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=0.7, color=HexColor('#e2e8f0')))
    story.append(Spacer(1, 8))

    # TABLE OF CONTENTS (generation uses titles)
    story.append(Paragraph("TABLE OF CONTENTS", h1))
    toc_entries = []
    toc_entries.append("1. Executive Summary .................................................... 1")
    for idx, rep in enumerate(source_reports, start=1):
        # Derive title: source_report.title or source_report.question (never generic)
        t = (rep.title or "").strip()
        if not t or t.lower() == "report 1" or t.lower().startswith("report "):
            # Try to derive from content question
            c = rep.content or {}
            q = c.get("business_question") or c.get("title") or c.get("question") or ""
            if q and len(q.strip()) > 5:
                t = q.strip()[:60]
            else:
                t = f"Report {idx}" if not t else t
        # Truncate for TOC
        toc_line = f"{idx+1}. {t[:55]} .................................................... {idx+1}"
        toc_entries.append(toc_line)
    toc_entries.append(f"{len(source_reports)+2}. Appendix .................................................... {len(source_reports)+2}")
    for line in toc_entries:
        story.append(Paragraph(_sanitize(line), small))
        story.append(Spacer(1, 2))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor('#e2e8f0')))
    story.append(Spacer(1, 6))

    # EXECUTIVE SUMMARY (5 bullets per report)
    story.append(Paragraph("EXECUTIVE SUMMARY", h1))
    story.append(Paragraph(f"Combined summary of {len(source_reports)} reports. Each bullet set is evidence-based (5 per report).", small))
    story.append(Spacer(1, 4))
    for idx, summ in enumerate(content.get("combined_summaries", []), start=1):
        # Find corresponding report for title derivation
        rep = source_reports[idx-1] if idx-1 < len(source_reports) else None
        t = summ.get("title") or (rep.title if rep else f"Report {idx}")
        # If title is generic, derive
        if not t or t == f"Report {idx}" or (t.startswith("Report ") and len(t) < 15):
            if rep and rep.content:
                q = rep.content.get("business_question") or rep.content.get("title") or ""
                if q:
                    t = q[:60]
        story.append(Paragraph(f"Report {idx} — {_sanitize(t)}", h2))
        bullets = summ.get("bullets", [])
        # Ensure exactly 5 bullets; if less, pad? Already generated 5 per report in reports.py
        for b in bullets[:5]:
            story.append(Paragraph(f"• {_sanitize(b)}", bullet_style))
        story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor('#e2e8f0')))
    story.append(Spacer(1, 6))

    # DETAILED REPORTS SECTION
    story.append(Paragraph("DETAILED REPORTS", h1))
    story.append(Paragraph(f"This section contains full details for each of the {len(source_reports)} reports, including titles, dataset versions, findings, charts, evidence, statistical validations, and recommendations.", small))
    story.append(Spacer(1, 6))
    for idx, rep in enumerate(source_reports, start=1):
        c = rep.content or {}
        # Derive individual report titles from source_report.title or source_report.question (never generic)
        display_title = rep.title
        if not display_title or display_title.strip().lower().startswith("report "):
            # Try to derive from business_question etc.
            q = c.get("business_question") or c.get("title") or c.get("question") or c.get("executive_summary","")[:60]
            if q and q.strip() and not q.strip().lower().startswith("report"):
                display_title = q.strip()[:80]
            else:
                display_title = f"Report {idx}"  # fallback only if no question exists
        story.append(Paragraph(f"Report {idx}: {_sanitize(display_title)}", h2))
        story.append(Paragraph(f"Dataset: {_sanitize(c.get('dataset_overview',{}).get('name',''))} | Version: {rep.dataset_version_number or c.get('dataset_version_number','')} | Session: {rep.session_id or c.get('session_id','')} | Created: {rep.created_at} | Report ID: {rep.id[:8]}", small))
        story.append(Spacer(1, 3))
        # Executive summary
        exec_sum = c.get("executive_summary","")[:800]
        if exec_sum:
            story.append(Paragraph("Executive Summary", h2))
            story.append(Paragraph(_sanitize(exec_sum), body))
            story.append(Spacer(1, 3))
        # Business Question
        if c.get("business_question"):
            story.append(Paragraph("Business Question", h2))
            story.append(Paragraph(_sanitize(c.get("business_question","")), body))
            story.append(Spacer(1, 3))
        # Dataset Overview
        if c.get("dataset_overview"):
            ov = c.get("dataset_overview",{})
            story.append(Paragraph("Dataset Overview", h2))
            story.append(Paragraph(f"Rows: {ov.get('rows','')} | Columns: {ov.get('columns','')} | File: {_sanitize(ov.get('name',''))} | Version V{ov.get('version_number','')}", small))
            story.append(Spacer(1, 2))
        # Data Quality
        if c.get("data_quality"):
            dq = c.get("data_quality",{})
            story.append(Paragraph("Data Quality", h2))
            if isinstance(dq, dict) and dq.get("factors"):
                story.append(Paragraph(_sanitize(str(dq.get("factors"))[:400]), small))
            story.append(Paragraph(f"Score: {dq.get('score','')}/100", small))
            story.append(Spacer(1, 2))
        # Key Findings
        if c.get("key_findings") or c.get("insights"):
            kf = c.get("key_findings") or c.get("insights")
            story.append(Paragraph("Key Findings", h2))
            for ins in kf[:4]:
                if isinstance(ins, dict):
                    story.append(Paragraph(f"<b>{_sanitize(ins.get('title',''))}</b> — {_sanitize(ins.get('description','')[:300])}", body))
                else:
                    story.append(Paragraph(_sanitize(str(ins)[:300]), body))
                story.append(Spacer(1, 2))
        # Charts + Interpretations (if stored in report)
        charts = c.get("charts") or c.get("chart_specs") or []
        # Also try to extract from session evidence if available
        if charts:
            for cidx, chart in enumerate(charts[:2], start=1):
                cht_title = chart.get("title") or f"Chart {cidx}"
                story.append(Paragraph(f"Chart: {_sanitize(cht_title)}", h2))
                d = chart_spec_to_drawing(chart, width=460, height=220)
                story.append(d)
                story.append(Spacer(1, 2))
                interp = chart.get("interpretation") or interpret_chart(chart)
                story.append(Paragraph(f"<b>Interpretation:</b> {_sanitize(interp)}", small))
                story.append(Spacer(1, 2))
                prov = chart.get("provenance") or c.get("provenance") or "DuckDB execution"
                story.append(Paragraph(f"<b>Evidence:</b> {_sanitize(prov[:200])}", small))
                story.append(Spacer(1, 3))
        # Statistical validation
        if c.get("statistical_validation"):
            sv = c["statistical_validation"]
            story.append(Paragraph("Statistical Validation", h2))
            story.append(Paragraph(f"Method: {_sanitize(str(sv.get('method','')))} | p={sv.get('p_value','')} | { _sanitize(str(sv.get('significance','')))}", small))
            if sv.get("limitations"):
                story.append(Paragraph(f"Limitations: {_sanitize('; '.join([str(x) for x in sv.get('limitations',[])[:2]]))}", small))
            story.append(Spacer(1, 2))
        # Evidence
        if c.get("evidence"):
            ev = c["evidence"]
            if isinstance(ev, dict) and ev.get("generated_code"):
                story.append(Paragraph("Evidence — Generated SQL", h2))
                story.append(Paragraph(f"<font name='Courier' size='7'>{_sanitize(ev.get('generated_code','')[:400])}</font>", ParagraphStyle('MonoSmall', parent=small, fontName='Courier', fontSize=7, leading=9, textColor=HexColor('#334155'))))
                story.append(Spacer(1, 2))
            elif isinstance(ev, dict) and ev.get("result_columns"):
                story.append(Paragraph("Evidence", h2))
                story.append(Paragraph(f"Columns: {_sanitize(', '.join([str(x) for x in ev.get('result_columns',[])[:5]]))} | Rows: {ev.get('row_count','')}", small))
                story.append(Spacer(1, 2))
        # Recommendations
        if c.get("recommendations") or c.get("recommendation"):
            rec = c.get("recommendations") or c.get("recommendation")
            if rec:
                story.append(Paragraph("Recommendations", h2))
                rec_text = rec.get("recommendation","")[:500] if isinstance(rec, dict) else str(rec)[:500]
                story.append(Paragraph(_sanitize(rec_text), body))
                if isinstance(rec, dict) and rec.get("rationale"):
                    story.append(Paragraph(f"Rationale: {_sanitize(rec.get('rationale','')[:300])}", small))
                story.append(Spacer(1, 2))
        # Question Coverage
        if c.get("question_coverage"):
            cov = c["question_coverage"]
            story.append(Paragraph("Question Coverage", h2))
            story.append(Paragraph(f"Coverage: {cov.get('coverage_ratio',0)*100:.0f}% | Status: {cov.get('execution_status','')} | Completeness: {cov.get('analysis_completeness','')}", small))
            story.append(Spacer(1, 2))
        # Lineage / Provenance trace
        if c.get("provenance"):
            story.append(Paragraph("Provenance", h2))
            story.append(Paragraph(_sanitize(c.get("provenance","")[:400]), small))
            story.append(Spacer(1, 4))
        # Page break after each detailed report except last
        if idx < len(source_reports):
            story.append(PageBreak())

    # APPENDIX
    story.append(Paragraph("APPENDIX", h1))
    story.append(Paragraph("Methodology", h2))
    story.append(Paragraph(_sanitize(content.get("methodology", "Combined via deterministic bullet generation from stored report content; each report's numbers from DuckDB execution.")), body))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Provenance", h2))
    story.append(Paragraph(_sanitize(content.get("provenance","")), small))
    story.append(Spacer(1, 2))
    story.append(Paragraph("Timestamps", h2))
    for idx, rep in enumerate(source_reports, start=1):
        story.append(Paragraph(f"Report {idx} ({_sanitize(rep.title[:40])}): Created {rep.created_at} | Version {rep.dataset_version_number} | ID {rep.id[:8]}", small))
    story.append(Spacer(1, 2))
    story.append(Paragraph("Assumptions & Limitations", h2))
    for lim in content.get("assumptions_and_limitations", [])[:5]:
        story.append(Paragraph(f"• {_sanitize(lim)}", bullet_style))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor('#e2e8f0')))
    story.append(Paragraph(f"Generated by Open Data Copilot — {datetime.now(timezone.utc).isoformat()} — Combined Report ID {report.id}", small))

    return story

def save_single_pdf(report, dataset, content: Dict[str,Any], charts: List[Dict[str,Any]], output_path: str):
    story = build_single_report_story(report, dataset, content, charts)
    doc = SimpleDocTemplate(output_path, pagesize=A4, leftMargin=14*mm, rightMargin=14*mm, topMargin=12*mm, bottomMargin=12*mm, title=_sanitize(report.title), author="Open Data Copilot")
    def _header(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(HexColor('#0b0d18'))
        canvas.setFont('Helvetica-Bold', 7)
        canvas.drawString(14*mm, 292*mm, "OPEN DATA COPILOT  •  Premium Intelligence  •  Trusted Analytics")
        canvas.restoreState()
    doc.build(story, onFirstPage=_header, onLaterPages=_header)
    return output_path

def save_combined_pdf(report, dataset, content: Dict[str,Any], source_reports: List[Any], output_path: str):
    story = build_combined_story(report, dataset, content, source_reports)
    doc = SimpleDocTemplate(output_path, pagesize=A4, leftMargin=14*mm, rightMargin=14*mm, topMargin=12*mm, bottomMargin=12*mm, title=_sanitize(report.title), author="Open Data Copilot")
    def _header(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(HexColor('#0b0d18'))
        canvas.setFont('Helvetica-Bold', 7)
        canvas.drawString(14*mm, 292*mm, "OPEN DATA COPILOT  •  Combined Report")
        canvas.restoreState()
    doc.build(story, onFirstPage=_header, onLaterPages=_header)
    return output_path
