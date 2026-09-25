import json, os, re, sys, datetime as dt
import urllib.request, urllib.error

NOS = ["EUR","GBP","AUD","NZD","USD","CAD","CHF","JPY"]
FEED = os.environ.get("BOUSSOLE_FEED", "https://nfs.faireconomy.media/ff_calendar_thisweek.json")
HORIZON = 10          # jours d'agenda affiches
IMMINENT = 36         # heures : seuil du bandeau rouge

M_AFF = {1:"janvier",2:"février",3:"mars",4:"avril",5:"mai",6:"juin",
         7:"juillet",8:"août",9:"septembre",10:"octobre",11:"novembre",12:"décembre"}
M_LIRE = {"janv":1,"janvier":1,"fevr":2,"févr":2,"fevrier":2,"février":2,"mars":3,
          "avr":4,"avril":4,"mai":5,"juin":6,"juil":7,"juillet":7,"aout":8,"août":8,
          "sept":9,"septembre":9,"oct":10,"octobre":10,"nov":11,"novembre":11,
          "dec":12,"déc":12,"decembre":12,"décembre":12}

now = dt.datetime.now(dt.timezone.utc)
def log(m): print(m, flush=True)
def frdate(d): return ("1er" if d.day == 1 else str(d.day)) + " " + M_AFF[d.month] + " " + str(d.year)

# Traduction des intitules anglais du flux. Ce qui n'est pas dans la table
# passe tel quel : mieux vaut un titre anglais qu'un titre faux.
TRAD = [
    ("Monetary Policy Statement", "Rapport de politique monétaire"),
    ("Monetary Policy Assessment", "Décision de politique monétaire"),
    ("Official Cash Rate", "Taux directeur (OCR)"),
    ("Cash Rate", "Taux directeur"),
    ("Policy Rate", "Taux directeur"),
    ("Overnight Rate", "Taux directeur"),
    ("Main Refinancing Rate", "Taux de refinancement BCE"),
    ("Official Bank Rate", "Taux directeur (Bank Rate)"),
    ("Federal Funds Rate", "Taux des fonds fédéraux"),
    ("FOMC Statement", "Communiqué du FOMC"),
    ("FOMC Economic Projections", "Projections économiques du FOMC"),
    ("FOMC Press Conference", "Conférence de presse du FOMC"),
    ("Press Conference", "Conférence de presse"),
    ("Rate Statement", "Communiqué de taux"),
    ("Non-Farm Employment Change", "Emplois non agricoles (NFP)"),
    ("Employment Change", "Variation de l'emploi"),
    ("Unemployment Rate", "Taux de chômage"),
    ("Unemployment Claims", "Inscriptions au chômage"),
    ("Average Hourly Earnings", "Salaire horaire moyen"),
    ("Claimant Count Change", "Demandeurs d'emploi"),
    ("Core CPI", "Inflation sous-jacente"),
    ("CPI y/y", "Inflation annuelle"),
    ("CPI m/m", "Inflation mensuelle"),
    ("CPI q/q", "Inflation trimestrielle"),
    ("Flash CPI", "Inflation (estimation rapide)"),
    ("CPI", "Inflation"),
    ("PPI", "Prix à la production"),
    ("Core PCE Price Index", "Indice PCE sous-jacent"),
    ("Retail Sales", "Ventes au détail"),
    ("GDP", "PIB"),
    ("ISM Manufacturing PMI", "ISM manufacturier"),
    ("ISM Services PMI", "ISM services"),
    ("ISM Manufacturing", "ISM manufacturier"),
    ("ISM Services", "ISM services"),
    ("Manufacturing PMI", "PMI manufacturier"),
    ("Services PMI", "PMI services"),
    ("Composite PMI", "PMI composite"),
    ("Consumer Confidence", "Confiance des consommateurs"),
    ("Consumer Sentiment", "Moral des ménages"),
    ("Trade Balance", "Balance commerciale"),
    ("Speaks", "— discours"),
]
ORG = [("BOE Gov", "Gouverneur BoE"), ("BOC Gov", "Gouverneur BdC"),
       ("RBA Gov", "Gouverneure RBA"), ("RBNZ Gov", "Gouverneur RBNZ"),
       ("SNB Chairman", "Président BNS"), ("BOJ Gov", "Gouverneur BoJ"),
       ("ECB President", "Présidente BCE"), ("Fed Chair", "Président Fed"),
       ("FOMC Member", "Membre du FOMC"), ("SNB", "BNS"), ("BOE", "BoE"),
       ("BOJ", "BoJ"), ("BOC", "BdC"), ("ECB", "BCE"), ("RBA", "RBA"), ("RBNZ", "RBNZ")]
