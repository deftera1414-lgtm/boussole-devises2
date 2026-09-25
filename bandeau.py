import json, html, re, sys, datetime as dt

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

def court(txt, n=58):
    t = str(txt or "").strip()
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"

def chiffres(ev):
    """« consensus 3,1% · précédent 3,0% », en n'affichant que ce qui existe."""
    bouts = []
    if ev.get("consensus"):
        bouts.append("consensus <b>" + esc(ev["consensus"]) + "</b>")
    if ev.get("precedent"):
        bouts.append("précédent " + esc(ev["precedent"]))
    return " · ".join(bouts)

CSS = """<style>
.hi{flex:1 0 100%;width:100%;background:var(--surface);border:1px solid var(--border);
  border-radius:12px;box-shadow:var(--shadow);margin:18px 0 4px;overflow:hidden;
  border-top:3px solid var(--gold)}
.hi-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:13px 18px 11px;
  border-bottom:1px solid var(--border)}
.hi-head h2{margin:0;font-family:var(--font-display);font-size:.95rem;letter-spacing:.01em;
  color:var(--text);font-weight:700}
.hi-pulse{width:9px;height:9px;border-radius:50%;background:var(--gold);flex:none;
  box-shadow:0 0 0 0 var(--gold);animation:hipulse 2.6s infinite}
@keyframes hipulse{0%{box-shadow:0 0 0 0 rgba(224,168,87,.55)}
  70%{box-shadow:0 0 0 9px rgba(224,168,87,0)}100%{box-shadow:0 0 0 0 rgba(224,168,87,0)}}
@media (prefers-reduced-motion:reduce){.hi-pulse{animation:none}}
.hi-when{margin-left:auto;font-family:var(--font-mono);font-size:.7rem;color:var(--text-muted);
  text-transform:uppercase;letter-spacing:.05em}
.hi-when b{color:var(--gold);font-weight:600}
.hi-warn{padding:9px 18px;font-size:.76rem;color:var(--fall-text);background:var(--surface-2);
  border-bottom:1px solid var(--border)}
.hi-now{padding:12px 18px 14px;border-bottom:1px solid var(--border)}
.hi-lab{font-family:var(--font-mono);font-size:.67rem;letter-spacing:.09em;text-transform:uppercase;
  color:var(--text-muted);margin-bottom:9px}
.hi-ev{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;padding:7px 0;
  border-top:1px dashed var(--border)}
.hi-ev:first-of-type{border-top:none}
.hi-cc{font-family:var(--font-mono);font-size:.74rem;font-weight:700;color:var(--text);
  flex:none;min-width:62px}
.hi-ti{font-size:.83rem;color:var(--text);font-weight:600;flex:1 1 200px}
.hi-src{font-size:.7rem;color:var(--text-muted);font-weight:400}
.hi-num{font-family:var(--font-mono);font-size:.72rem;color:var(--text-secondary);flex:none}
.hi-num b{color:var(--text);font-weight:600}
.hi-cd{font-family:var(--font-mono);font-size:.73rem;font-weight:700;flex:none;
  padding:2px 8px;border-radius:999px;background:var(--surface-2);color:var(--text-secondary);
  border:1px solid var(--border);white-space:nowrap}
.hi-cd.soon{color:var(--gold);border-color:var(--gold)}
.hi-cd.hot{color:#fff;background:var(--fall);border-color:var(--fall)}
.hi-cd.past{opacity:.55}
.hi-calme{padding:2px 0 0;font-size:.82rem;color:var(--text-secondary)}
.hi-scroll{overflow-x:auto}
.hi-tab{width:100%;border-collapse:collapse;font-size:.79rem;min-width:600px}
.hi-tab th{font-family:var(--font-mono);font-size:.64rem;letter-spacing:.07em;text-transform:uppercase;
  color:var(--text-muted);text-align:left;font-weight:500;padding:10px 12px;
  border-bottom:1px solid var(--border);white-space:nowrap}
.hi-tab td{padding:9px 12px;border-bottom:1px solid var(--border);color:var(--text-secondary);
  vertical-align:middle}
.hi-tab tr:last-child td{border-bottom:none}
.hi-dev{font-family:var(--font-mono);font-weight:700;color:var(--text);white-space:nowrap}
.hi-taux{font-family:var(--font-mono);color:var(--text);font-weight:600;white-space:nowrap}
.hi-chiffre{font-family:var(--font-mono);font-size:.74rem;white-space:nowrap;cursor:help}
.hi-ton{font-size:.72rem;padding:2px 8px;border-radius:999px;border:1px solid var(--border);
  white-space:nowrap;color:var(--text-secondary)}
.hi-ton.resserrement{color:var(--fall-text);border-color:var(--fall)}
.hi-ton.assouplissement{color:var(--rise-text);border-color:var(--rise)}
.hi-next{color:var(--text);font-weight:500}
.hi-next small{display:block;color:var(--text-muted);font-weight:400;font-family:var(--font-mono);
  font-size:.68rem;margin-top:2px}
.hi-ag{border-top:1px solid var(--border)}
.hi-ag>summary{cursor:pointer;list-style:none;padding:11px 18px;font-family:var(--font-display);
  font-size:.79rem;color:var(--text-secondary);display:flex;align-items:center;gap:9px}
.hi-ag>summary::-webkit-details-marker{display:none}
.hi-ag>summary::before{content:"\\25B8";color:var(--gold);transition:transform .15s}
.hi-ag[open]>summary::before{transform:rotate(90deg)}
.hi-ag .hi-ev{padding:7px 18px}
.hi-foot{padding:9px 18px 12px;font-size:.7rem;color:var(--text-muted);line-height:1.5}
.hi .sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@media (max-width:640px){
  .hi-when{margin-left:0;flex:1 0 100%}
  .hi-num{flex:1 0 100%}
  /* Sur telephone on garde l'essentiel : devise, taux, prochaine echeance. */
  .hi-tab{min-width:0}
  .hi-tab th:nth-child(3),.hi-tab td:nth-child(3),
  .hi-tab th:nth-child(4),.hi-tab td:nth-child(4),
  .hi-tab th:nth-child(5),.hi-tab td:nth-child(5){display:none}
  .hi-tab th,.hi-tab td{padding:9px 8px}
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
    var n = Date.now();
    var l = document.querySelectorAll(".hi [data-iso]");
    for (var i = 0; i < l.length; i++){
      var el = l[i], t = Date.parse(el.getAttribute("data-iso"));
      if (isNaN(t)) continue;
      var s = Math.round((t - n) / 1000);
      el.textContent = fmt(s);
      el.className = "hi-cd" + (s < 0 ? " past" : s < 3600 ? " hot" : s < 86400 ? " soon" : "");
      el.title = new Date(t).toLocaleString();
    }
  }
  tick();
  setInterval(tick, 30000);
})();
</script>"""

