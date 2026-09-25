"""Boussole Devises — rendu du bandeau hebdomadaire dans dashboard.html.

Trois niveaux, dans cet ordre : ce qui vient de paraitre et ce que ca change,
la semaine posee jour par jour, puis les huit devises avec ce que la semaine
leur reserve et ce qui leur est deja tombe dessus.
"""
import json, html, re, datetime as dt

FLAGS = {"USD": "\U0001F1FA\U0001F1F8", "EUR": "\U0001F1EA\U0001F1FA", "GBP": "\U0001F1EC\U0001F1E7",
         "JPY": "\U0001F1EF\U0001F1F5", "CHF": "\U0001F1E8\U0001F1ED", "CAD": "\U0001F1E8\U0001F1E6",
         "AUD": "\U0001F1E6\U0001F1FA", "NZD": "\U0001F1F3\U0001F1FF"}

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
    """Rend le sens d'un score : classe CSS, symbole, sans jamais inventer."""
    if x is None:
        return "", ""
    if x >= seuil:
        return "pos", "↗"
    if x <= -seuil:
        return "neg", "↘"
    return "neu", "·"


CSS = """<style>
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

/* --- ce qui vient de paraitre --- */
.hw-faits{padding:11px 18px;border-bottom:1px solid var(--border);display:flex;
  gap:8px 18px;flex-wrap:wrap;align-items:baseline}
.hw-faits .lab{font-family:var(--font-mono);font-size:.63rem;letter-spacing:.09em;
  text-transform:uppercase;color:var(--text-muted);flex:none}
.hw-fait{font-size:.81rem;color:var(--text-secondary)}
.hw-fait b{color:var(--text);font-weight:600}
.hw-fait .v{font-family:var(--font-mono);font-size:.78rem}

/* --- la semaine --- */
.hw-grille{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));
  border-bottom:1px solid var(--border)}
.hw-j{border-right:1px solid var(--border);padding:9px 8px 11px;min-height:96px}
.hw-j:last-child{border-right:none}
.hw-j.passe{opacity:.72}
.hw-j.auj{background:var(--gold-tint)}
.hw-j.vide{background:transparent}
.hw-jt{font-family:var(--font-mono);font-size:.63rem;letter-spacing:.06em;text-transform:uppercase;
  color:var(--text-muted);margin-bottom:7px;display:flex;align-items:baseline;gap:5px}
.hw-j.auj .hw-jt{color:var(--gold);font-weight:700}
.hw-jt b{color:var(--text-secondary);font-size:.78rem;font-weight:700}
.hw-j.auj .hw-jt b{color:var(--gold)}
.hw-ev{border-left:2px solid var(--border);padding:3px 0 3px 7px;margin-bottom:7px}
.hw-ev.pos{border-left-color:var(--rise)}
.hw-ev.neg{border-left-color:var(--fall)}
.hw-ev.bc{border-left-color:var(--gold)}
.hw-e1{display:flex;gap:5px;align-items:baseline;flex-wrap:wrap}
.hw-cc{font-family:var(--font-mono);font-size:.68rem;font-weight:700;color:var(--text)}
.hw-h{font-family:var(--font-mono);font-size:.63rem;color:var(--text-muted)}
.hw-t{font-size:.74rem;color:var(--text-secondary);line-height:1.35;margin-top:1px}
.hw-chiffres{font-family:var(--font-mono);font-size:.66rem;color:var(--text-muted);margin-top:2px}
.hw-chiffres b{color:var(--text-secondary);font-weight:600}
.hw-rien{font-size:.72rem;color:var(--text-muted);padding-top:4px}

/* --- les devises --- */
.hw-scroll{overflow-x:auto}
.hw-tab{width:100%;border-collapse:collapse;font-size:.79rem;min-width:620px}
.hw-tab th{font-family:var(--font-mono);font-size:.62rem;letter-spacing:.07em;text-transform:uppercase;
  color:var(--text-muted);text-align:left;font-weight:500;padding:10px 12px;
  border-bottom:1px solid var(--border);white-space:nowrap}
.hw-tab td{padding:9px 12px;border-bottom:1px solid var(--border);color:var(--text-secondary);
  vertical-align:middle}
.hw-tab tr:last-child td{border-bottom:none}
.hw-dev{font-family:var(--font-mono);font-weight:700;color:var(--text);white-space:nowrap}
.hw-taux{font-family:var(--font-mono);color:var(--text);font-weight:600;white-space:nowrap}
.hw-ton{font-size:.71rem;padding:2px 8px;border-radius:999px;border:1px solid var(--border);
  white-space:nowrap;color:var(--text-secondary)}
.hw-ton.resserrement{color:var(--fall-text);border-color:var(--fall)}
.hw-ton.assouplissement{color:var(--rise-text);border-color:var(--rise)}
.hw-sig{white-space:nowrap;font-size:.76rem}
.hw-sig .f{font-family:var(--font-mono);font-weight:700}
.hw-sig .f:not(:empty){margin-right:4px}
.hw-sig.pos .f{color:var(--rise-text)}
.hw-sig.neg .f{color:var(--fall-text)}
.hw-sig.neu .f{color:var(--text-muted)}
.hw-sig small{display:block;color:var(--text-muted);font-size:.68rem;white-space:normal;
  line-height:1.35;margin-top:1px}
.hw-next{color:var(--text);font-weight:500}
.hw-next small{display:block;color:var(--text-muted);font-weight:400;font-family:var(--font-mono);
  font-size:.67rem;margin-top:2px}
.hw-cd{font-family:var(--font-mono);font-size:.72rem;font-weight:700;white-space:nowrap;
  padding:2px 8px;border-radius:999px;background:var(--surface-2);color:var(--text-secondary);
  border:1px solid var(--border)}
.hw-cd.soon{color:var(--gold);border-color:var(--gold)}
.hw-cd.hot{color:#fff;background:var(--fall);border-color:var(--fall)}
.hw-cd.past{opacity:.5}
.hw-cdm{display:none}
.hw-foot{padding:9px 18px 12px;font-size:.69rem;color:var(--text-muted);line-height:1.5}
.hw .sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}

@media (max-width:900px){
  .hw-grille{grid-template-columns:repeat(3,minmax(0,1fr))}
  .hw-j{border-bottom:1px solid var(--border);min-height:0}
  .hw-j.vide{display:none}
}
@media (max-width:860px){
  /* tablette : on sacrifie l'orientation, lisible sur la carte de la devise */
  .hw-tab th:nth-child(3),.hw-tab td:nth-child(3){display:none}
}
@media (max-width:620px){
  .hw-grille{grid-template-columns:1fr}
  .hw-j{border-right:none}
  .hw-when{margin-left:0;flex:1 0 100%}
  /* Sur telephone : la devise, ce qui vient de paraitre, et la prochaine
     echeance. Taux et orientation restent lisibles sur les cartes en dessous. */
  .hw-tab{min-width:0}
  .hw-tab th:nth-child(2),.hw-tab td:nth-child(2),
  .hw-tab th:nth-child(3),.hw-tab td:nth-child(3),
  .hw-tab th:nth-child(4),.hw-tab td:nth-child(4){display:none}
  .hw-tab th,.hw-tab td{padding:9px 6px}
  .hw-sig{white-space:normal}
  .hw-sig small{display:none}
  .hw-next small{font-size:.63rem}
  .hw-cd{padding:1px 6px;font-size:.66rem}
  /* le delai rejoint la cellule plutot que d'occuper une colonne */
  .hw-cdm{display:inline-block;margin-left:6px}
  .hw-tab th:nth-child(7),.hw-tab td:nth-child(7){display:none}
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
    var n = Date.now(), l = document.querySelectorAll(".hw [data-iso]");
    for (var i = 0; i < l.length; i++){
      var el = l[i], t = Date.parse(el.getAttribute("data-iso"));
      if (isNaN(t)) continue;
      var s = Math.round((t - n) / 1000);
      el.textContent = fmt(s);
      el.className = "hw-cd" + (s < 0 ? " past" : s < 3600 ? " hot" : s < 86400 ? " soon" : "");
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

p = ['<section class="hw" aria-label="' + esc(sem.get("titre", "Semaine")) + '">']

# ---------- en-tete ----------
p.append('<div class="hw-head"><span class="hw-dot" aria-hidden="true"></span>'
         "<h2>" + esc(sem.get("titre", "")) + "</h2>"
         '<span class="hw-when">vérifié à <b>' + esc(H.get("verifie", "")) +
         "</b> · chaque heure</span></div>")

if not H.get("flux_ok", True):
    p.append('<div class="hw-note">Le calendrier économique n’a pas répondu lors de ce '
             "passage. Les réunions de banques centrales restent à jour ; les publications "
             "statistiques seront complétées au prochain passage.</div>")
elif sem.get("en_attente"):
    p.append('<div class="hw-note">Le calendrier de la semaine à venir paraît le dimanche. '
             "D’ici là, seules les réunions de banques centrales, connues de longue date, "
             "sont affichées.</div>")

# ---------- ce qui vient de paraitre ----------
if faits:
    p.append('<div class="hw-faits"><span class="lab">Vient de paraître</span>')
    for f in faits:
        cls, fl = fleche(f.get("poids"))
        p.append('<span class="hw-fait">' + FLAGS.get(f.get("code"), "") + " <b>" +
                 esc(f.get("code")) + "</b> " + esc(f.get("libelle")) +
                 ' <span class="v">' + esc(f.get("valeur")) + " (" + esc(f.get("variation")) +
                 ')</span> <span class="hw-sig ' + cls + '"><span class="f">' + fl + "</span>" +
                 esc("soutient" if cls == "pos" else ("pèse" if cls == "neg" else "neutre")) +
                 "</span></span>")
    p.append("</div>")

# ---------- la semaine, jour par jour ----------
p.append('<div class="hw-grille">')
for j in jours:
    cls = "hw-j"
    if j.get("aujourdhui"):
        cls += " auj"
    elif j.get("passe"):
        cls += " passe"
    if not j.get("nb"):
        cls += " vide"
    p.append('<div class="' + cls + '"><div class="hw-jt">' + esc(j.get("nom", "")[:3]) +
             " <b>" + esc(j.get("num", "")) + "</b> " + esc(j.get("mois", "")) + "</div>")
    if not j.get("nb"):
        p.append('<div class="hw-rien">—</div>')
    for e in j.get("evenements", []):
        a = e.get("attendu")
        ecls, _ = fleche(a)
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
                 '<span class="hw-cc">' + FLAGS.get(e.get("code"), "") + " " + esc(e.get("code")) +
                 '</span><span class="hw-h">' + esc(e.get("heure", "")) + "</span></div>"
                 '<div class="hw-t">' + esc(court(e.get("titre"), 44)) + "</div>" + chif + "</div>")
    p.append("</div>")
p.append("</div>")

# ---------- les huit devises ----------
p.append('<div class="hw-scroll"><table class="hw-tab"><thead><tr>'
         "<th>Devise</th><th>Taux directeur</th><th>Orientation</th>"
         "<th>Cette semaine</th><th>Déjà paru</th><th>Prochaine échéance</th>"
         '<th><span class="sr">Délai</span></th></tr></thead><tbody>')
for d in devises:
    ton = str(d.get("ton") or "")

    # Ce qui reste prime ; une fois la semaine faite, on rappelle ce qu'elle
    # contenait plutot que d'ecrire huit fois « rien ».
    nb, reste = d.get("semaine_nb") or 0, d.get("semaine_reste") or 0
    if reste:
        scls, sfl = fleche(d.get("semaine_penchant"))
        sem_txt = str(reste) + " à venir"
        sem_sous = d.get("semaine_mot") or ""
    elif nb:
        scls, sfl = "neu", ""
        sem_txt = str(nb) + " échéance" + ("s" if nb > 1 else "") + " passée" + ("s" if nb > 1 else "")
        sem_sous = d.get("semaine_resume") or ""
    else:
        scls, sfl = "neu", ""
        sem_txt = "—"
        sem_sous = "semaine calme"

    ecls, efl = fleche(d.get("effet"))
    pubs = d.get("parutions") or []
    if pubs:
        pu = pubs[0]
        eff_txt = esc(pu.get("libelle")) + " " + esc(pu.get("variation"))
        eff_sous = esc(pu.get("valeur")) + " · " + esc(pu.get("date_txt"))
    else:
        ecls, efl = "neu", ""
        eff_txt, eff_sous = "—", ""

    cd = ('<span class="hw-cd" data-iso="' + esc(d["prochain_iso"]) + '">—</span>') \
        if d.get("prochain_iso") else ""

    p.append(
        "<tr>"
        '<td class="hw-dev">' + FLAGS.get(d.get("code"), "") + " " + esc(d.get("code")) + "</td>"
        '<td class="hw-taux">' + esc(court(d.get("taux"), 22)) + "</td>"
        '<td><span class="hw-ton ' + esc(ton) + '">' + esc(ton or "—") + "</span></td>"
        '<td class="hw-sig ' + scls + '"><span class="f">' + sfl + "</span>" + esc(sem_txt) +
        ("<small>" + esc(sem_sous) + "</small>" if sem_sous else "") + "</td>"
        '<td class="hw-sig ' + ecls + '"><span class="f">' + efl + "</span>" + eff_txt +
        ("<small>" + eff_sous + "</small>" if eff_sous else "") + "</td>"
        '<td class="hw-next">' + esc(court(d.get("prochain"), 42)) +
        "<small>" + esc(d.get("prochain_txt", "")) +
        ('<span class="hw-cdm">' + cd + "</span>" if cd else "") + "</small></td>"
        "<td>" + cd + "</td></tr>")
p.append("</tbody></table></div>")

p.append('<div class="hw-foot">Seuls les événements classés « fort impact » figurent ici. '
         "« Cette semaine » compare le consensus à la valeur précédente et indique vers "
         "quoi penchent les échéances restantes. « Déjà paru » ne retient que des chiffres "
         "effectivement publiés, et leur effet s’estompe sur " + str(H.get("memoire_jours", 7)) +
         " jours. Les délais se calculent en direct dans votre navigateur.</div>")
p.append("</section>")
BLOC = "".join(p)

h = open("dashboard.html", encoding="utf-8").read()
if 'class="hw"' in h:
    print("Bandeau deja present.")
    raise SystemExit(0)
h = h.replace("</head>", CSS + "</head>", 1) if "</head>" in h else CSS + h
m = re.search(r'(<div class="top-meta">.*?</div>\s*</div>)', h, re.S)
if m:
    h = h[:m.end()] + BLOC + h[m.end():]
else:
    m2 = re.search(r'(<div class="wrap">)', h)
    h = (h[:m2.end()] + BLOC + h[m2.end():]) if m2 else h.replace("<body>", "<body>" + BLOC, 1)
h = h.replace("</body>", SCRIPT + "</body>", 1) if "</body>" in h else h + SCRIPT

# La cadence annoncee doit dire la verite.
for avant, apres in (
    ("scan complet 06h00 UTC + veille toutes les 4 h",
     "scan complet 06h00 UTC + veille à fort impact chaque heure"),
    ("scan complet 06h00 UTC + veille à fort impact chaque heure",
     "scan complet 06h00 UTC + veille à fort impact chaque heure"),
    ("dans les 4 heures (veille calendrier), scan complet demain à 06h00 UTC.",
     "dans l’heure (veille des échéances à fort impact), scan complet demain à 06h00 UTC."),
):
    if avant in h:
        h = h.replace(avant, apres)
open("dashboard.html", "w", encoding="utf-8").write(h)
print("Bandeau hebdomadaire insere — " + str(sem.get("nb", 0)) + " echeance(s) dans la semaine, " +
      str(len(faits)) + " parution(s) en tete, " + str(len(devises)) + " devises.")
