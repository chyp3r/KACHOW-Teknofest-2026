"""Analiz-önbelleği anahtar kuralı, bağımsız (standalone).

``app.domains.documents.service``'ten ayrı tutuldu, böylece bir belgenin
önbelleğe alınmış analizini ``BaseStorage`` üzerinden okumak için aynı
anahtara ihtiyaç duyan ``app.ai.workflows.planning_graph`` (bkz.
``_load_cached_document``) domain servis modülünü import etmeden bunu
paylaşabilir: yapay zekâ iş akışı katmanının bir domain servisine uzanması,
bu kod tabanının olağan bağımlılık yönünü tersine çevirirdi (domain'ler
``app.ai.*``'tan import eder, tersi değil).
"""


def analysis_cache_key(storage_path: str) -> str:
    """Bir analiz-önbelleği JSON'ının dosyalandığı BaseStorage anahtarı.

    Belgenin kendi byte'larının yaşadığı aynı `self.storage`/backend --
    mutlaka yerel disk değil. Bunun neden önemli olduğu için bkz.
    ``app.domains.documents.service._save_document_analysis_cache``: bunu
    ham bir yerel-dosya-sistemi yolu yerine yapılandırılmış depolama
    backend'i üzerinden yönlendirmek, önbelleği ``STORAGE_TYPE=s3`` altında
    çalışır ve birden fazla backend replikası için güvenli kılan şeydir.
    """
    return f"{storage_path}_analysis.json"