# (motif en tete, ce qui le remplace, note ajoutee en fin de titre)
QUAL = [("German ", "Allemagne : ", ""), ("French ", "France : ", ""),
        ("Italian ", "Italie : ", ""), ("Spanish ", "Espagne : ", ""),
        ("Flash ", "", " (flash)"), ("Prelim ", "", " (prélim.)"),
        ("Final ", "", " (définitif)")]
SUFF = [(" y/y", " sur un an"), (" m/m", " sur un mois"), (" q/q", " sur un trimestre")]

def traduire(titre):
    t = re.sub(r"\s+", " ", str(titre)).strip()
    pays, note = "", ""
    change = True
    while change:                                  # « German Flash PMI » : deux qualificatifs
        change = False
        for en, debut, fin in QUAL:
            if t.lower().startswith(en.lower()):
                t = t[len(en):]
                if debut:
                    pays = debut
                note += fin
                change = True
                break
    # Un discours garde son orateur en tete ; un indicateur renvoie le sigle de
    # la banque en fin de titre, ou « BNS Taux directeur » sonnerait faux.
    discours = "speaks" in t.lower()
    queue = ""
    for en, fr in ORG:
        if t.startswith(en + " "):
            if discours:
                t = fr + " " + t[len(en) + 1:]
            else:
                t, queue = t[len(en) + 1:], " " + fr
            break
    for en, fr in TRAD:
        if en.lower() in t.lower():
            t = re.sub(re.escape(en), fr, t, count=1, flags=re.I)
            break
    for en, fr in SUFF:
        t = re.sub(re.escape(en) + r"\b", fr, t, flags=re.I)
    if queue.strip() and queue.strip() in t:       # « Taux de refinancement BCE » + « BCE »
        queue = ""
    return re.sub(r"\s+", " ", pays + t + queue + note).strip()

# ---------- 1. flux hebdomadaire a fort impact ----------
flux, flux_ok = [], False
try:
    rq = urllib.request.Request(FEED, headers={"User-Agent": "boussole-devises/3"})
    with urllib.request.urlopen(rq, timeout=25) as r:
        data = json.load(r)
    if not isinstance(data, list):
        raise ValueError("format inattendu")
    for e in data:
        if not isinstance(e, dict) or e.get("impact") != "High":
            continue
        code = e.get("country")
        if code not in NOS:
            continue
        try:
            quand = dt.datetime.fromisoformat(str(e.get("date", ""))).astimezone(dt.timezone.utc)
        except (ValueError, TypeError):
            continue
        flux.append({"code": code, "titre": traduire(str(e.get("title", ""))),
                     "iso": quand.replace(microsecond=0).isoformat(),
                     "consensus": (e.get("forecast") or "").strip(),
                     "precedent": (e.get("previous") or "").strip(),
                     "source": "calendrier"})
    flux_ok = True
    log("Flux a fort impact : " + str(len(flux)) + " echeance(s) retenue(s) sur " + str(len(data)) + " entrees.")
except Exception as ex:
    log("Flux indisponible (" + str(ex)[:120] + ") — repli sur le calendrier des banques centrales seul.")

# ---------- 2. etat des 8 devises + prochaine reunion ----------
try:
    src = json.load(open("currencies.json", encoding="utf-8"))
    cur = src["currencies"]
except Exception as ex:
    log("ERREUR : currencies.json illisible (" + str(ex) + ")")
    sys.exit(1)

def lire_fr(txt):
    """Date d'un libelle du type '28 octobre 2026 — Decision FOMC'."""
    m = re.search(r"(\d{1,2})(?:\s*er)?\s+([a-zéèêûôàç]+)\.?\s+(\d{4})", str(txt).lower())
    if not m:
        return None
    j, mo, an = m.groups()
    mois = M_LIRE.get(mo.rstrip("."))
    if mois is None:
        for k, v in M_LIRE.items():
            if mo.startswith(k):
                mois = v
                break
    if mois is None:
        return None
    try:
        return dt.date(int(an), mois, int(j))
    except ValueError:
        return None

TON = {"hawkish": "resserrement", "dovish": "assouplissement", "neutral": "neutre"}

