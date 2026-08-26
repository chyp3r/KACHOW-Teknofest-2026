"""Yönlendirme grafiği için aktif birimlere okuma tarafı erişimi.

`routing_graph.create_routing_graph` süreç başına bir kez, herhangi bir
istek kapsamlı `Depends(get_db)` dışında derlenir (bkz.
`app.api.dependency.get_routing_graph`) -- `app.domains.drafts.
draft_recorder`'ın taslak yazmaları için belgelediği aynı durum. Bunun
yerine bu, her çağrıda kendi kısa ömürlü oturumunu açıp kapatır, böylece
her yönlendirme kararı birim listesini süreç başladığı andaki değil,
*şu anki* haliyle okur.

`app.ai` içinden doğrudan import edilmek yerine `app.domains.units` içinde
tutulur: `app.ai.workflows.routing_graph` hiçbir zaman `app.domains` import
etmez (bkz. `docs/architecture/backend.md` -- "Backend yalnızca AI Core'u
çağırır"), bu yüzden bu, tıpkı `llm_client` gibi, grafiğe kurulum anında
sade bir çağrılabilir (callable) olarak verilir.
"""

from typing import List, Tuple

from app.domains.units.repository import UnitRepository
from app.infrastructure.database.session import tenant_session


async def get_active_units_for_routing(company_id: str) -> List[Tuple[str, str]]:
    """`company_id`'nin şu anda aktif olan her birimi için `(name, description)` döndürür.

    Args:
        company_id: Birim listesinin kapsamlanacağı kiracı -- iki şirket de
            "İnsan Kaynakları" birimine sahip olabilir ve birinin yönlendirme
            kararı diğerininkini asla görmemelidir.

    Returns:
        Henüz hiç birim yapılandırılmamışsa (veya `company_id` boş/geçersizse)
        boş bir liste -- çağıranlar bunu bir hata değil "yönlendirilecek
        bir şey yok" olarak ele almalıdır.
    """
    if not company_id:
        return []
    async with tenant_session(company_id) as session:
        repository = UnitRepository(session)
        units = await repository.list_active(company_id)
        return [(unit.name, unit.description) for unit in units]