def ligne_ev(ev, dans_agenda=False):
    src = "" if ev.get("source") != "banque centrale" else \
          ' <span class="hi-src">(banque centrale)</span>'
    num = chiffres(ev)
    return ('<div class="hi-ev"><span class="hi-cc">' + FLAGS.get(ev["code"], "") + " " + esc(ev["code"]) +
            '</span><span class="hi-ti">' + esc(court(ev.get("titre"))) + src +
            '</span><span class="hi-cd" data-iso="' + esc(ev.get("iso")) + '">—</span>' +
            ('<span class="hi-num">' + num + "</span>" if num else "") + "</div>")

imm = H.get("imminents") or []
agenda = H.get("agenda") or []
devises = H.get("devises") or []
seuil = H.get("seuil_imminent_h", 36)
horizon = H.get("horizon_jours", 10)

parts = ['<section class="hi" aria-label="Informations à très fort impact">']
parts.append('<div class="hi-head"><span class="hi-pulse" aria-hidden="true"></span>'
             "<h2>À très fort impact</h2>"
             '<span class="hi-when">vérifié à <b>' + esc(H.get("verifie", "")) +
             "</b> · actualisé chaque heure</span></div>")

if not H.get("flux_ok", True):
    parts.append('<div class="hi-warn">Le calendrier économique n’a pas répondu lors de ce '
                 "passage. Les réunions de banques centrales ci-dessous restent à jour ; "
                 "les publications statistiques seront complétées au prochain passage.</div>")

