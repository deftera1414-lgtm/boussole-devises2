"""Boussole Devises — bandeau hebdomadaire + pastilles de semaine sur les cartes.

Deux insertions, sans jamais repeter la meme information :
  - en haut de page, LA SEMAINE : ce qui vient de paraitre, puis les echeances
    a fort impact posees jour par jour ;
  - sur chaque carte de devise, CE QUI LA CONCERNE : sa semaine, sa prochaine
    echeance avec le delai, et l'effet des chiffres deja parus.

Le detail chiffre (taux, PIB, inflation, chomage) reste sur la carte, ou il
etait deja. Rien n'est affiche deux fois.

Troisieme role, moins visible mais necessaire : retirer les drapeaux emoji de
toute la page. Windows ne possede pas ces caracteres et les rend sous forme de
deux lettres — « EU EUR », « GB GBP » — ce qui est du bruit pur. Le code a trois
lettres suffit et s'affiche partout.
"""
import json, html, re, datetime as dt

try:
    H = json.load(open("highlights.json", encoding="utf-8"))
except Exception as e:
    print("highlights.json illisible (" + str(e) + ") — bandeau non insere.")
    raise SystemExit(0)

# Les scores de marche sont facultatifs : sans eux la page reste correcte, elle
# est seulement moins bavarde sur l'origine du biais.
try:
    MJ = json.load(open("marche.json", encoding="utf-8")) or {}
except Exception:
    MJ = {}
MA = MJ.get("devises") or {}


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def court(t, n=52):
    t = str(t or "").strip()
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def fleche(x, seuil=0.3):
    """Classe et symbole d'un score. Rien n'est invente : None reste muet."""
    if x is None:
        return "neu", ""
    if x >= seuil:
        return "pos", "↗"
    if x <= -seuil:
        return "neg", "↘"
    return "neu", ""


