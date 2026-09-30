"""Boussole Devises — moteur de marche : des prix reels vers des scores vivants.

Le biais affiche etait jusqu'ici un nombre ecrit a la main : il ne bougeait pas.
Ce script le recalcule a chaque passage a partir de quatre sources distinctes,
et ecrit le resultat dans currencies.json, d'ou pipeline.py le reprend pour les
huit cartes ET les vingt-huit paires.

  FONDAMENTAL    (38 %) — huit moteurs, chacun ramene a la moyenne du panier :
      portage reel (taux directeur moins inflation, rapporte a la volatilite),
      impulsion de politique (la banque resserre-t-elle plus vite que
      l'inflation ne monte ?), ecart d'inflation a la cible et sens du
      mouvement, ton et dernier geste de la banque centrale corriges par les
      chiffres, croissance et emploi ramenes a la meme unite, anticipations de
      taux americains (2 ans sur un mois), termes de l'echange (brut WTI),
      regime de risque (VIX et prime de credit). Le nombre de moteurs qui
      s'accordent sert de mesure de confiance.
  TECHNIQUE      (26 %) — indice de force de la devise contre les sept autres,
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
POIDS = {"fondamental": 0.38, "technique": 0.26, "positionnement": 0.22, "flux": 0.14}

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


def serie_mensuelle(sid, mot, retard_max=110):
    """Meme controle, pour une serie mensuelle. La BIS publie ses taux de
    change effectifs reels avec deux mois de decalage : c'est sans importance
    pour un signal de valorisation, qui se mesure en annees."""
    try:
        m = (fred("series", series_id=sid).get("seriess") or [None])[0]
    except Exception as e:
        log("    " + sid + " : metadonnees illisibles (" + str(e)[:70] + ")")
        return False
    if not m or "DISCONTINUED" in m.get("title", "").upper():
        return False
    if m.get("frequency_short") != "M":
        log("    " + sid + " : frequence " + str(m.get("frequency_short")) + ", attendu mensuelle")
        return False
    if mot.lower() not in m.get("title", "").lower():
        log("    " + sid + " : titre inattendu (" + m.get("title", "")[:60] + ")")
        return False
    try:
        fin = dt.date.fromisoformat(m.get("observation_end", ""))
    except ValueError:
        return False
    if (now.date() - fin).days > retard_max:
        log("    " + sid + " : derniere observation il y a " + str((now.date() - fin).days) + " jours")
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
# Les chiffres sont ranges dans des phrases : « 3,4% (aout 2026, stable) ;
# coeur en repli a 2,4% ». Lire « le premier nombre » ou « la moyenne des deux
# premiers » ramenait l'annee (2026) ou un rang (« 2e estimation ») et donnait
# une inflation de 1014,7 % : tout le score fondamental en dependait.
# On lit donc le premier POURCENTAGE, et lui seul.
PCT = re.compile(r"([-+]?\d+(?:[.,]\d+)?)\s*%")
PLAGE = re.compile(r"([-+]?\d+(?:[.,]\d+)?)\s*%?\s*[–—-]\s*([-+]?\d+(?:[.,]\d+)?)\s*%")
NU = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def dec(s):
    return float(str(s).replace(",", "."))


def nombre(txt):
    """Le premier pourcentage du texte. Une fourchette accolee au premier
    chiffre (« 3,75%-4,00% ») est moyennee ; tout nombre plus loin dans la
    phrase est du commentaire et n'est pas lu."""
    t = str(txt or "").replace("−", "-")
    m = PCT.search(t)
    if m:
        p = PLAGE.match(t, m.start())
        return (dec(p.group(1)) + dec(p.group(2))) / 2.0 if p else dec(m.group(1))
    for m in NU.finditer(t):                     # repli : aucun pourcentage
        v = dec(m.group())
        if not (1900 <= v <= 2100):              # ce n'est pas une annee
            return v
    return None