parts.append('<div class="hi-now"><div class="hi-lab">\u00c0 l\u2019instant et dans les ' + str(seuil) + " heures</div>")
if imm:
    parts.extend(ligne_ev(e) for e in imm)
else:
    parts.append('<p class="hi-calme">Aucune échéance à très fort impact dans les '
                 + str(seuil) + " heures sur les huit devises.</p>")
parts.append("</div>")

parts.append('<div class="hi-scroll"><table class="hi-tab"><thead><tr>'
             "<th>Devise</th><th>Taux directeur</th><th>Orientation</th><th>Inflation</th>"
             "<th>Chômage</th><th>Prochaine échéance à fort impact</th>"
             '<th><span class="sr">Échéance</span></th>'
             "</tr></thead><tbody>")
for d in devises:
    ton = str(d.get("ton") or "")
    cd = ('<span class="hi-cd" data-iso="' + esc(d["prochain_iso"]) + '">—</span>') \
         if d.get("prochain_iso") else ""
    parts.append(
        "<tr>"
        '<td class="hi-dev">' + FLAGS.get(d.get("code"), "") + " " + esc(d.get("code")) + "</td>"
        '<td class="hi-taux">' + esc(court(d.get("taux"), 22)) + "</td>"
        '<td><span class="hi-ton ' + esc(ton) + '">' + esc(ton or "—") + "</span></td>"
        '<td class="hi-chiffre" title="' + esc(d.get("inflation_detail", "")) + '">'
        + esc(d.get("inflation")) + "</td>"
        '<td class="hi-chiffre" title="' + esc(d.get("chomage_detail", "")) + '">'
        + esc(d.get("chomage")) + "</td>"
        '<td class="hi-next">' + esc(court(d.get("prochain"), 52)) +
        "<small>" + esc(d.get("prochain_txt", "")) + "</small></td>"
        "<td>" + cd + "</td></tr>")
parts.append("</tbody></table></div>")

reste = [e for e in agenda if e not in imm]
if reste:
    parts.append('<details class="hi-ag"><summary>Agenda à fort impact — ' + str(horizon) +
                 " prochains jours (" + str(len(reste)) + ")</summary><div>")
    parts.extend(ligne_ev(e, True) for e in reste)
    parts.append("</div></details>")

parts.append('<div class="hi-foot">Ne figurent ici que les événements classés « fort '
             "impact » : décisions de taux, inflation, emploi, PIB, PMI et discours "
             "de gouverneurs. Compte à rebours calculé en direct dans votre navigateur ; "
             "le contenu est revérifié chaque heure.</div>")
parts.append("</section>")
BLOC = "".join(parts)

h = open("dashboard.html", encoding="utf-8").read()
if 'class="hi"' in h:
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

# La cadence annoncee doit dire la verite : le robot passe desormais chaque heure.
# On la corrige ici plutot que dans template.html, pour n'avoir qu'un fichier a tenir.
for avant, apres in (
    ("scan complet 06h00 UTC + veille toutes les 4 h",
     "scan complet 06h00 UTC + veille à fort impact chaque heure"),
    ("dans les 4 heures (veille calendrier), scan complet demain à 06h00 UTC.",
     "dans l’heure (veille des échéances à fort impact), "
     "scan complet demain à 06h00 UTC."),
):
    if avant in h:
        h = h.replace(avant, apres)
    else:
        print("Cadence : formule introuvable, laissee en l'etat -> " + avant[:44])
open("dashboard.html", "w", encoding="utf-8").write(h)
print("Bandeau insere — " + str(len(imm)) + " imminent(s), " + str(len(reste)) +
      " a l'agenda, " + str(len(devises)) + " devises.")