NB_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?\s*%")
PER_RE = re.compile(r"\b(T[1-4]\s*\d{4}|[a-zéèêûôàç]{3,10}\.?\s+\d{4})", re.I)

def compact(txt):
    """« 3,2% (août 2026, IPCH global, au-dessus de la cible) » -> « 3,2% · août 2026 ».
    Le bandeau doit se lire d'un coup d'oeil ; le detail reste sur la carte."""
    t = str(txt or "").strip()
    if not t:
        return ""
    n = NB_RE.search(t)
    if not n:
        return t if len(t) <= 26 else t[:25].rstrip() + "…"
    p = PER_RE.search(t)
    return n.group().replace(" ", "") + (" · " + p.group(1).rstrip(".") if p else "")
devises, reunions = [], []
for code in NOS:
    c = cur.get(code) or {}
    d = lire_fr(c.get("next", ""))
    lib = str(c.get("next", "")).split("—", 1)
    titre = lib[1].strip() if len(lib) > 1 else "Réunion de politique monétaire"
    iso = ""
    if d is not None:
        # 12h00 UTC par defaut : l'heure exacte des reunions lointaines n'est
        # pas publiee, et le compte a rebours reste juste au jour pres.
        iso = dt.datetime(d.year, d.month, d.day, 12, 0, tzinfo=dt.timezone.utc).isoformat()
        if d >= now.date():
            reunions.append({"code": code, "titre": titre, "iso": iso,
                             "consensus": "", "precedent": str(c.get("rate_current", "")),
                             "source": "banque centrale"})
    devises.append({
        "code": code,
        "banque": c.get("bank", ""),
        "taux": c.get("rate_current", ""),
        "ton": TON.get(str(c.get("tilt", "")).lower(), str(c.get("tilt", "") or "")),
        "biais": c.get("bias"),
        "momentum": c.get("momentum"),
        "inflation": compact(c.get("cpi_current", "")),
        "inflation_detail": c.get("cpi_current", ""),
        "chomage": compact(c.get("unemp_current", "")),
        "chomage_detail": c.get("unemp_current", ""),
        "prochain": titre,
        "prochain_iso": iso,
        "prochain_txt": frdate(d) if d else str(c.get("next", "")),
    })

# ---------- 3. fusion, dedoublonnage, tri ----------
def cle(x):
    return (x["code"], x["iso"][:10], re.sub(r"[^a-z]", "", x["titre"].lower())[:12])

vus, tout = set(), []
for x in flux + reunions:                      # le flux prime : il porte le consensus
    k = cle(x)
    if k in vus:
        continue
    vus.add(k)
    tout.append(x)

# une reunion de banque centrale deja couverte par le flux le meme jour est retiree
jours_flux = {(x["code"], x["iso"][:10]) for x in flux}
tout = [x for x in tout
        if not (x["source"] == "banque centrale" and (x["code"], x["iso"][:10]) in jours_flux)]

limite = now + dt.timedelta(days=HORIZON)
avenir = sorted([x for x in tout
                 if now - dt.timedelta(hours=2) <= dt.datetime.fromisoformat(x["iso"]) <= limite],
                key=lambda x: x["iso"])
imminents = [x for x in avenir
             if dt.datetime.fromisoformat(x["iso"]) <= now + dt.timedelta(hours=IMMINENT)]

# la prochaine echeance de chaque devise, quelle qu'en soit la distance
prochain_par_devise = {}
for x in sorted(tout, key=lambda x: x["iso"]):
    if dt.datetime.fromisoformat(x["iso"]) >= now - dt.timedelta(hours=2):
        prochain_par_devise.setdefault(x["code"], x)
for d in devises:
    p = prochain_par_devise.get(d["code"])
    if p:
        d["prochain"] = p["titre"]
        d["prochain_iso"] = p["iso"]
        jour = dt.datetime.fromisoformat(p["iso"]).date()
        d["prochain_txt"] = frdate(jour)

sortie = {
    "verifie_iso": now.replace(microsecond=0).isoformat(),
    "verifie": frdate(now.date()) + ", " + now.strftime("%Hh%M") + " UTC",
    "flux_ok": flux_ok,
    "horizon_jours": HORIZON,
    "seuil_imminent_h": IMMINENT,
    "imminents": imminents,
    "agenda": avenir[:14],
    "devises": devises,
}
json.dump(sortie, open("highlights.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
log("highlights.json ecrit — " + str(len(imminents)) + " imminent(s), " +
    str(len(avenir)) + " a l'agenda, 8 devises.")
