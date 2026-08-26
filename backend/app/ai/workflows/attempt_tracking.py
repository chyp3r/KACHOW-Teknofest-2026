"""Draft ve revize onarım döngüleri için paylaşılan "en iyi deneme kazanır" defter tutma mantığı.

Her iki döngü de (``draft_graph``'ın writer -> verify -> revise -> writer'ı ve
``revise_graph``'ın rewrite -> verify -> repair -> rewrite'ı) aynı tur üzerinde
birden fazla deneme çalıştırabilir. Bu modülden önce, hangi deneme *en son*
bittiyse gönderilen hep oydu -- şu durumlarda bile:

- Daha önceki bir deneme daha yüksek skor almışken, sonraki bir onarım
  geçişi bir kusuru düzeltirken daha kötüsünü ortaya çıkarmış olabilir
  (küçük bir modelin kendi çıktısını düzenlemesi istendiğinde sık görülen
  bir hata biçimi). Deneme bütçesi böylece elde, turun zaten sahip olduğundan
  kesinlikle daha kötü bir taslakla tükenir.
- Bir onarım geçişi tamamen çökmüş veya zaman aşımına uğramış olabilir; bu da
  gayet iyi durumdaki önceki bir denemeyi de beraberinde atıp, bunun yerine
  boş veya kesilmiş bir taslağı sert bir ``FAILED`` durumu altında gönderir.

Bu modül, bir turun döngüsü boyunca en yüksek skorlu denemenin tam sonuç
anlık görüntüsünü takip eder; böylece her iki hata biçimi de aynı şekilde
çözülür: turun nihai sonucu, sadece en son çalışan değil, gerçekten en
iyi skoru alan deneme olur.
"""

from typing import Any, Optional

#: Bir verify düğümünün kendi döndürdüğü update'in taşıdığı ve bir denemenin
#: sonucunu tam olarak tanımlayan her alan -- o denemeyi hiçbir şeyi yeniden
#: çalıştırmadan turun nihai sonucu olarak göndermek için gereken her şey.
#: draft_graph.DraftState ve revise_graph.ReviseState arasında paylaşılır;
#: ikisi de kendi verify-düğümü update'leri için tam olarak bu alan
#: kümesini kullanır (revise_graph'ın kendi update'inde
#: ``reasoning_level``/``company_adapter``/``company_rules`` yoktur, bu
#: yüzden bunlar orada anlık görüntüden basitçe eksik kalır -- bkz.
#: ``snapshot_attempt``'in kendi ``if field in update`` filtresi).
ATTEMPT_SNAPSHOT_FIELDS: tuple[str, ...] = (
    "draft",
    "confidence_score",
    "combined_score",
    "requires_human_approval",
    "requires_revision",
    "evaluation_notes",
    "verification",
    "judge",
    "judge_available",
    "repair_items",
    "missing_information",
    "applied_rules",
    "status",
    "pii_findings",
)


def snapshot_attempt(update: dict[str, Any], draft_text: str) -> dict[str, Any]:
    """Bir verify düğümünün update'inden bir denemenin tam sonuç anlık görüntüsünü çıkar.

    Args:
        update: Bir verify düğümünün döndürmek üzere olduğu dict.
        draft_text: Bu denemenin normalize edilmiş taslak metni -- ``update``
            içinden okunmak yerine ayrıca geçirilir, çünkü çağıranlar bazen
            ``update["draft"]``'ı bu hesaplandıktan sonra tamamlar.

    Returns:
        ``best_of`` için uygun ve ``dict.update`` ile ileride bir ``update``
        dict'ine doğrudan geri eklenebilecek anlık görüntü.
    """
    snapshot = {field: update[field] for field in ATTEMPT_SNAPSHOT_FIELDS if field in update}
    snapshot["draft"] = draft_text
    return snapshot


def recover_from_failed_attempt(
    best_attempt: dict[str, Any], attempt_number: int, error_note: str
) -> dict[str, Any]:
    """Boş/çökmüş bir yeniden deneme yerine şimdiye kadar görülen en iyi denemeyi gönder.

    C3: bundan önce, zaman aşımına uğrayan veya hata fırlatan bir
    repair/rewrite geçişi, önceki, zaten doğrulanmış bir denemenin ürettiği
    her şeyi atıp boş veya kesilmiş bir taslakla sert bir ``FAILED`` sonucu
    döndürüyordu -- daha önceki bir deneme zaten gayet iyi, doğrulanmış bir
    mektup üretmiş olsa bile. Turun *ilk* denemesinde kurtarılacak bir şey
    yoktur (``verify`` henüz bir kez bile çalışmadığından ``best_attempt``
    henüz mevcut değildir) -- o yol dokunulmadan kalır; bu sadece *sonraki*
    bir onarım geçişi çöktüğünde neler olduğunu değiştirir.

    Args:
        best_attempt: ``snapshot_attempt``/``best_of``'dan gelen anlık görüntü.
        attempt_number: Bu (başarısız) denemenin kendi numarası, döndürülen
            state'in defter tutması için.
        error_note: Çökme turu başarısız kılmasa bile hâlâ gözlemlenebilir
            olması için sonuca kaydedilen kısa bir Türkçe not.

    Returns:
        ``best_attempt``'in kendi alanları artı ``attempts``/``error`` ve
        ``restored_from_best_attempt: True`` -- sonuncusu, çağıranın kendi
        yönlendirme fonksiyonuna doğrudan "end"e gitmesini söyler: bu zaten
        tam anlamıyla doğrulanmış bir sonuçtur, yeniden doğrulamak en iyi
        ihtimalle boşa iş, en kötü ihtimalle de tekrar başarısız olma
        riskidir.
    """
    return {
        **best_attempt,
        "attempts": attempt_number,
        "error": error_note,
        "restored_from_best_attempt": True,
    }


def best_of(
    current: dict[str, Any], previous_best: Optional[dict[str, Any]]
) -> dict[str, Any]:
    """Hangi deneme anlık görüntüsü daha yüksek skor alıyorsa onu döndür.

    Args:
        current: Bu denemenin anlık görüntüsü.
        previous_best: Bu tur boyunca şimdiye kadar görülen en iyi anlık
            görüntü, veya ilk denemede ``None``.

    Returns:
        ``previous_best`` ile en az eşit skor alıyorsa ``current``
        (eşitlik durumunda daha yeni deneme tercih edilir -- o zamandan beri
        uygulanan her düzeltmeyi zaten içerdiğinden ikisinin daha eksiksiz
        sonucudur), aksi halde ``previous_best`` değişmeden.
    """
    if previous_best is None:
        return current
    if current.get("combined_score", -1.0) >= previous_best.get("combined_score", -1.0):
        return current
    return previous_best