CSS = """<style>
/* ---------- bandeau de la semaine ---------- */
.hw{flex:1 0 100%;width:100%;background:var(--surface);border:1px solid var(--border);
  border-radius:12px;box-shadow:var(--shadow);margin:18px 0 4px;overflow:hidden;
  border-top:3px solid var(--gold)}
.hw-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;padding:14px 18px 12px;
  border-bottom:1px solid var(--border)}
.hw-head h2{margin:0;font-family:var(--font-display);font-size:1rem;color:var(--text);
  font-weight:700;letter-spacing:.01em}
.hw-dot{width:8px;height:8px;border-radius:50%;background:var(--gold);flex:none;align-self:center;
  animation:hwp 2.6s infinite}
@keyframes hwp{0%{box-shadow:0 0 0 0 rgba(224,168,87,.5)}70%{box-shadow:0 0 0 9px rgba(224,168,87,0)}
  100%{box-shadow:0 0 0 0 rgba(224,168,87,0)}}
@media (prefers-reduced-motion:reduce){.hw-dot{animation:none}}
.hw-when{margin-left:auto;font-family:var(--font-mono);font-size:.68rem;color:var(--text-muted);
  text-transform:uppercase;letter-spacing:.05em}
.hw-when b{color:var(--gold);font-weight:600}
.hw-note{padding:9px 18px;font-size:.76rem;color:var(--text-secondary);background:var(--surface-2);
  border-bottom:1px solid var(--border)}
.hw-faits{padding:11px 18px;border-bottom:1px solid var(--border);display:flex;
  gap:7px 16px;flex-wrap:wrap;align-items:baseline}
.hw-faits .lab{font-family:var(--font-mono);font-size:.63rem;letter-spacing:.09em;
  text-transform:uppercase;color:var(--text-muted);flex:none}
.hw-fait{font-size:.81rem;color:var(--text-secondary)}
.hw-fait b{color:var(--text);font-weight:600}
.hw-fait .v{font-family:var(--font-mono);font-size:.78rem}
.hw-grille{display:grid;grid-template-columns:repeat(7,minmax(0,1fr))}
.hw-j{border-right:1px solid var(--border);padding:9px 9px 11px;min-height:72px}
.hw-j:last-child{border-right:none}
.hw-j.passe{opacity:.74}
.hw-j.auj{background:var(--gold-tint)}
.hw-jt{font-family:var(--font-mono);font-size:.63rem;letter-spacing:.06em;text-transform:uppercase;
  color:var(--text-muted);margin-bottom:7px;display:flex;align-items:baseline;gap:5px}
.hw-j.auj .hw-jt{color:var(--gold);font-weight:700}
.hw-jt b{color:var(--text-secondary);font-size:.78rem;font-weight:700}
.hw-j.auj .hw-jt b{color:var(--gold)}
.hw-ev{border-left:2px solid var(--border);padding:2px 0 2px 7px;margin-bottom:6px}
.hw-ev.pos{border-left-color:var(--rise)}
.hw-ev.neg{border-left-color:var(--fall)}
.hw-ev.bc{border-left-color:var(--gold)}
.hw-e1{display:flex;gap:6px;align-items:baseline;flex-wrap:wrap}
.hw-t{font-size:.74rem;color:var(--text-secondary);line-height:1.35;margin-top:1px}
.hw-chiffres{font-family:var(--font-mono);font-size:.66rem;color:var(--text-muted);margin-top:2px}
.hw-chiffres b{color:var(--text-secondary);font-weight:600}
.hw-rien{font-size:.72rem;color:var(--text-muted)}
.hw-plus{font-size:.68rem;color:var(--text-muted);padding-left:9px}
.hw-foot{padding:10px 18px 12px;font-size:.69rem;color:var(--text-muted);line-height:1.5;
  border-top:1px solid var(--border)}

/* ---------- code devise, en remplacement des drapeaux ---------- */
.code{font-family:var(--font-mono);font-size:.66rem;font-weight:700;letter-spacing:.04em;
  padding:1px 5px;border-radius:4px;background:var(--surface-2);border:1px solid var(--border);
  color:var(--text);white-space:nowrap}
.hw-h{font-family:var(--font-mono);font-size:.63rem;color:var(--text-muted)}

/* ---------- pastille de semaine sur chaque carte ---------- */
.cw{border-top:1px solid var(--border);border-bottom:1px solid var(--border);
  background:var(--surface-2);padding:8px 0;margin:2px 0 4px}
.cw-l{display:flex;gap:10px;align-items:baseline;padding:3px 16px}
.cw-k{font-family:var(--font-mono);font-size:.6rem;letter-spacing:.09em;text-transform:uppercase;
  color:var(--text-muted);flex:0 0 84px}
.cw-v{font-size:.78rem;color:var(--text-secondary);flex:1 1 auto;line-height:1.4}
.cw-v b{color:var(--text);font-weight:600}
.cw-v .s{color:var(--text-muted)}
.cw-f{font-family:var(--font-mono);font-weight:700;margin-right:3px}
.cw-f.pos{color:var(--rise-text)}
.cw-f.neg{color:var(--fall-text)}
.cw-courbe{vertical-align:middle;margin-right:8px}
.cw-courbe path{fill:none;stroke-width:1.6;vector-effect:non-scaling-stroke}
.cw-num{font-family:var(--font-mono);font-size:.74rem}
.cw-part{display:inline-block;margin-right:9px;font-family:var(--font-mono);font-size:.72rem}
.cw-part i{font-style:normal;color:var(--text-muted)}
.cw-part b{font-weight:700}
.cw-part.pos b{color:var(--rise-text)}
.cw-part.neg b{color:var(--fall-text)}
.cw-part.neu b{color:var(--text-secondary)}

/* ---------- ce que le modele vaut ---------- */
.cv{flex:1 0 100%;width:100%;background:var(--surface);border:1px solid var(--border);
  border-radius:12px;box-shadow:var(--shadow);margin:4px 0 14px;overflow:hidden}
.cv-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;padding:12px 18px 10px;
  border-bottom:1px solid var(--border)}
.cv-head h2{margin:0;font-family:var(--font-display);font-size:.92rem;color:var(--text);
  font-weight:700}
.cv-when{margin-left:auto;font-family:var(--font-mono);font-size:.66rem;color:var(--text-muted);
  text-transform:uppercase;letter-spacing:.05em}
.cv-corps{display:grid;grid-template-columns:1fr 1fr;gap:0}
.cv-col{padding:12px 18px 14px;min-width:0}
.cv-col + .cv-col{border-left:1px solid var(--border)}
@media (max-width:820px){.cv-corps{grid-template-columns:1fr}
  .cv-col + .cv-col{border-left:0;border-top:1px solid var(--border)}}
.cv-t{display:block;font-family:var(--font-mono);font-size:.6rem;letter-spacing:.09em;
  text-transform:uppercase;color:var(--text-muted);margin:2px 0 6px}
.cv-l + .cv-t{margin-top:12px}
.cv-l{font-size:.78rem;color:var(--text-secondary);line-height:1.5;padding:2px 0}
.cv-l b{color:var(--text);font-weight:600}
.cv-l .s{color:var(--text-muted)}
.cv-n{font-family:var(--font-mono);font-size:.74rem;color:var(--text)}
.cv-note{font-size:.7rem;color:var(--text-muted);line-height:1.5;margin-top:8px;
  padding-top:8px;border-top:1px dashed var(--border)}

/* ---------- delai, partout ---------- */
.cd{font-family:var(--font-mono);font-size:.71rem;font-weight:700;white-space:nowrap;
  padding:1px 7px;border-radius:999px;background:var(--surface);color:var(--text-secondary);
  border:1px solid var(--border)}
.cd.soon{color:var(--gold);border-color:var(--gold)}
.cd.hot{color:#fff;background:var(--fall);border-color:var(--fall)}
.cd.past{opacity:.5}

@media (max-width:900px){
  .hw-grille{grid-template-columns:repeat(3,minmax(0,1fr))}
  .hw-j{border-bottom:1px solid var(--border);min-height:0}
}
@media (max-width:620px){
  .hw-grille{grid-template-columns:1fr}
  .hw-j{border-right:none}
  .hw-when{margin-left:0;flex:1 0 100%}
  .cw-l{flex-wrap:wrap;gap:2px 10px}
  .cw-k{flex:1 0 100%}
}
</style>"""

