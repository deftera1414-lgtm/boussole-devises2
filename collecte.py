"""Boussole Devises — collecte hebdomadaire des echeances a fort impact.

Produit highlights.json : une semaine civile (lundi -> dimanche, UTC), les
echeances a fort impact posees jour par jour, ce que chaque publication implique
pour la devise concernee, et l'effet des chiffres deja parus.

Deux couches, volontairement distinctes :
  - ATTENDU  : consensus compare a la valeur precedente. Disponible pour tout
               evenement chiffre du calendrier. Dit vers quoi la semaine penche.
  - PARU     : chiffre effectivement publie, lu dans changelog.json (donc issu
               de FRED). Plus rare mais certain. Dit ce qui a deja bouge.
Aucune des deux n'est presentee pour l'autre.
"""
import json, os, re, sys, datetime as dt
import urllib.request, urllib.error

NOS = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY"]
FEED = os.environ.get("BOUSSOLE_FEED", "https://nfs.faireconomy.media/ff_calendar_thisweek.json")
MEMOIRE = 7          # jours pendant lesquels une publication continue de compter

M_AFF = {1: "janvier", 2: "février", 3: "mars", 4: "avril", 5: "mai", 6: "juin",
         7: "juillet", 8: "août", 9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre"}
M_LIRE = {"janv": 1, "janvier": 1, "fevr": 2, "févr": 2, "fevrier": 2, "février": 2, "mars": 3,
          "avr": 4, "avril": 4, "mai": 5, "juin": 6, "juil": 7, "juillet": 7, "aout": 8, "août": 8,
          "sept": 9, "septembre": 9, "oct": 10, "octobre": 10, "nov": 11, "novembre": 11,
          "dec": 12, "déc": 12, "decembre": 12, "décembre": 12}
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

now = dt.datetime.now(dt.timezone.utc)
def log(m): print(m, flush=True)
def frdate(d): return ("1er" if d.day == 1 else str(d.day)) + " " + M_AFF[d.month] + " " + str(d.year)
def frjour(d): return ("1er" if d.day == 1 else str(d.day)) + " " + M_AFF[d.month]


# --------------------------------------------------------------------------
# Familles d'indicateurs
# --------------------------------------------------------------------------
# (nom, motif sur le titre anglais, sens, echelle)
#   sens    : +1 si un chiffre plus haut soutient la devise, -1 si l'inverse,
#             0 si l'evenement n'est pas chiffrable (un discours).
#   echelle : ecart, dans l'unite de l'indicateur, qui vaut « un cran ».
#             None = echelle relative, calculee sur la taille des valeurs.
# L'ordre compte : « Unemployment Rate » doit tomber dans chomage, pas emploi.
FAMILLES = [
    ("taux", r"(cash rate|\bocr\b|official bank rate|bank rate|policy rate|federal funds"
             r"|refinancing rate|overnight rate|rate statement|rate decision"
             r"|monetary policy (statement|assessment|decision))", +1, 0.25),
    ("chomage", r"(unemployment rate|claimant count|unemployment claims|jobless)", -1, 0.2),
    ("emploi", r"(non-?farm|payroll|employment change|hourly earnings|labou?r cost)", +1, None),
    ("inflation", r"(\bcpi\b|\bppi\b|pce price|\bhicp\b|inflation|price index)", +1, 0.2),
    ("croissance", r"\bgdp\b", +1, 0.2),
    ("ventes", r"retail sales", +1, 0.4),
    ("activite", r"(\bpmi\b|\bism\b|\bifo\b|\bzew\b|confidence|sentiment|business climate)", +1, 1.0),
    ("commerce", r"trade balance", +1, None),
    ("discours", r"(speaks|press conference|testimony|minutes)", 0, None),
]
LIB_FAM = {"taux": "taux directeur", "inflation": "inflation", "chomage": "chômage",
           "emploi": "emploi", "croissance": "croissance", "ventes": "ventes au détail",
           "activite": "activité", "commerce": "commerce extérieur", "discours": "discours"}


def famille(titre):
    t = str(titre).lower()
    for nom, motif, sens, ech in FAMILLES:
        if re.search(motif, t, re.I):
            return nom, sens, ech
    return None, 0, None


MULT = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}
NUM_RE = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)\s*([KMBT])?\s*%?", re.I)


