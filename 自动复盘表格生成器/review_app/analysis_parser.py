from __future__ import annotations

import re


def parse_analysis_sections(analysis: str) -> dict[str, str]:
    """按 Markdown 标题拆分，供驾驶舱按模块展示。"""
    sections: dict[str, list[str]] = {}
    current = "分析摘要"
    for raw_line in analysis.splitlines():
        heading = re.match(r"^#{1,3}\s+(.+?)\s*$", raw_line.strip())
        if heading:
            current = heading.group(1).strip()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(raw_line)
    return {
        title: "\n".join(lines).strip()
        for title, lines in sections.items()
        if "\n".join(lines).strip()
    }


def parse_task_table(analysis: str) -> list[dict]:
    """提取模型输出的标准个股任务 Markdown 表格。"""
    lines = [line.strip() for line in analysis.splitlines() if line.strip()]
    required = [
        "个股",
        "首板出身",
        "原始任务",
        "当前地位",
        "协同/压制对象",
        "完成信号",
        "失败信号",
    ]
    for index, line in enumerate(lines):
        if not (
            line.startswith("|")
            and all(column in line for column in required)
        ):
            continue
        headers = [cell.strip() for cell in line.strip("|").split("|")]
        if (
            index + 1 >= len(lines)
            or not re.match(r"^\|?[\s:|-]+\|", lines[index + 1])
        ):
            continue
        tasks: list[dict] = []
        for row in lines[index + 2:]:
            if not row.startswith("|"):
                break
            values = [cell.strip() for cell in row.strip("|").split("|")]
            if len(values) != len(headers):
                continue
            item = dict(zip(headers, values))
            if not item.get("个股"):
                continue
            tasks.append(
                {
                    "stock": item.get("个股", ""),
                    "origin": item.get("首板出身", ""),
                    "original_task": item.get("原始任务", ""),
                    "current_position": item.get("当前地位", ""),
                    "relations": item.get("协同/压制对象", ""),
                    "success_signal": item.get("完成信号", ""),
                    "failure_signal": item.get("失败信号", ""),
                }
            )
        return tasks[:8]
    return []