SCRIPT = """<script>
(function(){
  function fmt(s){
    var p = s < 0, a = Math.abs(s);
    var j = Math.floor(a/86400), h = Math.floor(a%86400/3600), m = Math.floor(a%3600/60);
    var t;
    if (j >= 2) t = j + " j";
    else if (j === 1) t = "1 j" + (h ? " " + h + " h" : "");
    else if (h >= 1) t = h + " h" + (m ? " " + (m < 10 ? "0" : "") + m : "");
    else t = Math.max(m, 0) + " min";
    return p ? "il y a " + t : "dans " + t;
  }
  function tick(){
    var n = Date.now(), l = document.querySelectorAll("[data-iso]");
    for (var i = 0; i < l.length; i++){
      var el = l[i], t = Date.parse(el.getAttribute("data-iso"));
      if (isNaN(t)) continue;
      var s = Math.round((t - n) / 1000);
      el.textContent = fmt(s);
      el.className = "cd" + (s < 0 ? " past" : s < 3600 ? " hot" : s < 86400 ? " soon" : "");
      el.title = new Date(t).toLocaleString();
    }
  }
  tick();
  setInterval(tick, 30000);
})();
</script>"""

def courbe_svg(pts, hausse):
    """Petite courbe de force, en SVG inline : aucune dependance, aucun script."""
    if not pts or len(pts) < 8:
        return ""
    n = len(pts)
    d = " ".join(("M" if i == 0 else "L") + str(round(i * 108.0 / (n - 1), 1)) + "," +
                 str(round(20.0 - v * 0.18, 1)) for i, v in enumerate(pts))
    couleur = "var(--rise)" if hausse else "var(--fall)"
    return ('<svg class="cw-courbe" width="110" height="22" viewBox="0 0 110 22" '
            'aria-hidden="true"><path d="' + d + '" stroke="' + couleur + '"/></svg>')


def signe(v, suffixe="%"):
    if v is None:
        return "—"
    if abs(v) < 0.005:                       # evite le « -0,00 % »
        return "0,00" + suffixe
    return ("+" if v > 0 else "−") + ("%.2f" % abs(v)).replace(".", ",") + suffixe


def part(nom, v):
    cls = "pos" if v >= 0.3 else ("neg" if v <= -0.3 else "neu")
    return ('<span class="cw-part ' + cls + '"><i>' + nom + '</i> <b>' +
            ("+" if v >= 0 else "") + ("%.1f" % v).replace(".", ",") + "</b></span>")


MOIS = ("janv.", "févr.", "mars", "avril", "mai", "juin", "juil.", "août",
        "sept.", "oct.", "nov.", "déc.")


def date_courte(iso):
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return ""
    return str(d.day) + " " + MOIS[d.month - 1]


def tenue(place):
    """Ou en est le positionnement dans son historique de trois ans, en mots."""
    if place >= 90:
        return "au plus haut depuis 3 ans — positions encombrées"
    if place >= 70:
        return "haut de fourchette"
    if place > 30:
        return "milieu de fourchette"
    if place > 10:
        return "bas de fourchette"
    return "au plus bas depuis 3 ans — positions encombrées"


NOM_MOTEUR = {
    "taux_reel": "le portage réel", "impulsion": "l'impulsion de politique",
    "inflation": "l'écart d'inflation à la cible", "ton": "le ton de la banque centrale",
    "croissance": "la croissance et l'emploi", "taux_us": "les taux américains",
    "commerce": "les termes de l'échange", "risque": "le régime de risque",
}


