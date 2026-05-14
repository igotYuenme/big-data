from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _camel(name: str) -> str:
    parts = name.rstrip("_").split("_")
    if not parts:
        return name
    head, *tail = parts
    return head + "".join(piece[:1].upper() + piece[1:] for piece in tail)


def _convert(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {k: _convert(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [_convert(v) for v in value]
    return value


@dataclass
class _BaseOpts:
    values: dict[str, Any] = field(default_factory=dict)

    def __init__(self, **kwargs: Any) -> None:
        object.__setattr__(self, "values", kwargs)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in self.values.items():
            if value is None:
                continue
            out[_camel(key)] = _convert(value)
        return out


class InitOpts(_BaseOpts):
    pass


class LabelOpts(_BaseOpts):
    def to_dict(self) -> dict[str, Any]:
        out = super().to_dict()
        if "isShow" in out:
            out["show"] = out.pop("isShow")
        if "is_show" in out:
            out["show"] = out.pop("is_show")
        return out


class TitleOpts(_BaseOpts):
    def to_dict(self) -> dict[str, Any]:
        out = super().to_dict()
        if "title" in out:
            out["text"] = out.pop("title")
        if "subtitle" in out:
            out["subtext"] = out.pop("subtitle")
        return out


class AxisOpts(_BaseOpts):
    def to_dict(self) -> dict[str, Any]:
        out = super().to_dict()
        if "nameLocation" not in out and "name_location" in self.values:
            out["nameLocation"] = self.values["name_location"]
        if "nameGap" not in out and "name_gap" in self.values:
            out["nameGap"] = self.values["name_gap"]
        if "axislabel_opts" in self.values:
            out["axisLabel"] = _convert(self.values["axislabel_opts"])
        if "max_" in self.values:
            out["max"] = self.values["max_"]
        if "min_" in self.values:
            out["min"] = self.values["min_"]
        return out


class TooltipOpts(_BaseOpts):
    pass


class DataZoomOpts(_BaseOpts):
    def to_dict(self) -> dict[str, Any]:
        out = super().to_dict()
        out.setdefault("type", "slider")
        return out


class LegendOpts(_BaseOpts):
    def to_dict(self) -> dict[str, Any]:
        out = super().to_dict()
        if "posLeft" not in out and "pos_left" in self.values:
            out["left"] = self.values["pos_left"]
        if "type_" in self.values:
            out["type"] = self.values["type_"]
        return out


class VisualMapOpts(_BaseOpts):
    def to_dict(self) -> dict[str, Any]:
        out = super().to_dict()
        if "min_" in self.values:
            out["min"] = self.values["min_"]
        if "max_" in self.values:
            out["max"] = self.values["max_"]
        if "pos_top" in self.values:
            out["top"] = self.values["pos_top"]
        return out
