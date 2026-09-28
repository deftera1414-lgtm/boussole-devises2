"""Boussole Devises — moteur de marche : des prix reels vers des scores vivants.

Le biais affiche etait jusqu'ici un nombre ecrit a la main : il ne bougeait pas.
Ce script le recalcule a chaque passage a partir de quatre sources distinctes,
et ecrit le resultat dans currencies.json, d'ou pipeline.py le reprend pour les
huit cartes ET les vingt-huit paires.

  FONDAMENTAL    (32 %) — taux reel (taux directeur moins inflation) compare aux
      sept autres devises, orientation de la banque centrale, tendance du
      chomage et du PIB. Bouge quand les chiffres bougent.
  TECHNIQUE      (32 %) — indice de force de la devise contre les sept autres,
      construit sur les cours quotidiens : position contre moyennes mobiles
      50 et 200 jours, variation sur un mois, RSI, place dans le range annuel.
      Bouge tous les jours ouvres.
  POSITIONNEMENT (22 %) — ce que font reellement les grands speculateurs sur les
      contrats a terme de devises, d'apres le rapport hebdomadaire de la CFTC
      (Commitments of Traders) : position nette rapportee a l'interet ouvert,
      sa place dans les trois dernieres annees, et son evolution d'une semaine
      sur l'autre. C'est la mesure que citent les professionnels quand ils
      parlent du positionnement du marche.
  FLUX           (14 %) — effet des publications deja parues et penchant des
      echeances encore attendues cette semaine, calcules par collecte.py.

Si une composante manque (reseau coupe, serie absente), son poids est reparti
sur les autres : le score reste sur la meme echelle au lieu de s'affaisser
mecaniquement vers 50.

Les cours viennent de FRED (series H.10), meme hote et meme cle que le reste du
robot ; le positionnement vient de l'API publique de la CFTC, sans cle. Chaque
serie est verifiee avant usage (quotidienne, non discontinuee, observation
recente) ; une serie qui echoue laisse la devise inchangee plutot que de
produire un chiffre faux.
"""
import json, math, os, re, sys, datetime as dt
import urllib.request, urllib.parse

KEY = os.environ.get("FRED_API_KEY", "").strip()
FRED = "https://api.stlouisfed.org/fred"
NOS = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY"]
JOURS = 400          # profondeur d'historique demandee
COURBE = 90          # points de la courbe affichee
HIST = 60            # jours de memoire du biais

# (serie, sens) — sens = +1 si la serie monte quand la devise monte contre USD.
# DEXUSEU = dollars pour 1 euro : l'euro monte, le nombre monte -> +1.
# DEXJPUS = yens pour 1 dollar : le yen monte, le nombre baisse -> -1.
SERIES = {
    "EUR": ("DEXUSEU", +1), "GBP": ("DEXUSUK", +1),
    "AUD": ("DEXUSAL", +1), "NZD": ("DEXUSNZ", +1),
    "JPY": ("DEXJPUS", -1), "CHF": ("DEXSZUS", -1), "CAD": ("DEXCAUS", -1),
}
INDICE = {"EUR": "Euro", "GBP": "Pound", "AUD": "Australian", "NZD": "New Zealand",
          "JPY": "Yen", "CHF": "Swiss", "CAD": "Canadian"}

# Codes des contrats a terme de devises au CFTC (rapport « Legacy », futures
# seuls). L'indice dollar tient lieu de contrat pour l'USD.
COT = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
CONTRATS = {
    "EUR": ("099741", "EURO FX"), "GBP": ("096742", "BRITISH POUND"),
    "JPY": ("097741", "JAPANESE YEN"), "CHF": ("092741", "SWISS FRANC"),
    "CAD": ("090741", "CANADIAN DOLLAR"), "AUD": ("232741", "AUSTRALIAN DOLLAR"),
    "NZD": ("112741", "NZ DOLLAR"), "USD": ("098662", "USD INDEX"),
}
SEMAINES = 157       # trois ans de rapports hebdomadaires

# Poids de reference. Une composante absente voit son poids reparti sur les
# autres au prorata (voir melanger()).
POIDS = {"fondamental": 0.32, "technique": 0.32, "positionnement": 0.22, "flux": 0.14}