def nombre(s):
    """Lit « 3.1% », « 21.5K », « -15.8K », « 3,4% » (format francais) ou « 54.5 »."""
    if s is None:
        return None
    t = str(s).strip().replace("−", "-").replace("\u00a0", " ")
    if not t:
        return None
    # virgule decimale a la francaise si elle n'est pas un separateur de milliers
    if re.search(r"\d,\d{1,2}(?!\d)", t) and not re.search(r"\d\.\d", t):
        t = t.replace(",", ".")
    else:
        t = t.replace(",", "")
    m = NUM_RE.match(t)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    if m.group(2):
        v *= MULT[m.group(2).upper()]
    return v


def borne(v, lo, hi): return max(lo, min(hi, v))


def cran(apres, avant, sens, echelle):
    """Traduit un ecart en crans, entre -3 et +3, du point de vue de la devise."""
    if apres is None or avant is None or not sens:
        return None
    e = echelle if echelle else max(0.25 * max(abs(apres), abs(avant)), 1e-6)
    return borne(sens * (apres - avant) / e, -3.0, 3.0)


def mot_sens(x, fort=1.2):
    if x is None:
        return None
    if x >= fort: return "nettement favorable"
    if x >= 0.3: return "favorable"
    if x <= -fort: return "nettement défavorable"
    if x <= -0.3: return "défavorable"
    return "sans effet net"


# --------------------------------------------------------------------------
# Traduction des intitules
# --------------------------------------------------------------------------
TRAD = [
    ("Monetary Policy Statement", "Rapport de politique monétaire"),
    ("Monetary Policy Assessment", "Décision de politique monétaire"),
    ("Official Cash Rate", "Taux directeur (OCR)"),
    ("Cash Rate", "Taux directeur"), ("Policy Rate", "Taux directeur"),
    ("Overnight Rate", "Taux directeur"),
    ("Main Refinancing Rate", "Taux de refinancement BCE"),
    ("Official Bank Rate", "Taux directeur (Bank Rate)"),
    ("Federal Funds Rate", "Taux des fonds fédéraux"),
    ("FOMC Economic Projections", "Projections économiques du FOMC"),
    ("FOMC Press Conference", "Conférence de presse du FOMC"),
    ("FOMC Statement", "Communiqué du FOMC"),
    ("Press Conference", "Conférence de presse"),
    ("Rate Statement", "Communiqué de taux"),
    ("Non-Farm Employment Change", "Emplois non agricoles (NFP)"),
    ("Employment Change", "Variation de l'emploi"),
    ("Unemployment Rate", "Taux de chômage"),
    ("Unemployment Claims", "Inscriptions au chômage"),
    ("Average Hourly Earnings", "Salaire horaire moyen"),
    ("Claimant Count Change", "Demandeurs d'emploi"),
    ("Core CPI", "Inflation sous-jacente"), ("CPI y/y", "Inflation annuelle"),
    ("CPI m/m", "Inflation mensuelle"), ("CPI q/q", "Inflation trimestrielle"),
    ("CPI", "Inflation"), ("PPI", "Prix à la production"),
    ("Core PCE Price Index", "Indice PCE sous-jacent"),
    ("Retail Sales", "Ventes au détail"), ("GDP", "PIB"),
    ("ISM Manufacturing PMI", "ISM manufacturier"), ("ISM Services PMI", "ISM services"),
    ("ISM Manufacturing", "ISM manufacturier"), ("ISM Services", "ISM services"),
    ("Manufacturing PMI", "PMI manufacturier"), ("Services PMI", "PMI services"),
    ("Composite PMI", "PMI composite"),
    ("Consumer Confidence", "Confiance des consommateurs"),
    ("Consumer Sentiment", "Moral des ménages"),
    ("Trade Balance", "Balance commerciale"), ("Speaks", "— discours"),
]
ORG = [("BOE Gov", "Gouverneur BoE"), ("BOC Gov", "Gouverneur BdC"),
       ("RBA Gov", "Gouverneure RBA"), ("RBNZ Gov", "Gouverneur RBNZ"),
       ("SNB Chairman", "Président BNS"), ("BOJ Gov", "Gouverneur BoJ"),
       ("ECB President", "Présidente BCE"), ("Fed Chair", "Président Fed"),
       ("FOMC Member", "Membre du FOMC"), ("SNB", "BNS"), ("BOE", "BoE"),
       ("BOJ", "BoJ"), ("BOC", "BdC"), ("ECB", "BCE"), ("RBA", "RBA"), ("RBNZ", "RBNZ")]