def liste_fr(xs):
    if len(xs) < 2:
        return xs[0] if xs else ""
    return ", ".join(xs[:-1]) + " et " + xs[-1]


def fondation(m):
    """Ce qui porte et ce qui freine la direction fondamentale, en toutes
    lettres. C'est la reponse a « pourquoi ce chiffre ? » : on nomme les deux
    moteurs qui poussent le plus et celui qui retient le plus, chiffres."""
    d = m.get("fond_detail") or {}
    ap = d.get("apport") or {}
    if not ap:
        return ""
    f = m.get("fondamental")
    cls, fl = fleche(f, 0.5)
    v = (('<span class="cw-f ' + cls + '">' + fl + "</span>" if fl else "")
         + "<b>" + ("+" if (f or 0) >= 0 else "−")
         + ("%.1f" % abs(f or 0)).replace(".", ",") + "</b>")

    def dit(cle):
        return (NOM_MOTEUR.get(cle, cle) + ' <span class="cw-num">'
                + ("+" if ap[cle] >= 0 else "−") + ("%.1f" % abs(ap[cle])).replace(".", ",")
                + "</span>")

    ordre = sorted(ap, key=lambda k: ap[k], reverse=True)
    porte = [c for c in ordre if ap[c] >= 0.25][:2]
    freine = [c for c in reversed(ordre) if ap[c] <= -0.25][:1]
    if porte:
        v += ' <span class="s">· porté par ' + liste_fr([dit(c) for c in porte]) + "</span>"
    if freine:
        v += ' <span class="s">· freiné par ' + dit(freine[0]) + "</span>"
    if not porte and not freine:
        v += ' <span class="s">· aucun moteur dominant, ils se compensent</span>'
    a = d.get("accord")
    if isinstance(a, list) and len(a) == 2 and a[1]:
        cls2 = "pos" if a[0] * 2 >= a[1] * 1.5 else ("neg" if a[0] * 2 <= a[1] else "neu")
        v += (' <span class="s">· </span><span class="cw-part ' + cls2 + '"><b>'
              + str(a[0]) + " moteurs sur " + str(a[1])
              + '</b> <i>d\'accord</i></span>')
    return v


def speculateurs(pd):
    """Ce que font les grands spéculateurs, en une ligne lisible.

    Le net rapporté à l'intérêt ouvert dit de quel côté ils sont ; la place
    dans la fourchette de trois ans dit si c'est déjà tendu ; la variation
    hebdomadaire dit dans quel sens ils bougent en ce moment.
    """
    net, place = pd.get("net_pct"), pd.get("place")
    var = pd.get("var_hebdo")
    if net is None or place is None:
        return ""
    cls, fl = fleche(net, 1.0)
    sens = "nets acheteurs" if net >= 1.0 else ("nets vendeurs" if net <= -1.0 else "quasi neutres")
    v = (('<span class="cw-f ' + cls + '">' + fl + "</span>" if fl else "")
         + "<b>" + sens + "</b> "
         + '<span class="cw-num">' + ("+" if net > 0 else "")
         + ("%.1f" % net).replace(".", ",") + " %</span>"
         + ' <span class="s">· ' + tenue(place) + "</span>")
    if var is not None:
        c2, _ = fleche(var, 0.3)
        # « -0,0 » n'existe pas : en deca d'un dixieme de point, on le dit.
        if abs(var) < 0.05:
            v += ' <span class="s">· sans changement cette semaine</span>'
        else:
            v += (' <span class="s">· </span><span class="cw-part ' + c2 + '"><b>'
                  + ("+" if var > 0 else "−") + ("%.1f" % abs(var)).replace(".", ",")
                  + "</b> <i>pt/sem.</i></span>")
    j = date_courte(pd.get("rapport"))
    if j:
        v += ' <span class="s">· relevé du ' + j + "</span>"
    return v


sem = H.get("semaine") or {}
jours = sem.get("jours") or []
faits = H.get("faits") or []
devises = H.get("devises") or []


def delai(iso):
    return ('<span class="cd" data-iso="' + esc(iso) + '">—</span>') if iso else ""


# ==========================================================================
# 1. Le bandeau : la semaine, et rien d'autre
# ==========================================================================
p = ['<section class="hw" aria-label="' + esc(sem.get("titre", "Semaine")) + '">']
p.append('<div class="hw-head"><span class="hw-dot" aria-hidden="true"></span>'
         "<h2>" + esc(sem.get("titre", "")) + "</h2>"
         '<span class="hw-when">vérifié à <b>' + esc(H.get("verifie", "")) +
         "</b></span></div>")