def annualise(txt):
    """Les PIB ne sont pas donnes dans la meme unite selon les pays : +3,3 %
    annualise vaut +0,8 % trimestriel. Sans ce reperage, le Canada et les
    Etats-Unis ecrasaient l'Europe."""
    return "annualis" in str(txt or "").lower()


def ecart_type(xs):
    if len(xs) < 2:
        return None
    m = moyenne(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def centrer(d, defaut=0.0):
    """Ramene un dictionnaire de valeurs a sa moyenne. En change, seul l'ecart
    entre devises a un sens : un mouvement commun aux huit ne dit rien."""
    vals = [v for v in d.values() if v is not None]
    if len(vals) < 3:
        return {k: defaut for k in d}
    m = moyenne(vals)
    return {k: (v - m if v is not None else defaut) for k, v in d.items()}


TILT = {"hawkish": 3.0, "neutral": 0.0, "dovish": -3.0}
GESTE = {"hike": 1.5, "cut": -1.5, "hold": 0.0}

# Effet d'une hausse du brut sur chaque devise. Le Canada exporte du brut, le
# Japon importe la quasi-totalite de son energie ; entre les deux, l'Australie
# vend du gaz et du charbon, la zone euro et la Suisse achetent tout.
PETROLE = {"CAD": 1.0, "AUD": 0.5, "USD": 0.15, "GBP": -0.1,
           "NZD": -0.2, "CHF": -0.4, "EUR": -0.5, "JPY": -0.9}

# Comportement en regime de tension. Dollar, yen et franc sont recherches quand
# le risque monte ; dollars australien et neo-zelandais sont vendus les premiers.
REFUGE = {"JPY": 1.0, "CHF": 0.9, "USD": 0.6, "EUR": -0.1,
          "GBP": -0.4, "CAD": -0.4, "AUD": -0.9, "NZD": -1.0}

# Le taux a deux ans americain est la boussole des taux mondiaux : quand il se
# reevalue, le dollar bouge contre tout le reste. Aucune serie equivalente n'est
# disponible quotidiennement et gratuitement pour les sept autres pays, alors on
# lit ce moteur pour ce qu'il est : le dollar contre le panier.
TAUX_US = {"USD": 1.0, "EUR": -1 / 7.0, "GBP": -1 / 7.0, "JPY": -1 / 7.0,
           "CHF": -1 / 7.0, "CAD": -1 / 7.0, "AUD": -1 / 7.0, "NZD": -1 / 7.0}

# Taux de change effectifs reels de la BIS, mensuels : la mesure de reference
# pour savoir si une devise est chere ou bon marche par rapport a son histoire.
# C'est le troisieme pilier classique du change, avec le portage et le momentum.
REER = {"USD": "RBUSBIS", "EUR": "RBXMBIS", "GBP": "RBGBBIS", "JPY": "RBJPBIS",
        "CHF": "RBCHBIS", "CAD": "RBCABIS", "AUD": "RBAUBIS", "NZD": "RBNZBIS"}
REER_FENETRE = 120        # dix ans de moyenne de reference

# Les neuf moteurs et leur poids dans le score fondamental.
MOTEURS = [
    ("taux_reel", "le portage réel", 20),
    ("impulsion", "l'impulsion de politique", 16),
    ("valeur", "la valorisation de long terme", 12),
    ("inflation", "l'écart d'inflation à la cible", 12),
    ("ton", "le ton et le geste de la banque centrale", 12),
    ("croissance", "la croissance et l'emploi", 10),
    ("taux_us", "les anticipations de taux américains", 8),
    ("commerce", "les termes de l'échange", 6),
    ("risque", "le régime de risque", 4),
]


def fondamental(cur, petrole=None, tension=None, vols=None, reprise=None, cherte=None):
    """Huit moteurs explicites, chacun ramene a la moyenne du panier : en
    change, ce qui deplace un cours est l'ecart entre deux economies, pas la
    valeur absolue d'un taux. Chaque moteur est borne separement pour qu'aucun
    ne puisse emporter le total a lui seul.

    Retourne (scores -10..+10, taux reels, detail par moteur et accord).
    """
    lu = {}
    for code in NOS:
        c = cur.get(code) or {}
        lu[code] = {
            "taux": nombre(c.get("rate_current")), "taux0": nombre(c.get("rate_previous")),
            "ipc": nombre(c.get("cpi_current")), "ipc0": nombre(c.get("cpi_previous")),
            "cible": c.get("cpi_target"), "chom": nombre(c.get("unemp_current")),
            "chom0": nombre(c.get("unemp_previous")), "pib": nombre(c.get("gdp_current")),
            "pib0": nombre(c.get("gdp_previous")),
            "ann": annualise(c.get("gdp_current")) and annualise(c.get("gdp_previous")),
            "ton": str(c.get("tilt", "")).lower(), "geste": str(c.get("move", "")).lower(),
        }

    # 1. portage reel : taux directeur moins inflation, rapporte au risque.
    #    Un taux reel de 2 % sur une devise deux fois plus volatile ne vaut pas
    #    deux fois mieux qu'un taux reel de 1 % sur une devise calme : c'est le
    #    rapport entre les deux que regardent les gerants.
    reels = {k: (v["taux"] - v["ipc"]) for k, v in lu.items()
             if v["taux"] is not None and v["ipc"] is not None}
    port = {}
    for k, v in reels.items():
        sd = (vols or {}).get(k)
        port[k] = v / max(sd / 8.0, 0.5) if sd else v   # 8 % : volatilite usuelle
    s1 = {}
    if len(port) >= 4:
        m, sd = moyenne(list(port.values())), ecart_type(list(port.values()))
        sd = max(sd or 1.0, 0.25)
        s1 = {k: borne((v - m) / sd * 3.0, -6, 6) for k, v in port.items()}

    # 2. impulsion : la banque resserre-t-elle plus vite que l'inflation ne monte ?
    imp = {}
    for k, v in lu.items():
        if None in (v["taux"], v["taux0"], v["ipc"], v["ipc0"]):
            continue
        imp[k] = (v["taux"] - v["taux0"]) - (v["ipc"] - v["ipc0"])
    s2 = {k: borne(x * 4.0, -6, 6) for k, x in centrer(imp).items()} if len(imp) >= 3 else {}

    # 3. inflation : distance a la cible, et sens du mouvement
    pres, s3 = {}, {}
    for k, v in lu.items():
        if v["ipc"] is None or v["cible"] is None:
            continue
        d = (v["ipc"] - v["ipc0"]) if v["ipc0"] is not None else 0.0
        pres[k] = 0.7 * (v["ipc"] - float(v["cible"])) + 1.5 * d
    if len(pres) >= 3:
        s3 = {k: borne(x * 2.0, -6, 6) for k, x in centrer(pres).items()}

    # 4. ton : les mots, corriges par les chiffres, plus le dernier geste.
    #    Centre lui aussi : quand sept banques sur huit parlent de fermete,
    #    la fermete ne distingue plus personne.
    s4 = {}
    for k, v in lu.items():
        if v["ton"] not in TILT and v["geste"] not in GESTE:
            continue                  # rien de renseigne : le moteur se retire
        t = TILT.get(v["ton"], 0.0)
        p = pres.get(k)
        # Un discours de fermete que l'inflation ne justifie pas ne tient pas.
        if p is not None and t and ((t > 0 and p < -0.3) or (t < 0 and p > 0.3)):
            t *= 0.4
        s4[k] = t + GESTE.get(v["geste"], 0.0)
    s4 = {k: borne(x, -6, 6) for k, x in centrer(s4).items()} if len(s4) >= 3 else {}

    # 5. croissance et emploi, ramenes a la meme unite
    cro, s5 = {}, {}
    for k, v in lu.items():
        x, n = 0.0, 0
        if v["pib"] is not None and v["pib0"] is not None:
            d = v["pib"] - v["pib0"]
            x += 2.0 * (d / 4.0 if v["ann"] else d)      # annualise -> trimestriel
            n += 1
        if v["chom"] is not None and v["chom0"] is not None:
            x += 3.0 * (v["chom0"] - v["chom"])          # chomage qui baisse : favorable
            n += 1
        if n:
            cro[k] = x
    if len(cro) >= 3:
        s5 = {k: borne(x, -5, 5) for k, x in centrer(cro).items()}

    # 6. valorisation : ecart du taux de change effectif reel a sa moyenne de
    #    dix ans. Une devise chere finit par revenir ; c'est lent, mais c'est
    #    la seule ancre de long terme qui existe en change.
    s9 = {}
    if cherte:
        s9 = {k: borne(x, -6, 6) for k, x in
              centrer({k: -v / 10.0 * 3.0 for k, v in cherte.items()}).items()}

    # 7. anticipations de taux americains : le 2 ans sur un mois, en points de base
    s6 = {}
    if reprise is not None:
        s6 = {k: borne(x, -5, 5) for k, x in
              centrer({k: reprise / 25.0 * 3.0 * c for k, c in TAUX_US.items()}).items()}

    # 8. termes de l'echange : le brut sur trois mois
    s7 = {}
    if petrole is not None:
        s7 = {k: borne(x, -4, 4) for k, x in
              centrer({k: petrole / 12.0 * c for k, c in PETROLE.items()}).items()}

    # 9. regime de risque : volatilite des actions et prime de credit
    s8 = {}
    if tension is not None:
        s8 = {k: borne(x, -4, 4) for k, x in
              centrer({k: tension * c * 1.6 for k, c in REFUGE.items()}).items()}

    table = {"taux_reel": s1, "impulsion": s2, "valeur": s9, "inflation": s3,
             "ton": s4, "croissance": s5, "taux_us": s6, "commerce": s7, "risque": s8}
    brut, detail = {}, {}
    for code in NOS:
        parts = {cle: table[cle].get(code) for cle, _, _ in MOTEURS}
        poids = {cle: p for cle, _, p in MOTEURS if parts.get(cle) is not None}
        if not poids:
            continue
        tot = float(sum(poids.values()))
        apport = {k: poids[k] / tot * parts[k] * 3.0 for k in poids}
        total = borne(sum(apport.values()), -10, 10)
        brut[code] = total
        # Combien de moteurs tirent dans le sens du total ? C'est la seule
        # mesure honnete de confiance : un score de +4 sur lequel six moteurs
        # sur huit s'accordent ne vaut pas un +4 arrache par un seul.
        vus = [v for v in apport.values() if abs(v) >= 0.05]
        accord = sum(1 for v in vus if (v > 0) == (total >= 0))
        detail[code] = {k: round(v, 2) for k, v in parts.items() if v is not None}
        detail[code]["apport"] = {k: round(v, 2) for k, v in apport.items()}
        detail[code]["accord"] = [accord, len(vus)]
    return brut, reels, detail


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
    scores, detail, brutes = {}, {}, {}
    for code in codes:
        sid, nom = CONTRATS.get(code, (None, None))
        if not sid:
            continue
        try:
            serie = cot(sid, nom)
        except Exception as e:
            log("    " + code + " : positionnement indisponible (" + str(e)[:70] + ")")
            continue
        brutes[code] = serie
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

    # Comme pour le fondamental, ce qui compte en change est l'ecart entre
    # devises. Le marche a terme est structurellement vendeur de presque toutes
    # les devises contre dollar : cette pente commune fait plonger huit scores
    # a la fois sans rien dire sur laquelle preferer. On la retire.
    if len(scores) >= 4:
        m = moyenne(list(scores.values()))
        for code in scores:
            scores[code] = borne(scores[code] - m, -10, 10)
            detail[code]["relatif"] = round(scores[code], 2)
        log("  moyenne du panier %+.1f, retiree a chacun : il reste l'ecart entre devises." % m)
    return scores, detail, brutes


# --------------------------------------------------------------------------
# Mesure : le modele a-t-il raison ?
# --------------------------------------------------------------------------
def rang(xs):
    """Rangs moyens, ex aequo compris — pour une correlation de Spearman."""
    ordre = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(ordre):
        j = i
        while j + 1 < len(ordre) and xs[ordre[j + 1]] == xs[ordre[i]]:
            j += 1
        moy = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            r[ordre[k]] = moy
        i = j + 1
    return r


def correlation(a, b):
    if len(a) < 3 or len(a) != len(b):
        return None
    ma, mb = moyenne(a), moyenne(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (da * db) if da > 0 and db > 0 else None


def spearman(a, b):
    return correlation(rang(a), rang(b))


def note(paires, seuil=1.0):
    """Coefficient d'information et taux de reussite d'un signal.

    Le coefficient d'information est la correlation de rang entre le score
    annonce et le rendement qui a suivi : c'est la mesure que tout gerant
    quantitatif exige avant d'accorder un poids a un signal. Au-dela de 0,03
    il est considere comme exploitable, au-dela de 0,05 comme bon.
    Le taux de reussite ne compte que les signaux assez nets pour etre suivis.
    """
    if len(paires) < 12:
        return None
    s = [p[0] for p in paires]
    r = [p[1] for p in paires]
    nets = [p for p in paires if abs(p[0]) >= seuil]
    juste = sum(1 for x, y in nets if (x > 0) == (y > 0))
    ic = spearman(s, r)
    return {"ic": round(ic, 3) if ic is not None else None,
            "n": len(paires),
            "reussite": round(100.0 * juste / len(nets)) if nets else None,
            "n_nets": len(nets)}


def eprouver_technique(force, dates, horizons=(5, 21)):
    """Rejoue le score technique dans le passe et le confronte au rendement
    qui a suivi. Aucune donnee future n'entre dans le calcul du score : a la
    date t, seul force[:t+1] est lu. Les fenetres ne se chevauchent pas."""
    out = {}
    for h in horizons:
        paires = []
        for c, serie in force.items():
            t = 260
            while t + h < len(serie):
                sc, _ = technique(serie[:t + 1])
                if sc is not None and serie[t]:
                    paires.append((sc, (serie[t + h] / serie[t] - 1.0) * 100.0))
                t += h
        r = note(paires)
        if r:
            out[str(h) + "j"] = r
    return out


def eprouver_positionnement(cots, force, dates, semaines=(1, 4)):
    """Meme exercice pour le positionnement des speculateurs. Le rapport de la
    CFTC arrete les positions le mardi et parait le vendredi : on ne mesure le
    rendement qu'a partir du vendredi suivant, jamais avant."""
    index = {d: i for i, d in enumerate(dates)}

    def apres(jour, decalage=3):
        try:
            d = dt.date.fromisoformat(jour) + dt.timedelta(days=decalage)
        except ValueError:
            return None
        for _ in range(8):
            if d.isoformat() in index:
                return index[d.isoformat()]
            d += dt.timedelta(days=1)
        return None

    out = {}
    for sem in semaines:
        paires = []
        for c, serie in cots.items():
            if c not in force or len(serie) < 40:
                continue
            for t in range(26, len(serie) - sem, sem):
                vals = [v for _, v in serie[:t + 1]]
                bas, haut = min(vals), max(vals)
                net = vals[-1]
                place = 50.0 if haut <= bas else (net - bas) / (haut - bas) * 100.0
                niveau = borne((place - 50.0) / 5.0, -10, 10)
                if place > 85.0:
                    niveau = 7.0 - (place - 85.0) / 15.0 * 4.0
                elif place < 15.0:
                    niveau = -7.0 + (15.0 - place) / 15.0 * 4.0
                sc = borne(0.60 * niveau + 0.40 * borne((net - vals[-2]) * 4.0, -10, 10), -10, 10)
                i0 = apres(serie[t][0])
                i1 = apres(serie[t + sem][0]) if t + sem < len(serie) else None
                if i0 is None or i1 is None or i1 <= i0 or not force[c][i0]:
                    continue
                paires.append((sc, (force[c][i1] / force[c][i0] - 1.0) * 100.0))
        r = note(paires)
        if r:
            out[str(sem) + "sem"] = r
    return out


def eprouver_biais(hist, force, dates, horizons=(5, 21)):
    """Le seul vrai hors echantillon : les biais reellement publies, tels
    qu'ils ont ete ecrits jour apres jour dans historique.json, confrontes a
    ce qui s'est passe ensuite."""
    index = {d: i for i, d in enumerate(dates)}
    out = {}
    for h in horizons:
        paires = []
        for c, lignes in (hist or {}).items():
            if c not in force:
                continue
            for jour, biais in lignes:
                i = index.get(jour)
                if i is None or i + h >= len(force[c]) or not force[c][i]:
                    continue
                paires.append((float(biais) - 50.0,
                               (force[c][i + h] / force[c][i] - 1.0) * 100.0))
        r = note(paires, seuil=5.0)
        if r:
            out[str(h) + "j"] = r
    return out


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

# 3. contexte macro : brut et tension, deux series quotidiennes de plus
def serie_macro(sid, mot):
    if not serie_valide(sid, mot):
        return None
    obs = observations(sid)
    if len(obs) < 120:
        log("    " + sid + " : trop peu d'observations (" + str(len(obs)) + ")")
        return None
    return [obs[d] for d in sorted(obs)]


def cote_z(s, nom):
    """Ou en est la derniere valeur par rapport a sa propre annee."""
    if not s:
        return None
    fen = s[-252:]
    sd = ecart_type(fen)
    if not sd or sd <= 0:
        return None
    z = borne((s[-1] - moyenne(fen)) / sd, -2.5, 2.5)
    log("    " + nom + " %.2f, soit %+.2f ecart-type de son annee" % (s[-1], z))
    return z


petrole = tension = reprise = None
log("  Contexte macro :")
s = serie_macro("DCOILWTICO", "West Texas")
if s and len(s) > 63 and s[-64]:
    petrole = (s[-1] / s[-64] - 1.0) * 100.0
    log("    brut WTI %.2f $, %+.1f %% sur trois mois" % (s[-1], petrole))

# Deux mesures independantes du meme regime : la volatilite des actions et la
# prime exigee sur le credit risque. Les moyenner rend le signal moins fragile
# qu'un VIX seul, qui peut bouger pour des raisons techniques.
zs = [z for z in (cote_z(serie_macro("VIXCLS", "Volatility"), "VIX"),
                  cote_z(serie_macro("BAMLH0A0HYM2", "High Yield"), "prime de credit"))
      if z is not None]
if zs:
    tension = moyenne(zs)
    log("    regime de risque : %+.2f (%d mesure%s)" % (tension, len(zs), "s" if len(zs) > 1 else ""))

s = serie_macro("DGS2", "2-Year")
if s and len(s) > 21:
    reprise = (s[-1] - s[-22]) * 100.0          # en points de base
    log("    taux 2 ans americain %.2f %%, %+.0f pb sur un mois" % (s[-1], reprise))

if petrole is None and tension is None and reprise is None:
    log("    indisponible — les moteurs correspondants sont neutralises.")

# 4. volatilite realisee de chaque devise, pour rapporter le portage au risque
vols = {}
for c in panier:
    v = volatilite(force[c])
    if v and v > 0:
        vols[c] = v
if vols:
    log("  Volatilite annualisee : " + ", ".join("%s %.1f %%" % (k, vols[k])
                                                 for k in sorted(vols)))

# 5. valorisation : ecart du taux de change effectif reel a sa moyenne longue
cherte = {}
log("  Valorisation (taux de change effectifs reels, BIS) :")
for code, sid in REER.items():
    if not serie_mensuelle(sid, "Effective Exchange Rate"):
        continue
    obs = observations(sid)
    if len(obs) < 60:
        continue
    s = [obs[d] for d in sorted(obs)]
    ref = moyenne(s[-REER_FENETRE:])
    if ref:
        cherte[code] = (s[-1] / ref - 1.0) * 100.0
if cherte:
    log("    " + ", ".join("%s %+.1f %%" % (k, cherte[k]) for k in sorted(cherte)))
else:
    log("    indisponible — le moteur de valorisation est neutralise.")

# 6. scores
fond, reels, fond_detail = fondamental(cur, petrole, tension, vols, reprise, cherte)

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
pos, pos_detail, cots = positionnement(NOS)
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
        "fond_detail": fond_detail.get(code),
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

# --------------------------------------------------------------------------
# Ce que le chiffre vaut : amplitude, conviction, redondance, performance
# --------------------------------------------------------------------------
# Un biais est une direction, pas une taille. Meme un tres bon signal de change
# n'annonce qu'une fraction d'ecart-type : on le dit, avec l'ecart-type en face,
# pour que personne ne prenne 66 % pour une promesse.
FRACTION = 0.45          # part d'un ecart-type qu'un biais maximal revendique
for code, d in sortie.items():
    v = vols.get(code)
    if not v:
        continue
    sigma = v * math.sqrt(5.0 / 252.0)                    # ecart-type a cinq jours
    d["attendu_5j"] = round((d["biais"] - 50) / 45.0 * FRACTION * sigma, 3)
    d["sigma_5j"] = round(sigma, 2)

# Deux devises qui bougent ensemble ne font qu'une position. On le signale.
rends = {}
for c in panier:
    s = force[c][-91:]
    if len(s) > 30:
        rends[c] = [math.log(s[i] / s[i - 1]) for i in range(1, len(s)) if s[i - 1] > 0]
for code in sortie:
    voisins = []
    for autre in rends:
        if autre == code or code not in rends:
            continue
        r = correlation(rends[code], rends[autre])
        if r is not None:
            voisins.append((abs(r), autre, round(r, 2)))
    if voisins:
        voisins.sort(reverse=True)
        sortie[code]["jumelle"] = {"code": voisins[0][1], "correlation": voisins[0][2]}

# Les paires ou le modele est le mieux soutenu : grand ecart de biais, moteurs
# d'accord des deux cotes, et un ecart qui depasse le bruit de la paire.
convictions = []
codes = [c for c in NOS if c in sortie]
for i, a in enumerate(codes):
    for b in codes[i + 1:]:
        da, db = sortie[a], sortie[b]
        ecart = da["biais"] - db["biais"]
        haut, bas = (a, b) if ecart >= 0 else (b, a)
        aa = (da.get("fond_detail") or {}).get("accord") or [0, 1]
        ab = (db.get("fond_detail") or {}).get("accord") or [0, 1]
        soutien = min(aa[0] / float(aa[1] or 1), ab[0] / float(ab[1] or 1))
        att = (da.get("attendu_5j") or 0.0) - (db.get("attendu_5j") or 0.0)
        va, vb = vols.get(a, 8.0), vols.get(b, 8.0)
        rho = correlation(rends.get(a, []), rends.get(b, [])) if a in rends and b in rends else 0.0
        vp = math.sqrt(max(va * va + vb * vb - 2.0 * (rho or 0.0) * va * vb, 1.0))
        sigma_p = vp * math.sqrt(5.0 / 252.0)
        convictions.append({
            "paire": haut + "/" + bas,
            "ecart": abs(ecart),
            "soutien": round(soutien, 2),
            "attendu_5j": round(abs(att), 2),
            "sigma_5j": round(sigma_p, 2),
            "rapport": round(abs(att) / sigma_p, 2) if sigma_p else None,
            "score": round(abs(ecart) * soutien, 1),
        })
convictions.sort(key=lambda x: x["score"], reverse=True)
convictions = convictions[:5]

# Les devises qui bougent le plus ensemble : les acheter toutes les deux, c'est
# prendre deux fois le meme risque.
grappes = []
for i, a in enumerate(codes):
    for b in codes[i + 1:]:
        if a in rends and b in rends:
            r = correlation(rends[a], rends[b])
            if r is not None:
                grappes.append((abs(r), a, b, round(r, 2)))
grappes.sort(reverse=True)
grappes = [{"a": a, "b": b, "correlation": r} for _, a, b, r in grappes[:3]]
if convictions:
    log("  Meilleures convictions : " + " · ".join(
        "%s ecart %d, %d %% de moteurs d'accord" % (c["paire"], c["ecart"], round(c["soutien"] * 100))
        for c in convictions[:3]))

# --------------------------------------------------------------------------
# Le modele a-t-il raison ? On le mesure, on ne le decrete pas.
# --------------------------------------------------------------------------
log("  Mesure de performance :")
mesure = {}
try:
    mesure["technique"] = eprouver_technique({c: force[c] for c in sortie}, dates)
    for h, r in (mesure["technique"] or {}).items():
        log("    technique a %s : IC %s, reussite %s %% sur %d observations"
            % (h, r["ic"], r["reussite"], r["n"]))
except Exception as e:
    log("    technique : mesure impossible (" + str(e)[:60] + ")")
try:
    mesure["positionnement"] = eprouver_positionnement(cots, force, dates)
    for h, r in (mesure["positionnement"] or {}).items():
        log("    positionnement a %s : IC %s, reussite %s %% sur %d observations"
            % (h, r["ic"], r["reussite"], r["n"]))
except Exception as e:
    log("    positionnement : mesure impossible (" + str(e)[:60] + ")")
try:
    mesure["biais_publie"] = eprouver_biais(hist, force, dates)
    jours = sorted({j for l in (hist or {}).values() for j, _ in l})
    mesure["memoire_jours"] = len(jours)
    mesure["depuis"] = jours[0] if jours else None
    if mesure["biais_publie"]:
        for h, r in mesure["biais_publie"].items():
            log("    biais publie a %s : IC %s, reussite %s %% sur %d observations"
                % (h, r["ic"], r["reussite"], r["n"]))
    else:
        log("    biais publie : %d jour(s) d'historique, pas encore mesurable." % len(jours))
except Exception as e:
    log("    biais publie : mesure impossible (" + str(e)[:60] + ")")

journal(mouvements)
json.dump(hist, open("historique.json", "w", encoding="utf-8"), ensure_ascii=False)
json.dump({
    "calcule_iso": now.replace(microsecond=0).isoformat(),
    "seance": jour, "seances": len(dates),
    "source": "Reserve federale (H.10) via FRED",
    "source_pos": "CFTC — Commitments of Traders, non-commerciaux, futures seuls",
    "rapport_cot": max((d["rapport"] for d in pos_detail.values()), default=None),
    "macro": {"petrole_3m": round(petrole, 1) if petrole is not None else None,
              "tension": round(tension, 2) if tension is not None else None,
              "taux_us_1m": round(reprise) if reprise is not None else None},
    "moteurs": [{"cle": c, "nom": n, "poids": p} for c, n, p in MOTEURS],
    "poids": {k: round(v * 100) for k, v in POIDS.items()},
    "convictions": convictions,
    "grappes": grappes,
    "mesure": mesure,
    "devises": sortie,
}, open("marche.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

json.dump(src, open("currencies.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
log("marche.json ecrit — " + str(touchees) + " devise(s) recalculee(s) sur la seance du " + jour + ".")