QUAL = [("German ", "Allemagne : ", ""), ("French ", "France : ", ""),
        ("Italian ", "Italie : ", ""), ("Spanish ", "Espagne : ", ""),
        ("Flash ", "", " (flash)"), ("Prelim ", "", " (prélim.)"),
        ("Final ", "", " (définitif)")]
SUFF = [(" y/y", " sur un an"), (" m/m", " sur un mois"), (" q/q", " sur un trimestre")]


def traduire(titre):
    t = re.sub(r"\s+", " ", str(titre)).strip()
    pays, note, change = "", "", True
    while change:
        change = False
        for en, debut, fin in QUAL:
            if t.lower().startswith(en.lower()):
                t = t[len(en):]
                if debut:
                    pays = debut
                note += fin
                change = True
                break
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
    if queue.strip() and queue.strip() in t:
        queue = ""
    return re.sub(r"\s+", " ", pays + t + queue + note).strip()


# --------------------------------------------------------------------------
# 1. La semaine
# --------------------------------------------------------------------------
# Du lundi au dimanche. Le samedi et le dimanche, la semaine ecoulee n'interesse
# plus personne et le flux a bascule ou va basculer : on montre celle qui vient.
prochaine = now.weekday() >= 5
lundi = (now - dt.timedelta(days=now.weekday())).date()
if prochaine:
    lundi += dt.timedelta(days=7)
dimanche = lundi + dt.timedelta(days=6)
tete = "Semaine prochaine, du " if prochaine else "Semaine du "
if lundi.month == dimanche.month:
    titre_sem = tete + ("1er" if lundi.day == 1 else str(lundi.day)) + " au " + frdate(dimanche)
else:
    titre_sem = tete + frjour(lundi) + " au " + frdate(dimanche)

# --------------------------------------------------------------------------
# 2. Flux du calendrier
# --------------------------------------------------------------------------
evenements, flux_ok = [], False
try:
    rq = urllib.request.Request(FEED, headers={"User-Agent": "boussole-devises/4"})
    with urllib.request.urlopen(rq, timeout=25) as r:
        data = json.load(r)
    if not isinstance(data, list):
        raise ValueError("format inattendu")
    for e in data:
        if not isinstance(e, dict) or e.get("impact") != "High" or e.get("country") not in NOS:
            continue
        try:
            quand = dt.datetime.fromisoformat(str(e.get("date", ""))).astimezone(dt.timezone.utc)
        except (ValueError, TypeError):
            continue
        titre_en = str(e.get("title", ""))
        fam, sens, ech = famille(titre_en)
        cons, prec = (e.get("forecast") or "").strip(), (e.get("previous") or "").strip()
        attendu = cran(nombre(cons), nombre(prec), sens, ech)
        evenements.append({
            "code": e["country"], "titre": traduire(titre_en), "famille": fam,
            "iso": quand.replace(microsecond=0).isoformat(),
            "heure": quand.strftime("%Hh%M"),
            "consensus": cons, "precedent": prec,
            "attendu": None if attendu is None else round(attendu, 2),
            "source": "calendrier",
        })
    flux_ok = True
    log("Calendrier : " + str(len(evenements)) + " echeance(s) a fort impact sur " +
        str(len(data)) + " entrees.")
except Exception as ex:
    log("Calendrier indisponible (" + str(ex)[:110] + ") — repli sur les banques centrales seules.")

# --------------------------------------------------------------------------
# 3. Etat des devises + reunions de banques centrales
# --------------------------------------------------------------------------
try:
    src = json.load(open("currencies.json", encoding="utf-8"))
    cur = src["currencies"]
except Exception as ex:
    log("ERREUR : currencies.json illisible (" + str(ex) + ")")
    sys.exit(1)


