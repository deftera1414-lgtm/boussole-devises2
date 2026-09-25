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
import json, html, re

try:
    H = json.load(open("highlights.json", encoding="utf-8"))
except Exception as e:
    print("highlights.json illisible (" + str(e) + ") — bandeau non insere.")
    raise SystemExit(0)


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

m = re.search(r'(<div class="top-meta">.*?</div>\s*</div>)', h, re.S)
if m:
    h = h[:m.end()] + BANDEAU + h[m.end():]
else:
    m2 = re.search(r'(<div class="wrap">)', h)
    h = (h[:m2.end()] + BANDEAU + h[m2.end():]) if m2 else h.replace("<body>", "<body>" + BANDEAU, 1)

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