now = dt.datetime.now(dt.timezone.utc)
def log(m): print(m, flush=True)
def borne(v, a, b): return max(a, min(b, v))


# --------------------------------------------------------------------------
# Lecture FRED
# --------------------------------------------------------------------------
def fred(chemin, **p):
    p["api_key"] = KEY
    p["file_type"] = "json"
    url = FRED + "/" + chemin + "?" + urllib.parse.urlencode(p)
    rq = urllib.request.Request(url, headers={"User-Agent": "boussole-devises/5"})
    with urllib.request.urlopen(rq, timeout=30) as r:
        return json.load(r)


def serie_valide(sid, mot):
    """Quotidienne, vivante, et bien celle qu'on croit. C'est ce controle qui
    manquait en septembre, quand une serie discontinuee a ecrit des chiffres de
    2025 par-dessus des chiffres de 2026."""
    try:
        m = (fred("series", series_id=sid).get("seriess") or [None])[0]
    except Exception as e:
        log("    " + sid + " : metadonnees illisibles (" + str(e)[:70] + ")")
        return False
    if not m:
        return False
    titre = m.get("title", "")
    if "DISCONTINUED" in titre.upper():
        log("    " + sid + " : serie discontinuee")
        return False
    if m.get("frequency_short") != "D":
        log("    " + sid + " : frequence " + str(m.get("frequency_short")) + ", attendu quotidienne")
        return False
    if mot.lower() not in titre.lower():
        log("    " + sid + " : titre inattendu (" + titre[:60] + ")")
        return False
    try:
        fin = dt.date.fromisoformat(m.get("observation_end", ""))
    except ValueError:
        return False
    retard = (now.date() - fin).days
    if retard > 12:
        log("    " + sid + " : derniere observation il y a " + str(retard) + " jours")
        return False
    return True


def observations(sid):
    try:
        d = fred("series/observations", series_id=sid, sort_order="desc", limit=JOURS)
    except Exception as e:
        log("    " + sid + " : observations illisibles (" + str(e)[:70] + ")")
        return {}
    out = {}
    for o in d.get("observations", []):
        v = o.get("value")
        if v in (".", "", None):
            continue
        try:
            out[o["date"]] = float(v)
        except ValueError:
            continue
    return out


# --------------------------------------------------------------------------
# Statistiques techniques
# --------------------------------------------------------------------------
def moyenne(xs):
    return sum(xs) / float(len(xs)) if xs else None


def variation(serie, n):
    """Variation en % sur n seances."""
    if len(serie) <= n:
        return None
    a, b = serie[-1], serie[-1 - n]
    return None if not b else (a / b - 1.0) * 100.0


def rsi(serie, n=14):
    if len(serie) < n + 1:
        return None
    h = p = 0.0
    for i in range(len(serie) - n, len(serie)):
        d = serie[i] - serie[i - 1]
        if d >= 0:
            h += d
        else:
            p -= d
    if h + p == 0:
        return 50.0
    return 100.0 * h / (h + p)


def volatilite(serie, n=21):
    if len(serie) < n + 1:
        return None
    r = [math.log(serie[i] / serie[i - 1]) for i in range(len(serie) - n, len(serie))
         if serie[i - 1] > 0]
    if len(r) < 2:
        return None
    m = moyenne(r)
    v = sum((x - m) ** 2 for x in r) / (len(r) - 1)
    return math.sqrt(v) * math.sqrt(252) * 100.0