if not H.get("flux_ok", True):
    p.append('<div class="hw-note">Le calendrier économique n’a pas répondu lors de ce passage. '
             "Les réunions de banques centrales restent à jour ; les publications statistiques "
             "seront complétées au prochain passage.</div>")
elif sem.get("en_attente"):
    p.append('<div class="hw-note">Le calendrier de la semaine à venir paraît le dimanche. '
             "D’ici là, seules les réunions de banques centrales, connues de longue date, "
             "sont affichées.</div>")

if faits:
    p.append('<div class="hw-faits"><span class="lab">Vient de paraître</span>')
    for f in faits:
        cls, fl = fleche(f.get("poids"))
        mot = "soutient" if cls == "pos" else ("pèse" if cls == "neg" else "sans effet net")
        p.append('<span class="hw-fait"><span class="code">' + esc(f.get("code")) + "</span> " +
                 esc(f.get("libelle")) + ' <span class="v">' + esc(f.get("valeur")) + " (" +
                 esc(f.get("variation")) + ')</span> <span class="cw-f ' + cls + '">' + fl +
                 "</span>" + mot + "</span>")
    p.append("</div>")

p.append('<div class="hw-grille">')
for j in jours:
    cls = "hw-j"
    if j.get("aujourdhui"):
        cls += " auj"
    elif j.get("passe"):
        cls += " passe"
    p.append('<div class="' + cls + '"><div class="hw-jt">' + esc(j.get("nom", "")[:3]) +
             " <b>" + esc(j.get("num", "")) + "</b> " + esc(j.get("mois", "")) + "</div>")
    liste = j.get("evenements", [])
    if not liste:
        p.append('<div class="hw-rien">—</div>')
    # Le tableau ayant disparu, la grille peut respirer : on montre jusqu'a six
    # echeances par jour et on ne compte le reste qu'au-dela.
    trop = len(liste) - 6
    for e in (liste[:6] if trop > 0 else liste):
        ecls, _ = fleche(e.get("attendu"))
        bord = "bc" if e.get("source") == "banque centrale" else (ecls if ecls != "neu" else "")
        chif = ""
        if e.get("consensus") or e.get("precedent"):
            bits = []
            if e.get("consensus"):
                bits.append("<b>" + esc(e["consensus"]) + "</b>")
            if e.get("precedent"):
                bits.append(esc(e["precedent"]))
            chif = '<div class="hw-chiffres">' + " ← ".join(bits) + "</div>"
        p.append('<div class="hw-ev ' + bord + '"><div class="hw-e1">'
                 '<span class="code">' + esc(e.get("code")) + "</span>"
                 '<span class="hw-h">' + esc(e.get("heure", "")) + "</span></div>"
                 '<div class="hw-t">' + esc(court(e.get("titre"), 44)) + "</div>" + chif + "</div>")
    if trop > 0:
        p.append('<div class="hw-plus">+ ' + str(trop) + " autre" + ("s" if trop > 1 else "") + "</div>")
    p.append("</div>")
p.append("</div>")

p.append('<div class="hw-foot">Seules les échéances classées « fort impact » figurent ici : '
         "décisions de taux, inflation, emploi, PIB, PMI, discours de gouverneurs. Les chiffres "
         "sous chaque intitulé se lisent <b>consensus ← valeur précédente</b>. Le détail par "
         "devise est sur sa carte ci-dessous. Le robot passe plusieurs fois par jour, aux heures "
         "que l’hébergeur lui accorde ; les délais, eux, se recalculent en direct dans votre "
         "navigateur et restent donc justes à la minute.</div>")
p.append("</section>")
BANDEAU = "".join(p)


# ==========================================================================
# 1 bis. Ce que le modele vaut : convictions, mesure, redondance
# ==========================================================================
def pourcent(v, dec=2):
    if v is None:
        return "—"
    return (("+" if v > 0 else ("−" if v < 0 else ""))
            + (("%." + str(dec) + "f") % abs(v)).replace(".", ",") + " %")


def ic_mot(ic):
    """Un coefficient d'information se lit sur une echelle serree : en change,
    0,05 est deja un bon signal et 0,10 est rare."""
    if ic is None:
        return "neu", "non mesuré"
    if ic >= 0.05:
        return "pos", "bon"
    if ic >= 0.02:
        return "pos", "exploitable"
    if ic > -0.02:
        return "neu", "sans contenu"
    return "neg", "à contre-emploi"


