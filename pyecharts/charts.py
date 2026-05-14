from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from .options import _convert


def _opts(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if isinstance(obj, dict):
        return deepcopy(obj)
    return {}


class _BaseChart:
    chart_type = "line"

    def __init__(self, init_opts=None):
        self.init_opts = init_opts
        self._xaxis: list[Any] = []
        self._yaxis: list[Any] = []
        self._series: list[dict[str, Any]] = []
        self._global_opts: dict[str, Any] = {}
        self._series_opts: dict[str, Any] = {}
        self._reversed = False

    def add_xaxis(self, xaxis_data):
        self._xaxis = list(xaxis_data or [])
        return self

    def add_yaxis(self, series_name, y_axis, *args, **kwargs):
        series = {"name": series_name, "type": self.chart_type, "data": list(y_axis or [])}
        if "label_opts" in kwargs and kwargs["label_opts"] is not None:
            series["label"] = _opts(kwargs["label_opts"])
        self._series.append(series)
        return self

    def set_global_opts(self, **kwargs):
        self._global_opts.update(kwargs)
        return self

    def set_series_opts(self, **kwargs):
        self._series_opts.update(kwargs)
        return self

    def reversal_axis(self):
        self._reversed = True
        return self

    def _build_common(self) -> dict[str, Any]:
        option: dict[str, Any] = {}
        title_opts = self._global_opts.get("title_opts")
        if title_opts is not None:
            option["title"] = _opts(title_opts)
        tooltip_opts = self._global_opts.get("tooltip_opts")
        if tooltip_opts is not None:
            option["tooltip"] = _opts(tooltip_opts)
        legend_opts = self._global_opts.get("legend_opts")
        if legend_opts is not None:
            option["legend"] = _opts(legend_opts)
        datazoom_opts = self._global_opts.get("datazoom_opts")
        if datazoom_opts:
            option["dataZoom"] = [_opts(item) for item in datazoom_opts]
        visualmap_opts = self._global_opts.get("visualmap_opts")
        if visualmap_opts is not None:
            option["visualMap"] = _opts(visualmap_opts)
        return option

    def dump_options_with_quotes(self) -> str:
        return json.dumps(self.dump_options(), ensure_ascii=False)

    def dump_options(self) -> dict[str, Any]:
        return {}


class Line(_BaseChart):
    chart_type = "line"

    def dump_options(self) -> dict[str, Any]:
        option = self._build_common()
        xaxis_opts = _opts(self._global_opts.get("xaxis_opts"))
        yaxis_opts = _opts(self._global_opts.get("yaxis_opts"))
        option["xAxis"] = {"type": "category", "data": self._xaxis}
        option["xAxis"].update(xaxis_opts)
        option["yAxis"] = {"type": "value"}
        option["yAxis"].update(yaxis_opts)
        series = []
        for item in self._series:
            s = deepcopy(item)
            s.setdefault("smooth", False)
            if "label_opts" in self._series_opts and self._series_opts["label_opts"] is not None:
                s["label"] = _opts(self._series_opts["label_opts"])
            series.append(s)
        option["series"] = series
        return option


class Bar(_BaseChart):
    chart_type = "bar"

    def dump_options(self) -> dict[str, Any]:
        option = self._build_common()
        xaxis_opts = _opts(self._global_opts.get("xaxis_opts"))
        yaxis_opts = _opts(self._global_opts.get("yaxis_opts"))
        if self._reversed:
            option["xAxis"] = {"type": "value"}
            option["xAxis"].update(xaxis_opts)
            option["yAxis"] = {"type": "category", "data": self._xaxis}
            option["yAxis"].update(yaxis_opts)
        else:
            option["xAxis"] = {"type": "category", "data": self._xaxis}
            option["xAxis"].update(xaxis_opts)
            option["yAxis"] = {"type": "value"}
            option["yAxis"].update(yaxis_opts)
        series = []
        for item in self._series:
            s = deepcopy(item)
            if "label_opts" in self._series_opts and self._series_opts["label_opts"] is not None:
                s["label"] = _opts(self._series_opts["label_opts"])
            series.append(s)
        option["series"] = series
        return option


class HeatMap(_BaseChart):
    chart_type = "heatmap"

    def add_yaxis(self, series_name, y_axis, data, *args, **kwargs):
        self._yaxis = list(y_axis or [])
        series = {
            "name": series_name,
            "type": self.chart_type,
            "data": list(data or []),
        }
        if "label_opts" in kwargs and kwargs["label_opts"] is not None:
            series["label"] = _opts(kwargs["label_opts"])
        self._series.append(series)
        return self

    def dump_options(self) -> dict[str, Any]:
        option = self._build_common()
        xaxis_opts = _opts(self._global_opts.get("xaxis_opts"))
        yaxis_opts = _opts(self._global_opts.get("yaxis_opts"))
        option["xAxis"] = {"type": "category", "data": self._xaxis}
        option["xAxis"].update(xaxis_opts)
        option["yAxis"] = {"type": "category", "data": self._yaxis}
        option["yAxis"].update(yaxis_opts)
        option["series"] = deepcopy(self._series)
        return option


class Funnel(_BaseChart):
    chart_type = "funnel"

    def add(self, series_name, data_pair=None, **kwargs):
        series = {
            "name": series_name,
            "type": self.chart_type,
            "data": [{"name": n, "value": v} for n, v in (data_pair or [])],
        }
        if "label_opts" in kwargs and kwargs["label_opts"] is not None:
            series["label"] = _opts(kwargs["label_opts"])
        for key in ("sort", "gap", "minSize", "maxSize"):
            if key in kwargs and kwargs[key] is not None:
                series[key] = kwargs[key]
        self._series.append(series)
        return self

    def dump_options(self) -> dict[str, Any]:
        option = self._build_common()
        option["series"] = deepcopy(self._series)
        return option


class Pie(_BaseChart):
    chart_type = "pie"

    def add(self, series_name, data_pair=None, radius=None, **kwargs):
        series = {
            "name": series_name,
            "type": self.chart_type,
            "data": [{"name": n, "value": v} for n, v in (data_pair or [])],
        }
        if radius is not None:
            series["radius"] = radius
        if "label_opts" in kwargs and kwargs["label_opts"] is not None:
            series["label"] = _opts(kwargs["label_opts"])
        self._series.append(series)
        return self

    def dump_options(self) -> dict[str, Any]:
        option = self._build_common()
        option["series"] = deepcopy(self._series)
        return option