def technique(serie):
    """Score -10..+10 a partir de l'indice de force. Chaque composante est
    bornee separement pour qu'aucune ne puisse emporter le total a elle seule."""
    if len(serie) < 60:
        return None, {}
    s = serie[-1]
    ma50 = moyenne(serie[-50:])
    ma200 = moyenne(serie[-200:]) if len(serie) >= 200 else moyenne(serie)
    v21 = variation(serie, 21)
    r = rsi(serie)
    fen = serie[-252:] if len(serie) >= 252 else serie
    bas, haut = min(fen), max(fen)
    place = 50.0 if haut <= bas else (s - bas) / (haut - bas) * 100.0

    c = {}
    c["ma50"] = borne((s / ma50 - 1.0) * 100.0 / 2.0 * 10.0, -10, 10) if ma50 else 0.0
    c["ma200"] = borne((s / ma200 - 1.0) * 100.0 / 5.0 * 10.0, -10, 10) if ma200 else 0.0
    c["mois"] = borne(v21 / 3.0 * 10.0, -10, 10) if v21 is not None else 0.0
    c["rsi"] = borne((r - 50.0) / 5.0, -10, 10) if r is not None else 0.0
    c["range"] = borne((place - 50.0) / 5.0, -10, 10)
    t = (0.25 * c["ma50"] + 0.20 * c["ma200"] + 0.25 * c["mois"]
         + 0.15 * c["rsi"] + 0.15 * c["range"])
    detail = {
        "ma50_ecart": round((s / ma50 - 1.0) * 100.0, 2) if ma50 else None,
        "ma200_ecart": round((s / ma200 - 1.0) * 100.0, 2) if ma200 else None,
        "rsi": round(r, 1) if r is not None else None,
        "range_place": round(place),
        "volatilite": round(volatilite(serie) or 0.0, 1),
    }
    return borne(t, -10, 10), detail


# --------------------------------------------------------------------------
# Score fondamental
# --------------------------------------------------------------------------
NB = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def nombre(txt):
    """Moyenne des nombres trouves : « 3,75%–4,00% » -> 3.875."""
    v = []
    for m in NB.finditer(str(txt or "").replace("−", "-")):
        try:
            v.append(float(m.group().replace(",", ".")))
        except ValueError:
            pass
    return moyenne(v[:2]) if v else None


TILT = {"hawkish": 3.0, "neutral": 0.0, "dovish": -3.0}


def fondamental(cur):
    """Score -10..+10 par devise, comparatif : ce qui compte en change, c'est
    l'ecart entre deux devises, pas la valeur absolue d'un taux."""
    reels, brut = {}, {}
    for code in NOS:
        c = cur.get(code) or {}
        taux, infl = nombre(c.get("rate_current")), nombre(c.get("cpi_current"))
        if taux is not None and infl is not None:
            reels[code] = taux - infl
    if len(reels) >= 4:
        m = moyenne(list(reels.values()))
        ec = [abs(x - m) for x in reels.values()]
        disp = max(moyenne(ec) or 1.0, 0.3)
    else:
        m, disp = 0.0, 1.0

    for code in NOS:
        c = cur.get(code) or {}
        s = 0.0
        if code in reels:
            s += borne((reels[code] - m) / disp * 3.2, -6, 6)
        s += TILT.get(str(c.get("tilt", "")).lower(), 0.0)
        a, b = nombre(c.get("unemp_previous")), nombre(c.get("unemp_current"))
        if a is not None and b is not None:
            s += borne((a - b) * 4.0, -2, 2)          # chomage qui baisse : favorable
        a, b = nombre(c.get("gdp_previous")), nombre(c.get("gdp_current"))
        if a is not None and b is not None:
            s += borne((b - a) * 2.0, -2, 2)
        brut[code] = borne(s, -10, 10)
    return brut, reels


# --------------------------------------------------------------------------
# Positionnement des grands speculateurs (CFTC, Commitments of Traders)
# --------------------------------------------------------------------------
def cot(sid, nom):
    """Trois ans de position nette hebdomadaire, en % de l'interet ouvert.

    La position nette des « non-commerciaux » — fonds et gerants, par
    opposition aux industriels qui se couvrent — est la mesure que les
    professionnels citent pour dire ou est place l'argent speculatif.
    On la rapporte a l'interet ouvert pour que huit contrats de tailles tres
    differentes deviennent comparables entre eux.
    """
    p = {"cftc_contract_market_code": sid,
         "$select": ("report_date_as_yyyy_mm_dd,contract_market_name,"
                     "noncomm_positions_long_all,noncomm_positions_short_all,"
                     "open_interest_all"),
         "$order": "report_date_as_yyyy_mm_dd DESC",
         "$limit": str(SEMAINES)}
    url = COT + "?" + urllib.parse.urlencode(p)
    rq = urllib.request.Request(url, headers={"User-Agent": "boussole-devises/5"})
    with urllib.request.urlopen(rq, timeout=40) as r:
        d = json.load(r)
    serie = []
    for o in d:
        # Garde-fou : on refuse une ligne qui ne vient pas du contrat attendu.
        if nom not in str(o.get("contract_market_name", "")).upper():
            continue
        try:
            oi = float(o["open_interest_all"])
            lg = float(o["noncomm_positions_long_all"])
            ct = float(o["noncomm_positions_short_all"])
            jour = str(o["report_date_as_yyyy_mm_dd"])[:10]
            dt.date.fromisoformat(jour)
        except (KeyError, TypeError, ValueError):
            continue
        if oi <= 0:
            continue
        serie.append((jour, (lg - ct) / oi * 100.0))
    serie.sort()
    return serie


