# -*- coding: utf-8 -*-
"""Закрытие пришедших issues: PATCH /issues/<id> {status, note}. По фактам фиксов."""
import json
import urllib.request

BASE = "http://127.0.0.1:8000"

RES = {
    "47acdc11700f": ("fixed", "Робастный матчинг category (_norm + подстрока в обе стороны), "
                              "ретрай чтения дерева, categories[] в 400 никогда не пуст "
                              "(fallback на известные/канонические). Live: имя из categories[] "
                              "принимается; битое → 400 с 5 именами."),
    "df488837e3fc": ("fixed", "reset_for_search + сброс сессии на входе /search; "
                              "garbage-запрос → total=0/no_matches, старое не протекает."),
    "f501474bbd6d": ("fixed", "Неудачный /search очищает docs[]; /doc затем → 400 "
                              "index_out_of_range вместо чужого тела. Флаг ok согласован."),
    "c69df8c52d10": ("fixed", "/doc: ensure_doc_open + ретрай экспорта x3; пустой экспорт → "
                              "kind=unavailable, ok=false, retryable=true (не тихая маска)."),
    "329caa3df48d": ("fixed", "см. c69df8c52d10 — тот же ретрай+честный unavailable. "
                              "Live: content_len=774336 вместо 0."),
    "4ca163a98bc5": ("fixed", "/open выбирает документ по совпадению заголовка (enumerate + "
                              "поиск best-match), а не первый-попади; ретраит экспорт. "
                              "Live: content_len=705219 вместо ~100."),
    "464d28fea11c": ("fixed", "/sub ретраит, отдаёт kind/entries/href; при пустоте ok=false "
                              "retryable. Hint: пункт подборки через /open{href}."),
    "62ca9676535f": ("fixed", "rtf_util.extract_links отдаёт {ref,title,label,href}; "
                              "/doc,/open,/sub наполняют. Live: href/label присутствуют."),
    "cf37d556dbd5": ("fixed", "Эхо-заголовки (==query / 'Поиск:') отбрасываются из docs[]; "
                              "индексы континуальны 0..n."),
    "67fa1114261d": ("fixed", "Детерминированное правило: без category — первый лист в порядке "
                              "дерева; добавлены selection_rule и sections[] (что рассмотрено). "
                              "scope=single_section задокументирован в манифесте."),
    "04a148b531e7": ("fixed", "/health и /search несут index_as_of/last_update + note при запросе "
                              "позже среза. Поле задаётся оператором: env CONSULTANT_INDEX_AS_OF="
                              "ГГГГ-ММ-ДД (иначе 'unknown'). Auto-detect из «Актуально на…» — опция."),
    "d815c7bd9717": ("fixed", "GET / несёт categories[], selection_rule, index_as_of, link_fields."),
    "e917bda629fb": ("fixed", "/open принимает {ref}/{uri}: ref из ранее отданных links[] "
                              "разрешается через накопленную ref→title; неизвестный ref → 400 с "
                              "пояснением. href добавлен в links."),
    "385108b01f44": ("fixed", "Хранилище трекера на диске (data/issues/*.json) персистентно "
                              "за пределами процесса — заявки пережили рестарт сервера. Осенние "
                              "id относились к другому развёртыванию (старый IP 192.168.1.105)."),
}


def patch(iid, status, note):
    data = json.dumps({"status": status, "note": note}).encode("utf-8")
    req = urllib.request.Request(BASE + "/issues/" + iid, data=data, method="PATCH")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.loads(r.read().decode("utf-8"))
            return j["issue"]["status"]
    except Exception as e:  # noqa: BLE001
        return "ERR " + str(e)


def main():
    for iid, (st, note) in RES.items():
        got = patch(iid, st, note)
        print("%s -> %s" % (iid, got))
    print("PATCH_DONE count=%d" % len(RES))


if __name__ == "__main__":
    main()
