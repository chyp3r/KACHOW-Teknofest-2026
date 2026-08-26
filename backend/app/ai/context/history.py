"""Birebir (değiştirilmemiş) konuşma turlarının bütçe farkındalıklı seçimi.

``ContextBuilder``'ın string bloklarından ayrı bir mekanizma: konuşma
geçmişi, tek bir prompt string'ine yerleştirilmek yerine assist ajanına
rol/içerik mesajlarından oluşan bir liste olarak enjekte edilir (bkz.
``AssistantAgent.run_stream``), bu yüzden ``ContextBlock``'ın
``render() -> str`` biçimine uymaz. Önceki sabit ``HISTORY_WINDOW``'un
(her zaman tam olarak 12 tur) yerine, prompt'un geri kalanı zaten büyükse
küçülen, değilse büyüyen bir pencere koyar.
"""

from typing import Callable

from app.ai.policy import get_policy

_DEFAULT_MAX_TURNS = get_policy().memory.history_window


def select_history_window(
    history: list[dict[str, str]],
    remaining_budget_tokens: int,
    count_tokens: Callable[[str], int],
    min_turns: int = 2,
    max_turns: int | None = None,
) -> list[dict[str, str]]:
    """Kalan bütçeye sığan en yeni turları seçer.

    En yeni turdan geriye doğru açgözlü (greedy) bir seçim -- zamirlerin/
    eksiltili ifadelerin çözümlenmesi için gereken şey yakınlıktır (bkz. bu
    modülün yerini aldığı eski modül), bu yüzden sığmayan bir tur mesajın
    ortasından kırpılacak değil, tamamen düşürülecek bir turdur.

    Args:
        history: Önceki turlar, en eskiden başlayarak.
        remaining_budget_tokens: Aynı prompt'taki diğer her blok
            hesaplandıktan sonra geçmiş için kalan token sayısı.
        count_tokens: Aktif istemcinin token tahmin edicisi.
        min_turns: Bütçeyi aşsa bile her zaman en az bu kadar yeni turu
            dahil eder (`history`'nin kendisi daha kısaysa daha azını) --
            çok sıkı bir bütçe prompt'u kötüleştirmeli, asistanı her tek
            cevaptan sonra hafızasız bırakmamalı.
        max_turns: Bütçe uygulanmadan önce bile kaç yeni turun dikkate
            alınacağına dair üst sınır. Varsayılan olarak
            `MemoryPolicy.history_window` (bugünkü sabit değer), böylece
            bol bir bütçe bile tutulan tüm geçmişi içine çekmez.

    Returns:
        Seçilen turlar, en eskiden başlayarak.
    """
    cap = max_turns if max_turns is not None else _DEFAULT_MAX_TURNS
    candidates = history[-cap:] if cap > 0 else []

    selected: list[dict[str, str]] = []
    spent = 0
    for turn in reversed(candidates):
        cost = count_tokens(turn.get("content", "") or "")
        if spent + cost > remaining_budget_tokens and len(selected) >= min_turns:
            break
        selected.append(turn)
        spent += cost

    selected.reverse()
    return selected
