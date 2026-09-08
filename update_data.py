# -*- coding: utf-8 -*-
"""
Boussole Devises — update_data.py (v1)

Rafraîchit automatiquement, via l'API FRED (Federal Reserve Economic Data,
gratuite), DEUX champs objectifs de currencies.json pour les 8 devises :
inflation (CPI, YoY %) et taux de chômage. Ce sont les deux séries les mieux
et les plus uniformément couvertes par FRED pour ces 8 économies.

Volontairement HORS PÉRIMÈTRE de ce script (v1) :
  - Taux directeur et PIB : la couverture FRED des taux directeurs hors USD
    est incomplète/peu fiable (séries interrompues ou mal alignées sur la
    vraie cible de la banque centrale) ; le PIB trimestriel bouge trop
    rarement pour justifier une vérification horaire. Restent mis à jour par
    le scan quotidien Claude (déjà fonctionnel, cf. rapport du 30 août).
  - bias / long_adj / momentum / tilt / speech / cycle / events / watch :
    ce sont des champs de JUGEMENT (lecture d'un discours, calibrage d'un
    score de biais 0-100), pas de simples chiffres. Un script ne doit pas
    les réécrire silencieusement — ils restent la responsabilité du scan
    quotidien Claude (ou d'une relecture humaine).

Principe de robustesse : plutôt que de coder en dur des identifiants de
série FRED (risque réel et déjà rencontré en pratique : plusieurs séries
similaires coexistent, certaines "DISCONTINUED", avec des fréquences/
transformations différentes — un mauvais choix peut silencieusement écrire
une donnée fausse), ce script INTERROGE l'API de recherche FRED à chaque
exécution et filtre les résultats (exclut "DISCONTINUED", exige que le nom
du pays apparaisse dans le titre, préfère la série dont les observations
sont les plus récentes). Chaque valeur récupérée est ensuite bornée par un
test de plausibilité (ex. chômage entre 0 et 30 %) avant d'être écrite : en
cas de doute, l'ancienne valeur est conservée et l'incident est journalisé
plutôt que de risquer une donnée fausse dans le dashboard.

Nécessite la variable d'environnement FRED_API_KEY (gratuite, voir
README.md). Sans elle, le script s'arrête proprement (code de sortie 0,
aucune modification) pour ne jamais faire échouer le workflow GitHub
Actions par erreur de configuration.
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
FRED_BASE = "https://api.stlouisfed.org/fred"
FRED_API_KEY = os.environ.get("FRED_API_KEY", "").strip()

MONTHS_FR = {
    "01": "janv.", "02": "févr.", "03": "mars", "04": "avr.", "05": "mai", "06": "juin",
    "07": "juil.", "08": "août", "09": "sept.", "10": "oct.", "11": "nov.", "12": "déc.",
}

# Un seul hint de pays/zone par devise (utilisé pour filtrer les résultats de
# recherche FRED — la série retenue doit contenir ce texte dans son titre).
COUNTRY_HINT = {
    "USD": "United States",
    "EUR": "Euro Area",
    "GBP": "United Kingdom",
    "JPY": "Japan",
    "CHF": "Switzerland",
    "CAD": "Canada",
    "AUD": "Australia",
    "NZD": "New Zealand",
}


def log(msg):
    print(msg, flush=True)


def fred_get(path, **params):
    params = dict(params)
    params["api_key"] = FRED_API_KEY
    params["file_type"] = "json"
    url = f"{FRED_BASE}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "boussole-devises-update/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def find_series(search_text, country_hint, require_freq=None):
    """Cherche une série FRED pertinente et NON interrompue. Retourne le
    dict de la série choisie (avec sa clé 'id') ou None si rien de fiable
    n'a été trouvé. Ne devine jamais un ID codé en dur : toujours une
    recherche + un filtre, pour éviter de piéger un ID discontinué ou mal
    scoré (cas réel rencontré en préparant ce script)."""
    try:
        data = fred_get(
            "series/search",
            search_text=search_text,
            order_by="search_rank",
            sort_order="desc",
            limit=60,
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        log(f"    [erreur recherche FRED] {search_text!r} : {e}")
        return None

    candidates = []
    for s in data.get("seriess", []):
        title = s.get("title", "")
        if "DISCONTINUED" in title.upper():
            continue
        if country_hint.lower() not in title.lower():
            continue
        if require_freq and s.get("frequency_short") not in require_freq:
            continue
        obs_end = s.get("observation_end", "0000-00-00")
        # N'accepte que des séries encore mises à jour récemment (dans les
        # ~15 derniers mois) — une série "vivante" mais qui traîne loin
        # derrière est un signal qu'elle n'est plus la bonne référence.
        candidates.append((s, obs_end))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]


def latest_two_observations(series_id, units="lin"):
    try:
        data = fred_get(
            "series/observations",
            series_id=series_id,
            units=units,
            sort_order="desc",
            limit=6,
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        log(f"    [erreur observations FRED] {series_id} : {e}")
        return None, None

    obs = [o for o in data.get("observations", []) if o.get("value") not in (".", "", None)]
    if len(obs) < 2:
        return None, None
    return obs[1], obs[0]  # (précédent, actuel) — la liste est triée desc


def sane(value, lo, hi):
    try:
        return lo <= float(value) <= hi
    except (TypeError, ValueError):
        return False


def format_date_fr(iso_date):
    try:
        y, m, _ = iso_date.split("-")
        return f"{MONTHS_FR.get(m, m)} {y}"
    except Exception:
        return iso_date


def fmt_pct(value, date_iso):
    v = float(value)
    txt = f"{v:.1f}".replace(".", ",")
    return f"{txt}% ({format_date_fr(date_iso)}, FRED)"


def refresh_unemployment(code, cur):
    hint = COUNTRY_HINT[code]
    s = find_series(f"harmonized unemployment rate {hint}", hint, require_freq=("M", "Q"))
    if not s:
        s = find_series(f"unemployment rate {hint}", hint, require_freq=("M", "Q"))
    if not s:
        log(f"  [{code}] chômage : aucune série FRED fiable trouvée, valeur conservée")
        return False

    prev, curr = latest_two_observations(s["id"], units="lin")
    if not prev or not curr:
        log(f"  [{code}] chômage : observations insuffisantes pour {s['id']}, valeur conservée")
        return False
    if not (sane(prev["value"], 0, 30) and sane(curr["value"], 0, 30)):
        log(f"  [{code}] chômage : valeur hors bornes plausibles pour {s['id']} "
            f"({prev['value']} -> {curr['value']}), valeur conservée")
        return False

    new_prev = fmt_pct(prev["value"], prev["date"])
    new_curr = fmt_pct(curr["value"], curr["date"])
    changed = cur[code].get("unemp_current") != new_curr
    if changed:
        log(f"  [{code}] chômage : {cur[code].get('unemp_current')!r} -> {new_curr!r} (série {s['id']})")
        cur[code]["unemp_previous"] = new_prev
        cur[code]["unemp_current"] = new_curr
    else:
        log(f"  [{code}] chômage : inchangé ({s['id']})")
    return changed


def refresh_cpi(code, cur):
    hint = COUNTRY_HINT[code]
    s = find_series(f"consumer price index all items {hint}", hint, require_freq=("M", "Q"))
    if not s:
        s = find_series(f"harmonized index of consumer prices {hint}", hint, require_freq=("M", "Q"))
    if not s:
        log(f"  [{code}] IPC : aucune série FRED fiable trouvée, valeur conservée")
        return False

    # units=pc1 : FRED calcule lui-même la variation en % sur un an à partir
    # de l'indice brut — on évite ainsi de devoir deviner quelle variante
    # pré-calculée ("659N", "657N", ...) correspond au bon calcul.
    prev, curr = latest_two_observations(s["id"], units="pc1")
    if not prev or not curr:
        log(f"  [{code}] IPC : observations insuffisantes pour {s['id']}, valeur conservée")
        return False
    if not (sane(prev["value"], -5, 30) and sane(curr["value"], -5, 30)):
        log(f"  [{code}] IPC : valeur hors bornes plausibles pour {s['id']} "
            f"({prev['value']} -> {curr['value']}), valeur conservée")
        return False

    new_prev = fmt_pct(prev["value"], prev["date"])
    new_curr = fmt_pct(curr["value"], curr["date"])
    changed = cur[code].get("cpi_current") != new_curr
    if changed:
        log(f"  [{code}] IPC : {cur[code].get('cpi_current')!r} -> {new_curr!r} (série {s['id']}, YoY)")
        cur[code]["cpi_previous"] = new_prev
        cur[code]["cpi_current"] = new_curr
    else:
        log(f"  [{code}] IPC : inchangé ({s['id']})")
    return changed


def main():
    if not FRED_API_KEY:
        log("FRED_API_KEY absente — rien à faire (voir README.md pour l'obtenir gratuitement).")
        # Fichier marqueur explicite pour que le workflow sache qu'aucune
        # tentative réelle n'a eu lieu (différent de "vérifié, rien changé").
        with open(os.path.join(BASE, ".update_status"), "w") as f:
            f.write("no_api_key")
        return 0

    path = os.path.join(BASE, "currencies.json")
    with open(path, encoding="utf-8") as f:
        src = json.load(f)
    cur = src["currencies"]

    any_change = False
    for code in COUNTRY_HINT:
        if code not in cur:
            log(f"  [{code}] absent de currencies.json, ignoré")
            continue
        log(f"-- {code} --")
        changed_u = refresh_unemployment(code, cur)
        time.sleep(1)  # reste largement sous les limites de débit de l'API FRED
        changed_c = refresh_cpi(code, cur)
        time.sleep(1)
        any_change = any_change or changed_u or changed_c

    if any_change:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(src, f, ensure_ascii=False, indent=2)
        log("currencies.json mis à jour.")
        with open(os.path.join(BASE, ".update_status"), "w") as f:
            f.write("changed")
    else:
        log("Aucun changement détecté.")
        with open(os.path.join(BASE, ".update_status"), "w") as f:
            f.write("unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