def lire_fr(txt):
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


NB_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?\s*%")
PER_RE = re.compile(r"\b(T[1-4]\s*\d{4}|[a-zéèêûôàç]{3,10}\.?\s+\d{4})", re.I)


def compact(txt):
    """« 3,2% (août 2026, IPCH global…) » -> « 3,2% · août 2026 »."""
    t = str(txt or "").strip()
    if not t:
        return ""
    n = NB_RE.search(t)
    if not n:
        return t if len(t) <= 26 else t[:25].rstrip() + "…"
    p = PER_RE.search(t)
    return n.group().replace(" ", "") + (" · " + p.group(1).rstrip(".") if p else "")


TON = {"hawkish": "resserrement", "dovish": "assouplissement", "neutral": "neutre"}
reunions = []
for code in NOS:
    c = cur.get(code) or {}
    d = lire_fr(c.get("next", ""))
    if d is None:
        continue
    lib = str(c.get("next", "")).split("—", 1)
    titre = lib[1].strip() if len(lib) > 1 else "Réunion de politique monétaire"
    quand = dt.datetime(d.year, d.month, d.day, 12, 0, tzinfo=dt.timezone.utc)
    reunions.append({"code": code, "titre": titre, "famille": "taux",
                     "iso": quand.isoformat(), "heure": "",
                     "consensus": "", "precedent": str(c.get("rate_current", "")),
                     "attendu": None, "source": "banque centrale"})

# le flux prime : il porte le consensus. Une reunion deja couverte le meme jour saute.
jours_flux = {(x["code"], x["iso"][:10]) for x in evenements}
tout = evenements + [r for r in reunions if (r["code"], r["iso"][:10]) not in jours_flux]
tout.sort(key=lambda x: x["iso"])

# --------------------------------------------------------------------------
# 4. Ce qui est deja paru : on relit le journal du robot
# --------------------------------------------------------------------------
# Le pas FRED ecrit « USD — inflation : 3,4% (août 2026, FRED) (auparavant 3,2% …) ».
# C'est notre seule source certaine de chiffre publie, et elle est deja la.
PUB_RE = re.compile(r"^([A-Z]{3})\s*[-—]\s*(inflation|chomage|chômage)\s*:\s*(.+?)\s*"
                    r"\(auparavant\s+(.+)\)\s*$")
parutions = {c: [] for c in NOS}
try:
    entrees = json.load(open("changelog.json", encoding="utf-8")).get("entries", [])
except Exception:
    entrees = []
limite = now.date() - dt.timedelta(days=MEMOIRE)
for entree in entrees if isinstance(entrees, list) else []:
    if not isinstance(entree, dict):
        continue
    try:
        jour = dt.date.fromisoformat(str(entree.get("date", "")))
    except ValueError:
        continue
    if jour < limite:
        continue
    for item in entree.get("items", []):
        m = PUB_RE.match(str(item).strip())
        if not m or m.group(1) not in NOS:
            continue
        code = m.group(1)
        fam = "chomage" if m.group(2).lower().startswith(("chom", "chôm")) else "inflation"
        sens = -1 if fam == "chomage" else +1
        na, nb = nombre(m.group(3)), nombre(m.group(4))
        c_ = cran(na, nb, sens, 0.2)
        if c_ is None:
            continue
        age = (now.date() - jour).days
        parutions[code].append({
            "famille": fam, "libelle": LIB_FAM[fam], "date": jour.isoformat(),
            "date_txt": frjour(jour), "valeur": compact(m.group(3)),
            "avant": compact(m.group(4)),
            "variation": ("+" if na >= nb else "") + ("%.1f" % (na - nb)).replace(".", ",") + " pt",
            "cran": round(c_, 2), "age": age,
            "poids": round(c_ * max(0.0, 1.0 - age / float(MEMOIRE)), 2),
        })

# --------------------------------------------------------------------------
# 5. Assemblage de la semaine
# --------------------------------------------------------------------------
jours = []
for i in range(7):
    j = lundi + dt.timedelta(days=i)
    du_jour = [e for e in tout if e["iso"][:10] == j.isoformat()]
    jours.append({
        "iso": j.isoformat(), "nom": JOURS[i], "num": str(j.day),
        "mois": M_AFF[j.month][:4] + ("." if len(M_AFF[j.month]) > 4 else ""),
        "passe": j < now.date(), "aujourdhui": j == now.date(),
        "evenements": du_jour, "nb": len(du_jour),
    })

