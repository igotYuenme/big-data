/**
 * ECharts 挂载：与深色页面搭配使用内置 dark 主题，避免坐标/文字与背景同色导致「看不见图」。
 * CDN 未加载时给出可见提示；setOption 异常会输出到控制台。
 */
(function (global) {
  "use strict";

  function showLoadError() {
    var nodes = document.querySelectorAll(".chart-box");
    var msg =
      '<p style="color:#8b9bb4;padding:1.5rem;margin:0;">ECharts 未加载：请确认 <code>static/js/echarts.min.js</code> 存在且路径正确（约 1MB）。</p>';
    for (var i = 0; i < nodes.length; i++) {
      if (!nodes[i].innerHTML) nodes[i].innerHTML = msg;
    }
  }

  function mountAll(charts) {
    if (!charts || !charts.length) return;
    if (!global.echarts) {
      console.error("ECharts 未定义：请确认 echarts.min.js 已成功加载");
      showLoadError();
      return;
    }
    var instances = [];
    charts.forEach(function (item) {
      var el = document.getElementById(item.id);
      if (!el || !item.options) return;
      try {
        var ch = global.echarts.init(el, "dark", { renderer: "canvas" });
        ch.setOption(item.options);
        instances.push(ch);
        requestAnimationFrame(function () {
          ch.resize();
        });
      } catch (err) {
        console.error("ECharts setOption 失败:", item.id, err);
        el.innerHTML =
          '<p style="color:#f87171;padding:1rem;">图表渲染失败，请打开浏览器开发者工具 (F12) 查看控制台。</p>';
      }
    });
    global.addEventListener("resize", function () {
      instances.forEach(function (ch) {
        try {
          ch.resize();
        } catch (e) {}
      });
    });
  }

  global.TaobaoCharts = { mountAll: mountAll };
})(typeof window !== "undefined" ? window : this);