def positionnement(codes):
    """Score -10..+10 par devise, en deux lectures complementaires : ou en est
    le positionnement dans son historique de trois ans (60 %), et dans quel
    sens il a bouge d'une semaine sur l'autre (40 %)."""
    scores, detail = {}, {}
    for code in codes:
        sid, nom = CONTRATS.get(code, (None, None))
        if not sid:
            continue
        try:
            serie = cot(sid, nom)
        except Exception as e:
            log("    " + code + " : positionnement indisponible (" + str(e)[:70] + ")")
            continue
        if len(serie) < 26:
            log("    " + code + " : historique trop court (" + str(len(serie)) + " rapports)")
            continue
        jour, net = serie[-1]
        retard = (now.date() - dt.date.fromisoformat(jour)).days
        if retard > 21:
            log("    " + code + " : dernier rapport CFTC il y a " + str(retard) + " jours, ignore")
            continue
        vals = [v for _, v in serie]
        bas, haut = min(vals), max(vals)
        place = 50.0 if haut <= bas else (net - bas) / (haut - bas) * 100.0
        niveau = borne((place - 50.0) / 5.0, -10, 10)
        # Au-dela de 85 % du range de trois ans, le positionnement cesse d'etre
        # un appui : tout le monde est deja du meme cote, et le moindre
        # retournement force des sorties. On ecrete la lecture au lieu de la
        # pousser a l'extreme — c'est ainsi que les professionnels la lisent.
        if place > 85.0:
            niveau = 7.0 - (place - 85.0) / 15.0 * 4.0
        elif place < 15.0:
            niveau = -7.0 + (15.0 - place) / 15.0 * 4.0
        ecart = net - serie[-2][1]
        # un point d'interet ouvert bascule en une semaine : mouvement franc
        elan = borne(ecart * 4.0, -10, 10)
        scores[code] = borne(0.60 * niveau + 0.40 * elan, -10, 10)
        detail[code] = {"net_pct": round(net, 2), "place": round(place),
                        "var_hebdo": round(ecart, 2), "rapport": jour,
                        "semaines": len(serie)}
        log("  " + code + " : net %+.1f %% de l'interet ouvert · %d %% du range 3 ans · "
            "%+.2f pt sur la semaine  ->  %+.1f" % (net, place, ecart, scores[code]))
    return scores, detail


MOTEUR = {"fondamental": "les fondamentaux", "technique": "les graphiques",
          "positionnement": "le positionnement des grands spéculateurs",
          "flux": "l'actualité économique"}