def bloc_valeur():
    conv = MJ.get("convictions") or []
    mes = MJ.get("mesure") or {}
    grap = MJ.get("grappes") or []
    if not conv and not mes:
        return ""

    g = ['<section class="cv"><div class="cv-head"><h2>Ce que le modèle vaut</h2>'
         '<span class="cv-when">mesuré sur ' + str(MJ.get("seances", "—")) +
         ' séances de cours</span></div><div class="cv-corps">']

    g.append('<div class="cv-col"><span class="cv-t">Meilleures convictions</span>')
    if conv:
        for c in conv[:3]:
            g.append('<div class="cv-l"><b>' + esc(c.get("paire")) + "</b> "
                     '<span class="cv-n">écart ' + str(c.get("ecart")) + " pts</span>"
                     ' <span class="s">· ' + str(round((c.get("soutien") or 0) * 100)) +
                     " % des moteurs d'accord · </span>"
                     '<span class="cv-n">' + pourcent(c.get("attendu_5j")) + "</span>"
                     ' <span class="s">attendu sur 5 j, pour ' +
                     (("%.2f" % (c.get("sigma_5j") or 0)).replace(".", ",")) +
                     " % d'écart-type</span></div>")
    else:
        g.append('<div class="cv-l"><span class="s">indisponible</span></div>')
    if grap:
        def lien(x):
            r = x.get("correlation") or 0.0
            return (esc(x.get("a")) + " et " + esc(x.get("b")) + ' <span class="cv-n">' +
                    ("%.2f" % r).replace(".", ",") + "</span>" +
                    ('<span class="s"> (inverse)</span>' if r < 0 else ""))
        g.append('<span class="cv-t">Devises liées</span><div class="cv-l">' +
                 ' <span class="s">·</span> '.join(lien(x) for x in grap) + "</div>")
    if conv:
        g.append('<div class="cv-note">'
                 "La conviction est l'écart de biais pondéré par l'accord des moteurs des "
                 "deux côtés. Le mouvement attendu est volontairement modeste : en change, "
                 "même un très bon signal ne revendique qu'une fraction de l'écart-type, et "
                 "le voir écrit évite de confondre une direction avec une promesse. Deux "
                 "devises fortement liées, dans un sens ou dans l'autre, ne font qu'un seul "
                 "pari.</div>")
    g.append("</div>")

    g.append('<div class="cv-col"><span class="cv-t">Ce que valent les signaux</span>')
    lignes = []
    for cle, nom, horizons in (("technique", "Graphiques", ("5j", "21j")),
                               ("positionnement", "Spéculateurs", ("1sem", "4sem"))):
        bloc = mes.get(cle) or {}
        for h in horizons:
            r = bloc.get(h)
            if not r:
                continue
            cls, mot = ic_mot(r.get("ic"))
            mot_h = {"5j": "5 jours", "21j": "21 jours",
                     "1sem": "une semaine", "4sem": "quatre semaines"}.get(h, h)
            lignes.append('<div class="cv-l">' + nom + ' <span class="s">à ' + mot_h + ' · </span>'
                          '<span class="cw-part ' + cls + '"><b>IC ' +
                          (("%.2f" % r["ic"]).replace(".", ",") if r.get("ic") is not None else "—") +
                          "</b> <i>" + mot + "</i></span>"
                          '<span class="s">' + str(r.get("reussite")) + " % de réussite sur " +
                          str(r.get("n")) + " observations</span></div>")
    b = (mes.get("biais_publie") or {}).get("5j")
    if b:
        cls, mot = ic_mot(b.get("ic"))
        lignes.append('<div class="cv-l">Biais publié <span class="s">à 5 jours · </span>'
                      '<span class="cw-part ' + cls + '"><b>IC ' +
                      ("%.2f" % b["ic"]).replace(".", ",") + "</b> <i>" + mot + "</i></span>"
                      '<span class="s">' + str(b.get("reussite")) + " % de réussite sur " +
                      str(b.get("n")) + " observations</span></div>")
    elif mes.get("memoire_jours") is not None:
        lignes.append('<div class="cv-l">Biais publié <span class="s">· ' +
                      str(mes["memoire_jours"]) + " jour(s) d'historique hors échantillon, "
                      "pas encore mesurable — il se construit passage après passage.</span></div>")
    g.extend(lignes or ['<div class="cv-l"><span class="s">mesure indisponible</span></div>'])
    g.append('<div class="cv-note">'
             "Le coefficient d'information est la corrélation de rang entre le score annoncé "
             "et le mouvement qui a suivi. En change, 0,02 est exploitable et 0,05 est bon : "
             "les marchés ne laissent pas beaucoup plus. Ces mesures rejouent le passé sans "
             "jamais lire une donnée future, et elles ne servent pas à régler les poids du "
             "modèle — se noter sur sa propre copie ferait de beaux chiffres et de mauvaises "
             "prévisions. Les fondamentaux, eux, ne sont pas reconstituables : leur seule "
             "mesure honnête est le suivi du biais publié.</div>")
    g.append("</div></div></section>")
    return "".join(g)


