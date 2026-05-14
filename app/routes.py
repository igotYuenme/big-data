from flask import Blueprint, render_template, Response

from .analysis import charts_json_for_api, get_dashboard_payload

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    return render_template("index.html", **get_dashboard_payload())


@bp.route("/data-analysis")
def data_analysis():
    """作业要求：分析结果与可视化主入口。"""
    return render_template("index.html", **get_dashboard_payload())


@bp.route("/api/analysis.json")
def analysis_api():
    """交互式前端可轮询或拉取同一套图表配置（JSON）。"""
    return Response(charts_json_for_api(), mimetype="application/json; charset=utf-8")


@bp.route("/favicon.ico")
def favicon():
    return Response(status=204)
