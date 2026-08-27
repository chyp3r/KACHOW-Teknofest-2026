#!/usr/bin/env python3
"""Langfuse'ta "KACHOW · LLM İzleme" panosunu oluşturur (idempotent).

Langfuse'un Grafana gibi dosyadan sağlama (provisioning) mekanizması yoktur;
panolar UI'den veya public API'den yaratılır. Bu betik, langfuse DB'si
sıfırlandığında panoyu tek komutla geri getirmek için vardır.

Çalıştırma (backend konteynerinin içinden -- LANGFUSE_* ayarları ve httpx
oradan hazır gelir):

    docker compose cp scripts/langfuse_bootstrap_dashboard.py backend:/tmp/d.py
    docker compose exec backend python /tmp/d.py

Her çalıştırmada adı "KACHOW" ile başlayan panoyu ve tüm serbest widget'ları
silip yeniden kurar; birden çok kez güvenle çalıştırılabilir.
"""

import base64
import sys

import httpx

from app.core.config import settings

if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
    sys.exit("LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY ayarlı değil.")

_auth = base64.b64encode(
    f"{settings.LANGFUSE_PUBLIC_KEY}:{settings.LANGFUSE_SECRET_KEY}".encode()
).decode()
c = httpx.Client(
    base_url=settings.LANGFUSE_HOST,
    headers={"Authorization": f"Basic {_auth}", "content-type": "application/json"},
    timeout=30,
)

WIDGETS = "/api/public/unstable/dashboard-widgets"
DASHBOARDS = "/api/public/unstable/dashboards"
VIEW = "observations"

M_COUNT = [{"measure": "count", "agg": "count"}]
M_TOKENS = [{"measure": "totalTokens", "agg": "sum"}]
M_LAT_AVG = [{"measure": "latency", "agg": "avg"}]
M_LAT_P95 = [{"measure": "latency", "agg": "p95"}]


def _widget(name, desc, chart, metrics, dims=None, cfg=None):
    body = {
        "name": name,
        "description": desc,
        "view": VIEW,
        "dimensions": dims or [],
        "metrics": metrics,
        "filters": [],
        "chartType": chart,
        "chartConfig": {"type": chart, **(cfg or {})},
    }
    r = c.post(WIDGETS, json=body)
    r.raise_for_status()
    return r.json()["id"]


def main() -> None:
    # idempotent: eski KACHOW panosunu + tüm serbest widget'ları temizle
    for d in c.get(DASHBOARDS).json()["data"]:
        if d["name"].startswith("KACHOW"):
            c.delete(f"{DASHBOARDS}/{d['id']}")
    for w in c.get(WIDGETS).json()["data"]:
        c.delete(f"{WIDGETS}/{w['id']}")

    w = {
        "n_obs": _widget("Toplam gözlem", "Seçili dönemdeki observation adedi", "NUMBER", M_COUNT),
        "n_tok": _widget("Toplam token", "Girdi + çıktı token toplamı", "NUMBER", M_TOKENS),
        "n_lat": _widget("Ort. gecikme (sn)", "Ortalama observation süresi", "NUMBER", M_LAT_AVG),
        "n_p95": _widget("p95 gecikme (sn)", "95. yüzdelik observation süresi", "NUMBER", M_LAT_P95),
        "ts_obs": _widget("Gözlem sayısı (zaman)", "Zamana göre observation sayısı",
                          "LINE_TIME_SERIES", M_COUNT),
        "ts_tok": _widget("Token kullanımı (zaman)", "Zamana göre token toplamı",
                          "LINE_TIME_SERIES", M_TOKENS),
        "bar_model": _widget("Model bazında gözlem", "En çok kullanılan modeller", "VERTICAL_BAR",
                             M_COUNT, dims=[{"field": "providedModelName"}], cfg={"row_limit": 10}),
        "pie_level": _widget("Seviye dağılımı", "DEBUG / DEFAULT / WARNING / ERROR", "PIE",
                             M_COUNT, dims=[{"field": "level"}]),
        "bar_name": _widget("İşlem bazında ort. gecikme", "Observation adına göre ortalama süre",
                            "HORIZONTAL_BAR", M_LAT_AVG, dims=[{"field": "name"}],
                            cfg={"row_limit": 15}),
    }

    dash = c.post(
        DASHBOARDS,
        json={
            "name": "KACHOW · LLM İzleme",
            "description": "Backend AI turlarinin observation, token ve gecikme dokumu.",
        },
    ).json()
    did = dash["id"]

    # 12 sütunluk ızgara
    layout = [
        ("n_obs", 0, 0, 3, 4), ("n_tok", 3, 0, 3, 4),
        ("n_lat", 6, 0, 3, 4), ("n_p95", 9, 0, 3, 4),
        ("ts_obs", 0, 4, 6, 6), ("ts_tok", 6, 4, 6, 6),
        ("bar_model", 0, 10, 6, 6), ("pie_level", 6, 10, 6, 6),
        ("bar_name", 0, 16, 12, 6),
    ]
    for key, x, y, width, height in layout:
        c.post(
            f"{DASHBOARDS}/{did}/placements",
            json={"type": "widget", "widgetId": w[key], "x": x, "y": y,
                  "width": width, "height": height},
        ).raise_for_status()

    print("Pano hazır:", dash["name"])
    print(f"{settings.LANGFUSE_PUBLIC_URL}/project/kachow/dashboards/{did}")


if __name__ == "__main__":
    main()