dans_semaine = [e for e in tout if lundi.isoformat() <= e["iso"][:10] <= dimanche.isoformat()]
a_venir = [e for e in dans_semaine if e["iso"] >= now.isoformat()]

# --------------------------------------------------------------------------
# 6. Chaque devise : ce que la semaine lui reserve, ce qui lui est deja tombe
# --------------------------------------------------------------------------
devises = []
for code in NOS:
    c = cur.get(code) or {}
    sem = [e for e in dans_semaine if e["code"] == code]
    reste = [e for e in a_venir if e["code"] == code]
    penchant = sum(e["attendu"] for e in reste if e["attendu"] is not None)
    penchant = round(borne(penchant, -6, 6), 2)

    fams = []
    for e in sem:
        lib = LIB_FAM.get(e["famille"])
        if lib and lib not in fams:
            fams.append(lib)
    resume = ", ".join(fams[:3]) if fams else ""

    pubs = sorted(parutions[code], key=lambda p: p["date"], reverse=True)
    effet = round(borne(sum(p["poids"] for p in pubs), -6, 6), 2)

    suivant = next((e for e in tout if e["code"] == code and e["iso"] >= now.isoformat()), None)
    d_suiv = dt.date.fromisoformat(suivant["iso"][:10]) if suivant else None

    devises.append({
        "code": code,
        "banque": c.get("bank", ""),
        "taux": c.get("rate_current", ""),
        "ton": TON.get(str(c.get("tilt", "")).lower(), str(c.get("tilt", "") or "")),
        "biais": c.get("bias"),
        "inflation": compact(c.get("cpi_current", "")),
        "inflation_detail": c.get("cpi_current", ""),
        "chomage": compact(c.get("unemp_current", "")),
        "chomage_detail": c.get("unemp_current", ""),
        "semaine_nb": len(sem),
        "semaine_reste": len(reste),
        "semaine_penchant": penchant,
        "semaine_mot": ("rien d’ici dimanche" if not reste else mot_sens(penchant, fort=1.5)),
        "semaine_resume": resume,
        "parutions": pubs[:3],
        "effet": effet,
        "effet_mot": mot_sens(effet, fort=1.5),
        "prochain": suivant["titre"] if suivant else str(c.get("next", "")),
        "prochain_iso": suivant["iso"] if suivant else "",
        "prochain_txt": frjour(d_suiv) if d_suiv else "",
    })

# ligne de synthese : les parutions les plus marquantes, toutes devises confondues
faits = []
for code in NOS:
    for p in parutions[code]:
        if abs(p["poids"]) >= 0.3:
            faits.append(dict(p, code=code))
faits.sort(key=lambda p: (-abs(p["poids"]), p["date"]))

sortie = {
    "verifie_iso": now.replace(microsecond=0).isoformat(),
    "verifie": frdate(now.date()) + ", " + now.strftime("%Hh%M") + " UTC",
    "flux_ok": flux_ok,
    "memoire_jours": MEMOIRE,
    "semaine": {
        "titre": titre_sem, "debut": lundi.isoformat(), "fin": dimanche.isoformat(),
        "aujourdhui": now.date().isoformat(), "jours": jours,
        "nb": len(dans_semaine), "reste": len(a_venir),
        "prochaine": prochaine,
        # Le calendrier de la semaine suivante ne parait que le dimanche : le
        # samedi, la grille est legitimement presque vide et doit le dire.
        "en_attente": prochaine and now.weekday() == 5 and
                      not [e for e in dans_semaine if e["source"] == "calendrier"],
    },
    "faits": faits[:3],
    "devises": devises,
}
json.dump(sortie, open("highlights.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
log("highlights.json ecrit — " + titre_sem.lower() + " : " + str(len(dans_semaine)) +
    " echeance(s), dont " + str(len(a_venir)) + " a venir ; " +
    str(sum(len(v) for v in parutions.values())) + " parution(s) retenue(s).")