VALEUR = bloc_valeur()


# ==========================================================================
# 2. Une pastille par carte de devise
# ==========================================================================
def ligne(cle, valeur):
    return '<div class="cw-l"><span class="cw-k">' + cle + '</span><span class="cw-v">' + valeur + "</span></div>"


pastilles = {}
for d in devises:
    code = d.get("code")
    nb, reste = d.get("semaine_nb") or 0, d.get("semaine_reste") or 0
    lignes = []

    if reste:
        cls, fl = fleche(d.get("semaine_penchant"))
        v = ('<span class="cw-f ' + cls + '">' + fl + "</span>" if fl else "") + \
            "<b>" + str(reste) + " échéance" + ("s" if reste > 1 else "") + " à venir</b>"
        if d.get("semaine_mot"):
            v += ' <span class="s">· ' + esc(d["semaine_mot"]) + "</span>"
        lignes.append(ligne("Cette semaine", v))
    elif nb:
        v = "<b>" + str(nb) + " échéance" + ("s" if nb > 1 else "") + " passée" + \
            ("s" if nb > 1 else "") + "</b>"
        if d.get("semaine_resume"):
            v += ' <span class="s">· ' + esc(d["semaine_resume"]) + "</span>"
        lignes.append(ligne("Cette semaine", v))
    else:
        lignes.append(ligne("Cette semaine", '<span class="s">aucune échéance à fort impact</span>'))

    pubs = d.get("parutions") or []
    if pubs:
        pu = pubs[0]
        cls, fl = fleche(pu.get("poids"))
        v = ('<span class="cw-f ' + cls + '">' + fl + "</span>" if fl else "") + \
            "<b>" + esc(pu.get("libelle")) + " " + esc(pu.get("variation")) + "</b>" + \
            ' <span class="s">· ' + esc(pu.get("valeur")) + " · " + esc(pu.get("date_txt")) + "</span>"
        lignes.append(ligne("Déjà paru", v))

    m = MA.get(code) or {}
    if m:
        var = m.get("var") or {}
        det = m.get("detail") or {}
        mois = var.get("j21")
        v = courbe_svg(m.get("courbe") or [], (mois or 0) >= 0)
        v += ('<span class="cw-num">1 sem. ' + signe(var.get("j5")) + " · 1 mois "
              + signe(mois)
              + (" · RSI " + str(int(round(det["rsi"]))) if det.get("rsi") is not None else "")
              + "</span>")
        lignes.append(ligne("Force 90 j", v))

        t = fondation(m)
        if t:
            lignes.append(ligne("Fondamental", t))

        pd = m.get("pos_detail") or {}
        if pd:
            t = speculateurs(pd)
            if t:
                lignes.append(ligne("Spéculateurs", t))

        v = part("fond.", m.get("fondamental", 0.0)) + part("tech.", m.get("technique", 0.0))
        if m.get("positionnement") is not None:
            v += part("spéc.", m["positionnement"])
        v += part("flux", m.get("flux", 0.0))
        b7 = m.get("biais_7j")
        if isinstance(b7, (int, float)) and b7 != m.get("biais"):
            ec = m["biais"] - b7
            v += ('<span class="s">→ biais ' + str(m["biais"]) + " (" +
                  ("+" if ec > 0 else "") + str(ec) + " en 7 j)</span>")
        else:
            v += '<span class="s">→ biais ' + str(m.get("biais", "—")) + "</span>"
        att, sig = m.get("attendu_5j"), m.get("sigma_5j")
        if att is not None and sig:
            # Une direction sans amplitude n'engage a rien. On donne les deux,
            # et l'ecart-type a cote pour que la modestie du signal se voie.
            v += ('<span class="s">· </span><span class="cw-num">'
                  + ("+" if att >= 0 else "−") + ("%.2f" % abs(att)).replace(".", ",")
                  + " %</span><span class=\"s\"> attendu sur 5 j, écart-type "
                  + ("%.2f" % sig).replace(".", ",") + " %</span>")
        lignes.append(ligne("Composition", v))

    if d.get("prochain"):
        v = "<b>" + esc(court(d.get("prochain"), 48)) + "</b>"
        if d.get("prochain_txt"):
            v += ' <span class="s">· ' + esc(d["prochain_txt"]) + "</span> "
        v += delai(d.get("prochain_iso"))
        lignes.append(ligne("Prochaine", v))

    pastilles[code] = '<div class="cw">' + "".join(lignes) + "</div>"


