"""OpenAPI schema snapshot test.

``frontend/package.json``'ın ``api:types:check`` script'i frontend'in
generated types'ının şemayla senkron kaldığını doğruluyor -- ama yalnızca
frontend tarafında, şemanın kendisinde değil: bu şemanın kaynağında hiçbir
kontrat testi yoktu, dolayısıyla incelenmemiş bir şema değişikliği yalnızca
frontend'in bir sonraki `npm run api:types` çalıştırmasında görünür oluyordu
(ya da hiç görünmüyordu, kimse çalıştırmazsa). Bu test onu kaynağında,
backend tarafında yakalar.

Regenerate deliberately, never accidentally: set
``KACHOW_UPDATE_OPENAPI_SNAPSHOT=1``. Bir router değişikliği incelenmemiş bir
şema kaymasına yol açmamalı -- güncelleme bilinçli bir commit olmalı, ardından
``frontend/`` içinde ``npm run api:types`` çalıştırılıp generated types
senkronize edilmeli.
"""

import json
import os
import pathlib

import pytest

from app.main import app

SNAPSHOT_PATH = pathlib.Path(__file__).resolve().parent / "openapi.snapshot.json"
_UPDATE = os.environ.get("KACHOW_UPDATE_OPENAPI_SNAPSHOT") == "1"


def _current_schema() -> dict:
    # FastAPI.openapi() caches its result on app.openapi_schema after the
    # first call in this process -- reset it so this test always builds
    # from the app's *current* routes rather than a schema some earlier
    # test/import in the same session already cached.
    app.openapi_schema = None
    return app.openapi()


def test_openapi_schema_matches_snapshot():
    schema = _current_schema()

    if _UPDATE:
        SNAPSHOT_PATH.write_text(
            json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        pytest.skip(f"OpenAPI snapshot regenerated: {SNAPSHOT_PATH}")

    if not SNAPSHOT_PATH.exists():
        pytest.fail(
            "No OpenAPI snapshot -- run with KACHOW_UPDATE_OPENAPI_SNAPSHOT=1 "
            "to create it, then review the new file before committing it."
        )

    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert schema == expected, (
        "OpenAPI schema changed. If intentional, regenerate with "
        "KACHOW_UPDATE_OPENAPI_SNAPSHOT=1, review the diff on "
        "openapi.snapshot.json, then run `npm run api:types` in frontend/ "
        "to keep its generated types in sync with the same change."
    )