def journal(lignes):
    """Consigne les mouvements de score dans le journal de la page. Meme format
    et meme fenetre de quatorze jours que le reste du robot."""
    if not lignes:
        return
    try:
        entries = json.load(open("changelog.json", encoding="utf-8")).get("entries", [])
    except Exception:
        entries = []
    if not isinstance(entries, list):
        entries = []
    jour = now.date().isoformat()
    cellule = next((e for e in entries if isinstance(e, dict) and e.get("date") == jour), None)
    if cellule is None:
        cellule = {"date": jour, "items": []}
        entries.insert(0, cellule)
    vues = set(cellule.get("items", []))
    for l in lignes:
        if l not in vues:
            cellule.setdefault("items", []).append(l)
            vues.add(l)
    lim = (now.date() - dt.timedelta(days=14)).isoformat()
    entries = [e for e in entries if isinstance(e, dict) and e.get("date", "") >= lim]
    entries.sort(key=lambda e: e.get("date", ""), reverse=True)
    json.dump({"entries": entries}, open("changelog.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    log("  journal : " + str(len(lignes)) + " mouvement(s) consigne(s).")


def melanger(parts):
    """Moyenne ponderee des composantes disponibles. Le poids d'une composante
    absente est reparti sur les autres au prorata, pour que le score garde la
    meme echelle au lieu de s'affaisser vers le neutre."""
    dispo = {k: v for k, v in parts.items() if v is not None}
    if not dispo:
        return 0.0, {}
    tot = sum(POIDS[k] for k in dispo)
    poids = {k: POIDS[k] / tot for k in dispo}
    return sum(poids[k] * dispo[k] for k in dispo), poids


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------
log("=== Moteur de marche — " + now.strftime("%d/%m/%Y %H:%M") + " UTC ===")
try:
    src = json.load(open("currencies.json", encoding="utf-8"))
    cur = src["currencies"]
except Exception as e:
    log("ERREUR : currencies.json illisible (" + str(e) + ")")
    sys.exit(1)

if not KEY:
    log("FRED_API_KEY absente — cours indisponibles, scores laisses en l'etat.")
    sys.exit(0)

# 1. cours quotidiens
usd = {"USD": None}
for code, (sid, sens) in SERIES.items():
    log("  " + code + " (" + sid + ")")
    if not serie_valide(sid, INDICE[code]):
        continue
    obs = observations(sid)
    if len(obs) < 60:
        log("    trop peu d'observations (" + str(len(obs)) + ")")
        continue
    usd[code] = {d: (v if sens > 0 else (1.0 / v if v else None)) for d, v in obs.items()}
    usd[code] = {d: v for d, v in usd[code].items() if v}
    log("    " + str(len(usd[code])) + " seances, derniere le " + max(usd[code]))

dispo = [c for c in SERIES if usd.get(c)]
if len(dispo) < 5:
    log("Moins de cinq devises cotees — on ne touche a rien.")
    sys.exit(0)

# dates communes a toutes les devises disponibles
dates = None
for c in dispo:
    d = set(usd[c])
    dates = d if dates is None else (dates & d)
dates = sorted(dates)[-JOURS:]
if len(dates) < 60:
    log("Historique commun trop court (" + str(len(dates)) + " seances).")
    sys.exit(0)
log("  Historique commun : " + str(len(dates)) + " seances, du " + dates[0] + " au " + dates[-1])

# 2. indice de force : chaque devise contre la moyenne geometrique des autres
panier = dispo + ["USD"]
force = {c: [] for c in panier}
for d in dates:
    val = {c: usd[c][d] for c in dispo}
    val["USD"] = 1.0
    g = math.exp(moyenne([math.log(v) for v in val.values()]))
    for c in panier:
        force[c].append(val[c] / g)
for c in panier:                                   # base 100 au depart
    b = force[c][0]
    force[c] = [x / b * 100.0 for x in force[c]]

# 3. scores
fond, reels = fondamental(cur)

# Flux : ce qui est deja paru compte plein tarif, ce qui est encore attendu
# d'ici dimanche compte a moitie — c'est une anticipation, pas un fait.
flux = {}
try:
    HL = json.load(open("highlights.json", encoding="utf-8"))
    for d in (HL.get("devises") or []):
        paru = float(d.get("effet") or 0.0)
        attendu = float(d.get("semaine_penchant") or 0.0)
        flux[d.get("code")] = paru + 0.5 * attendu
except Exception as e:
    log("  highlights.json illisible (" + str(e)[:60] + ") — flux neutre.")

log("  Positionnement des grands speculateurs (CFTC) :")
pos, pos_detail = positionnement(NOS)
if not pos:
    log("    aucune donnee — le poids du positionnement est reparti sur les autres composantes.")

try:
    hist = json.load(open("historique.json", encoding="utf-8"))
    if not isinstance(hist, dict):
        hist = {}
except Exception:
    hist = {}

jour = dates[-1]
sortie, touchees, mouvements = {}, 0, []
for code in NOS:
    if code not in force:
        continue
    t, detail = technique(force[code])
    if t is None:
        log("  " + code + " : serie trop courte, laisse en l'etat")
        continue
    f = fond.get(code, 0.0)
    x = borne(flux.get(code, 0.0) * 1.6, -10, 10)
    p = pos.get(code)
    total, util = melanger({"fondamental": f, "technique": t,
                            "positionnement": p, "flux": x})
    biais = int(round(borne(50 + 4.4 * total, 5, 95)))
    # Vue longue : on ne garde que les deux composantes lentes. L'ecart avec le
    # total dit si le court terme s'ecarte de la tendance de fond.
    longv = (0.68 * f + 0.32 * p) if p is not None else f
    ajust = int(round(borne(4.4 * (longv - total), -12, 12)))
    mom = int(round(borne(t, -10, 10)))

    c = cur.setdefault(code, {})
    avant = c.get("bias")
    c["bias"], c["momentum"], c["long_adj"] = biais, mom, ajust
    touchees += 1

    # Un mouvement de quatre points ou plus merite d'etre explique : on nomme
    # la composante qui pese le plus lourd dans le score du jour.
    if isinstance(avant, (int, float)) and abs(biais - avant) >= 4:
        pond = {k: util.get(k, 0.0) * v for k, v in
                (("fondamental", f), ("technique", t), ("positionnement", p), ("flux", x))
                if v is not None}
        ecart = biais - avant
        ligne = (code + " — biais " + str(int(avant)) + " → " + str(biais) + " (" +
                 ("+" if ecart > 0 else "") + str(ecart) + ")")
        if pond:
            ligne += ", porté par " + MOTEUR[max(pond, key=lambda k: abs(pond[k]))]
        mouvements.append(ligne)

    serie = force[code]
    pts = serie[-COURBE:]
    bas, haut = min(pts), max(pts)
    courbe = [round((v - bas) / (haut - bas) * 100.0, 1) if haut > bas else 50.0 for v in pts]

    h = [e for e in (hist.get(code) or []) if isinstance(e, list) and len(e) == 2]
    h = [e for e in h if e[0] != jour][-HIST:] + [[jour, biais]]
    hist[code] = h
    il_y_a_7 = None
    for e in reversed(h[:-1]):
        try:
            if (dt.date.fromisoformat(jour) - dt.date.fromisoformat(e[0])).days >= 7:
                il_y_a_7 = e[1]
                break
        except ValueError:
            pass

    sortie[code] = {
        "biais": biais, "biais_avant": avant, "biais_7j": il_y_a_7,
        "momentum": mom, "long_adj": ajust,
        "fondamental": round(f, 2), "technique": round(t, 2), "flux": round(x, 2),
        "positionnement": round(p, 2) if p is not None else None,
        "pos_detail": pos_detail.get(code),
        "poids": {k: round(v * 100) for k, v in util.items()},
        "taux_reel": round(reels[code], 2) if code in reels else None,
        "var": {"j1": variation(serie, 1), "j5": variation(serie, 5),
                "j21": variation(serie, 21), "j63": variation(serie, 63)},
        "detail": detail,
        "courbe": courbe,
    }
    for k in ("j1", "j5", "j21", "j63"):
        v = sortie[code]["var"][k]
        sortie[code]["var"][k] = round(v, 2) if v is not None else None
    log("  " + code + " : fond %+.1f  tech %+.1f  pos %s  flux %+.1f  ->  biais %d "
        "(avant %s), momentum %+d"
        % (f, t, ("%+.1f" % p) if p is not None else "  n/d", x, biais, avant, mom))

if not touchees:
    log("Aucune devise recalculee — fichiers laisses en l'etat.")
    sys.exit(0)

journal(mouvements)
json.dump(hist, open("historique.json", "w", encoding="utf-8"), ensure_ascii=False)
json.dump({
    "calcule_iso": now.replace(microsecond=0).isoformat(),
    "seance": jour, "seances": len(dates),
    "source": "Reserve federale (H.10) via FRED",
    "source_pos": "CFTC — Commitments of Traders, non-commerciaux, futures seuls",
    "rapport_cot": max((d["rapport"] for d in pos_detail.values()), default=None),
    "poids": {k: round(v * 100) for k, v in POIDS.items()},
    "devises": sortie,
}, open("marche.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

json.dump(src, open("currencies.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
log("marche.json ecrit — " + str(touchees) + " devise(s) recalculee(s) sur la seance du " + jour + ".")