def poser_pastilles(h):
    """Insere chaque pastille juste apres l'en-tete de la carte correspondante."""
    out, pos, n = [], 0, 0
    for m in re.finditer(r'<h3 class="ccy">([A-Z]{3})</h3>', h):
        code = m.group(1)
        if code not in pastilles:
            continue
        fin = h.find("</header>", m.end())
        if fin == -1:
            continue
        fin += len("</header>")
        out.append(h[pos:fin])
        out.append(pastilles[code])
        pos = fin
        n += 1
    out.append(h[pos:])
    return "".join(out), n


# ==========================================================================
# 3. Assemblage
# ==========================================================================
h = open("dashboard.html", encoding="utf-8").read()
if 'class="hw"' in h:
    print("Bandeau deja present.")
    raise SystemExit(0)

h = h.replace("</head>", CSS + "</head>", 1) if "</head>" in h else CSS + h

TETE = BANDEAU + VALEUR
m = re.search(r'(<div class="top-meta">.*?</div>\s*</div>)', h, re.S)
if m:
    h = h[:m.end()] + TETE + h[m.end():]
else:
    m2 = re.search(r'(<div class="wrap">)', h)
    h = (h[:m2.end()] + TETE + h[m2.end():]) if m2 else h.replace("<body>", "<body>" + TETE, 1)

h, poses = poser_pastilles(h)

# La pastille rend deux blocs de la carte redondants : la ligne « Prochaine
# reunion », qu'elle reprend avec un delai vivant, et la liste d'evenements,
# que la grille de la semaine affiche deja. Le commentaire « A surveiller »,
# lui, n'existe nulle part ailleurs : il reste.
avant_meta = len(re.findall(r'<p class="meta-line"><strong>Prochaine réunion', h))
h = re.sub(r'\s*<p class="meta-line"><strong>Prochaine réunion.*?</p>', "", h, flags=re.S)


def alleger(m):
    watch = re.search(r'<p class="events-watch">(.*?)</p>', m.group(0), re.S)
    if not watch:
        return ""
    # « A surveiller » en titre puis « A surveiller ensuite : » dans le texte
    # bégaie ; on ne garde qu'une fois la formule.
    txt = re.sub(r"^\s*À surveiller ensuite\s*:\s*", "", watch.group(1))
    return ('<div class="events-block"><span class="stat-label">À surveiller</span>'
            '<p class="events-watch">' + txt + "</p></div>")


avant_ev = len(re.findall(r'<div class="events-block">', h))
h = re.sub(r'<div class="events-block">.*?</div>', alleger, h, flags=re.S)

# Drapeaux emoji : absents de Windows, ou ils se lisent « EU », « GB »… Le code
# a trois lettres, lui, s'affiche partout.
avant_dr = len(re.findall(r"[\U0001F1E6-\U0001F1FF]{2}", h))
h = re.sub(r"[\U0001F1E6-\U0001F1FF]{2}", "", h)
h = re.sub(r'<span class="flag"[^>]*>\s*</span>\s*', "", h)
h = re.sub(r'<span class="ev-flag"[^>]*>\s*</span>\s*', "", h)

h = h.replace("</body>", SCRIPT + "</body>", 1) if "</body>" in h else h + SCRIPT

for a, b in (
    ("scan complet 06h00 UTC + veille toutes les 4 h",
     "plusieurs passages par jour · délais recalculés en direct"),
    ("scan complet 06h00 UTC + veille à fort impact chaque heure",
     "plusieurs passages par jour · délais recalculés en direct"),
    ("dans les 4 heures (veille calendrier), scan complet demain à 06h00 UTC.",
     "au prochain passage du robot ; les délais affichés, eux, sont recalculés en direct."),
    ("dans l’heure (veille des échéances à fort impact), scan complet demain à 06h00 UTC.",
     "au prochain passage du robot ; les délais affichés, eux, sont recalculés en direct."),
):
    if a in h:
        h = h.replace(a, b)

open("dashboard.html", "w", encoding="utf-8").write(h)
print("Bandeau insere — " + str(sem.get("nb", 0)) + " echeance(s) dans la semaine, " +
      str(len(faits)) + " parution(s) en tete ; " + str(poses) + " pastille(s) sur les cartes ; " +
      str(avant_dr) + " drapeau(x) emoji, " + str(avant_meta) + " ligne(s) « prochaine reunion » et " +
      str(avant_ev) + " bloc(s) d'evenements redondants retires.")
