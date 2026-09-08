# -*- coding: utf-8 -*-
"""
Boussole Devises — pipeline unique (v4 : scores en probabilité %, chips de
facteurs, note de divergence bias/momentum).

Entrée : currencies.json — {"generated_at": str, "currencies": {CODE: {...}}}
Sortie : data.json (currencies + 28 pairs calculées) et dashboard.html.

Horizons :
  Court terme : 6 heures — dominé par le momentum de surprise des dernières
                données (précédent vs actuel) ; fortement compressé vers 50
                (humilité assumée : pas de flux d'ordres / prix en direct).
  Moyen terme : 1-2 jours — mix momentum + biais fondamental, compression modérée.
  Long terme  : plus de 2 jours — biais fondamental (cycle banque centrale),
                peu compressé, comme l'ancien "moyen terme" macro.
Une compression additionnelle s'applique si un événement à impact élevé tombe
dans la fenêtre du calcul (event_6h / event_1_2d) : plus d'incertitude, donc
score tiré davantage vers 50, jamais vers un camp au hasard.

v4 (23 août 2026, correctif suite retour utilisateur) :
  - Tous les scores 0-100 (biais et probabilités de paire) sont désormais
    affichés comme une probabilité explicite en pourcentage + direction —
    ex. "Proba 62% Hausse" — plutôt qu'un score brut "62/100" jugé peu clair.
  - Le chip de momentum a été reformulé pour ne plus utiliser un vocabulaire
    hawkish/dovish qui entrait en collision visuelle avec le biais
    haussier/baissier (ex. AUD biais haussier + momentum "dovish" perçu à
    tort comme une incohérence). Le momentum est maintenant décrit comme une
    tendance de données ("en accélération" / "en ralentissement" / "stables").
  - Quand bias et momentum divergent (cas normal et informatif : deux
    horizons différents, pas un bug), une note explicative apparaît sur la
    carte (divergence_note).
  - Chaque carte affiche 4 "facteurs" indépendants (Taux, Inflation, Chômage,
    PIB) calculés à partir des données déjà présentes, pour que la note ne
    soit jamais une boîte noire — nécessite un nouveau champ `tilt`
    (hawkish/neutral/dovish) par devise dans currencies.json.
"""
import json, html, itertools, os, re

BASE = os.path.dirname(os.path.abspath(__file__))
ORDER = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY"]
FLAGS = {"USD": "🇺🇸", "EUR": "🇪🇺", "GBP": "🇬🇧", "JPY": "🇯🇵",
         "CHF": "🇨🇭", "CAD": "🇨🇦", "AUD": "🇦🇺", "NZD": "🇳🇿"}
MOVE_LABEL = {"hike": "Hausse", "cut": "Baisse", "hold": "Statu quo"}
MOVE_CLASS = {"hike": "chip-rise", "cut": "chip-fall", "hold": "chip-neutral"}


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def safe_num_field(v, default=0):
    """Coerce a bias/long_adj/momentum-style field to a number defensively.

    Ces champs DOIVENT être numériques pour que bucket()/format_score()/les
    comparaisons de divergence_note() fonctionnent — mais un agent de
    recherche écrit parfois par erreur un texte ("NON TROUVÉ", une chaîne
    vide, un champ manquant) là où seul un entier est attendu. Plutôt que de
    laisser une seule devise mal renseignée faire planter tout le build (et
    donc toute l'exécution planifiée), on retombe sur une valeur neutre par
    défaut et on continue."""
    if isinstance(v, bool):
        return default
    if isinstance(v, (int, float)):
        return v
    try:
        return round(float(str(v).replace(",", ".").strip()))
    except (TypeError, ValueError):
        return default


def bucket(score):
    if score >= 76: return "rise-3", "Haussier fort"
    if score >= 66: return "rise-2", "Haussier modéré"
    if score >= 56: return "rise-1", "Haussier faible"
    if score >= 45: return "neutral", "Neutre"
    if score >= 35: return "fall-1", "Baissier faible"
    if score >= 25: return "fall-2", "Baissier modéré"
    return "fall-3", "Baissier fort"


def format_score(score):
    """0-100 -> lecture explicite en probabilité : (pct, direction, force).

    pct = confiance dans le sens indiqué, toujours >= 50 (score 15 -> 85% Baisse).
    direction = 'Hausse' / 'Baisse' / 'Neutre'.
    force = qualificatif de la distance au neutre (50), pour éviter une fausse
    précision : un score à 51 n'inspire pas la même confiance qu'un score à 90.
    """
    score = clamp(score, 0, 100)
    pct = score if score >= 50 else 100 - score
    if score > 50:
        direction = "Hausse"
    elif score < 50:
        direction = "Baisse"
    else:
        direction = "Neutre"
    dist = abs(score - 50)
    if dist >= 26:
        force = "confiance forte"
    elif dist >= 16:
        force = "confiance modérée"
    elif dist >= 6:
        force = "confiance faible"
    else:
        force = "quasi neutre"
    return pct, direction, force


def score_unit_word(pct, direction):
    """(unité, mot-direction) affichés à côté du nombre pour un score déjà
    décomposé par format_score(). Cas particulier à pile 50/50 : affiche
    "/50 Neutre" plutôt que "% Neutre", pour éviter la lecture ambiguë
    "50% de confiance que c'est neutre" — on veut dire "exactement au
    milieu", pas "incertain"."""
    if direction == "Neutre":
        return "/50", "Neutre"
    return "%", direction


def esc(s):
    return html.escape(str(s), quote=True)


def compute_pairs(cur):
    pairs = []
    for base, quote in itertools.combinations(ORDER, 2):
        b, q = cur[base], cur[quote]
        b_bias, q_bias = b.get("bias", 50), q.get("bias", 50)
        b_mom, q_mom = b.get("momentum", 0), q.get("momentum", 0)
        b_adj, q_adj = b.get("long_adj", 0), q.get("long_adj", 0)

        diff_momentum = b_mom - q_mom
        diff_mix = 0.55 * diff_momentum + 0.45 * (b_bias - q_bias)
        diff_long = (b_bias + b_adj) - (q_bias + q_adj)

        event_6h = bool(b.get("event_6h") or q.get("event_6h"))
        event_12d = bool(b.get("event_1_2d") or q.get("event_1_2d"))

        prob_6h = clamp(round(50 + diff_momentum / 2 * 0.5 * (0.7 if event_6h else 1.0)), 35, 65)
        prob_12d = clamp(round(50 + diff_mix / 2 * 0.75 * (0.7 if event_12d else 1.0)), 25, 75)
        prob_gt2d = clamp(round(50 + diff_long / 2), 8, 92)

        def lab(p):
            return bucket(p)[1]

        pairs.append({
            "pair": f"{base}/{quote}", "base": base, "quote": quote,
            "short": {"prob": prob_6h, "label": lab(prob_6h), "event": event_6h},
            "medium": {"prob": prob_12d, "label": lab(prob_12d), "event": event_12d},
            "long": {"prob": prob_gt2d, "label": lab(prob_gt2d)},
        })
    return pairs


def gauge_html(score, aria_label=None, lo=8, hi=92):
    fillcls = "bar-rise" if score >= 50 else "bar-fall"
    left = min(50, score)
    width = abs(score - 50)
    label = aria_label or f"Indice directionnel {score} sur 100"
    return f'''
      <div class="gauge" role="img" aria-label="{esc(label)}">
        <div class="gauge-track">
          <div class="gauge-center"></div>
          <div class="gauge-fill {fillcls}" style="left:{left}%; width:{width}%;"></div>
          <div class="gauge-marker {fillcls}" style="left:{score}%;"></div>
        </div>
        <div class="gauge-scale"><span>0</span><span>50</span><span>100</span></div>
      </div>'''


_NUM_PCT_RE = re.compile(r'[+-]?\d+(?:[.,]\d+)?\s*%')
_NUM_RE = re.compile(r'[+-]?\d+(?:[.,]\d+)?')


def parse_num(s):
    """Extrait la valeur numérique pertinente d'une chaîne comme
    'T2 2026 : +1,5% (QoQ)' ou '3,4% (juil. 2026)'. Retourne None si rien trouvé.

    Version regex (corrige un bug réel de l'ancienne boucle caractère par
    caractère : elle prenait le PREMIER chiffre rencontré, donc confondait un
    label de trimestre/année — "T2", "2026" — avec la donnée elle-même quand
    le label précédait le chiffre dans la chaîne. Exemple vérifié : "T2 2026 :
    +1,5% ..." renvoyait 2.0 au lieu de 1.5). Toutes les valeurs manipulées
    ici sont des pourcentages : on cherche donc en priorité un nombre
    directement suivi de '%', ce qui écarte "T2"/"2026" (jamais suivis de %)
    même s'ils apparaissent avant la vraie donnée. À défaut d'un nombre suivi
    de %, on retombe sur le premier nombre signé/décimal trouvé."""
    s = str(s).replace("−", "-")
    m = _NUM_PCT_RE.search(s)
    if not m:
        m = _NUM_RE.search(s)
    if not m:
        return None
    token = m.group().rstrip("% \t").replace(",", ".")
    try:
        return float(token)
    except ValueError:
        return None


def delta_arrow(prev_val, curr_val, good_when_up=True):
    """Compare les valeurs numériques de tête de deux chaînes ('3,4%' etc.)."""
    p, c = parse_num(prev_val), parse_num(curr_val)
    if p is None or c is None or p == c:
        return "→", "flat"
    up = c > p
    cls = ("rise" if good_when_up else "fall") if up else ("fall" if good_when_up else "rise")
    return ("↑" if up else "↓"), cls


def stat_pair_html(label, prev, curr, good_when_up=True):
    arrow, cls = delta_arrow(prev, curr, good_when_up)
    return f'''
        <div class="stat">
          <span class="stat-label">{esc(label)}</span>
          <div class="stat-pair">
            <span class="stat-prev">{esc(prev)}</span>
            <span class="stat-arrow arrow-{cls}">{arrow}</span>
            <span class="stat-curr">{esc(curr)}</span>
          </div>
        </div>'''


def events_html(c):
    evs = c.get("events") or []
    watch = c.get("watch")
    if not evs:
        block = '<p class="events-empty">Calme — aucun événement à impact élevé dans les 4 prochains jours.</p>'
    else:
        items = "\n".join(
            f'<li><span class="ev-time">{esc(e.get("date", "?"))} · {esc(e.get("time", "?"))}</span>'
            f'<span class="ev-name">{esc(e.get("name", "?"))}</span>'
            f'<span class="ev-fc">prév. {esc(e.get("forecast", "?"))} · préc. {esc(e.get("previous", "?"))}</span></li>'
            for e in evs if isinstance(e, dict)
        )
        block = f'<ul class="events-list">{items}</ul>'
    watch_html = f'<p class="events-watch">À surveiller ensuite : {esc(watch)}</p>' if watch else ""
    return block + watch_html


def momentum_badge(m):
    """Chip de tendance des toutes dernières données. Vocabulaire volontairement
    distinct de celui du biais (Haussier/Baissier) pour ne jamais donner
    l'impression d'un désaccord avec le biais fondamental — ce sont deux
    signaux différents qui peuvent légitimement diverger (voir divergence_note)."""
    if m >= 4:
        return '<span class="chip chip-rise">Données ↗ en accélération</span>'
    if m <= -4:
        return '<span class="chip chip-fall">Données ↘ en ralentissement</span>'
    return '<span class="chip chip-neutral">Données → stables</span>'


def divergence_note(bias, momentum):
    """Quand le biais fondamental et le momentum récent pointent dans des sens
    opposés, ce n'est pas une incohérence : ce sont deux horizons différents.
    On l'explique explicitement plutôt que de laisser l'utilisateur y voir un bug."""
    bias_up, bias_down = bias >= 56, bias <= 44
    mom_up, mom_down = momentum >= 4, momentum <= -4
    if bias_up and mom_down:
        return ("<p class='divergence'>⚠ Signal de divergence : le biais fondamental reste haussier "
                "(posture de la banque centrale, change rarement) alors que les toutes dernières données "
                "ralentissent (momentum, change à chaque publication). Ce n'est pas une incohérence — deux "
                "horizons différents — mais un ralentissement qui se confirme peut annoncer un futur "
                "ajustement du biais.</p>")
    if bias_down and mom_up:
        return ("<p class='divergence'>⚠ Signal de divergence : le biais fondamental reste baissier "
                "(posture de la banque centrale, change rarement) alors que les toutes dernières données "
                "accélèrent (momentum, change à chaque publication). Ce n'est pas une incohérence — deux "
                "horizons différents — mais une accélération qui se confirme peut annoncer un futur "
                "ajustement du biais.</p>")
    return ""


def factor_chip_html(cls, label, txt):
    return (f'<div class="factor-chip factor-{cls}">'
            f'<span class="factor-label">{esc(label)}</span>'
            f'<span class="factor-txt">{esc(txt)}</span></div>')


def factor_grid_html(c):
    """4 facteurs indépendants derrière la note, pour qu'elle ne soit jamais
    une boîte noire : Taux, Inflation, Chômage, PIB. Tous les accès au dict
    passent par .get() avec une valeur de repli neutre : une clé manquante
    dans currencies.json (recherche incomplète, agent perturbé) ne doit
    jamais faire planter tout le build."""
    move, tilt = c.get("move", "hold"), c.get("tilt", "neutral")
    if move == "hike":
        rate = ("rise", "Taux", "Vient de monter")
    elif move == "cut":
        rate = ("fall", "Taux", "Vient de baisser")
    elif tilt == "hawkish":
        rate = ("rise", "Taux", "Statu quo, ton ferme")
    elif tilt == "dovish":
        rate = ("fall", "Taux", "Statu quo, ton accommodant")
    else:
        rate = ("neutral", "Taux", "Statu quo, attentiste")

    cpi_v = parse_num(c.get("cpi_current", ""))
    if cpi_v is None:
        infl = ("neutral", "Inflation", "Donnée non lue")
    else:
        # Cible dynamique par devise (au lieu de 2.0 codé en dur) : chaque
        # banque centrale a sa propre cible/bande — ex. RBA/RBNZ ~2,5%.
        # Voir le champ "cpi_target" dans currencies.json (repli 2.0).
        cible = c.get("cpi_target", 2.0)
        gap = cpi_v - cible
        cible_txt = f"{cible:g}%".replace(".", ",")
        if gap > 0.3:
            infl = ("rise", "Inflation", f"Au-dessus de la cible ({cible_txt})")
        elif gap < -0.3:
            infl = ("fall", "Inflation", f"En dessous de la cible ({cible_txt})")
        else:
            infl = ("neutral", "Inflation", f"Proche de la cible ({cible_txt})")

    _, u_cls = delta_arrow(c.get("unemp_previous", ""), c.get("unemp_current", ""), good_when_up=False)
    unemp = {"rise": ("rise", "Chômage", "En baisse (positif)"),
             "fall": ("fall", "Chômage", "En hausse (négatif)"),
             "flat": ("neutral", "Chômage", "Stable")}[u_cls]

    _, g_cls = delta_arrow(c.get("gdp_previous", ""), c.get("gdp_current", ""), good_when_up=True)
    gdp = {"rise": ("rise", "PIB", "Croissance accélère"),
           "fall": ("fall", "PIB", "Croissance ralentit"),
           "flat": ("neutral", "PIB", "Stable")}[g_cls]

    chips = "".join(factor_chip_html(cls, lbl, txt) for cls, lbl, txt in (rate, infl, unemp, gdp))
    return f'<div class="factor-grid">{chips}</div>'


def metric_tag(label, prev, curr, good_when_up=True):
    """Compact 'IPC↑' style tag with the same arrow colors used on the cards."""
    arrow, cls = delta_arrow(prev, curr, good_when_up)
    return f'<span class="mtag arrow-{cls}">{esc(label)}{arrow}</span>'


def momentum_compact(code, cur):
    c = cur[code]
    na = "NON TROUVÉ"
    tags = (
        metric_tag("IPC", c.get("cpi_previous", na), c.get("cpi_current", na), True)
        + metric_tag("Chôm.", c.get("unemp_previous", na), c.get("unemp_current", na), False)
        + metric_tag("PIB", c.get("gdp_previous", na), c.get("gdp_current", na), True)
    )
    return f'<strong>{code}</strong> {tags}'


def pair_reason_html(p, cur):
    base, quote = p["base"], p["quote"]
    b, q = cur[base], cur[quote]
    b_pct, b_dir, _ = format_score(b.get("bias", 50))
    q_pct, q_dir, _ = format_score(q.get("bias", 50))
    b_unit, b_dirword = score_unit_word(b_pct, b_dir)
    q_unit, q_dirword = score_unit_word(q_pct, q_dir)

    ev_note_6h = " ⚡ événement majeur imminent pour l'une des deux devises — confiance encore réduite." if p["short"]["event"] else ""
    ev_note_12d = " ⚡ événement majeur dans la fenêtre — confiance réduite." if p["medium"]["event"] else ""

    reason_short = (
        f'{momentum_compact(base, cur)} contre {momentum_compact(quote, cur)} — '
        f'lecture resserrée volontairement (6h, sans flux de prix en direct).{ev_note_6h}'
    )
    reason_medium = (
        f'{momentum_compact(base, cur)} contre {momentum_compact(quote, cur)}, pondéré par le biais '
        f'fondamental — {base} {b_pct}{b_unit} {b_dirword} contre {quote} {q_pct}{q_unit} {q_dirword}.{ev_note_12d}'
    )
    reason_long = (
        f'<strong>{base}</strong> — {esc(b.get("cycle", "NON TROUVÉ"))}.<br>'
        f'<strong>{quote}</strong> — {esc(q.get("cycle", "NON TROUVÉ"))}.'
    )

    return f'''
    <tr class="reason-row" data-for="{p["pair"]}" hidden>
      <td colspan="4">
        <div class="reason-grid">
          <div><span class="reason-h">Court terme (6h)</span><p>{reason_short}</p></div>
          <div><span class="reason-h">Moyen terme (1-2j)</span><p>{reason_medium}</p></div>
          <div><span class="reason-h">Long terme (&gt;2j)</span><p>{reason_long}</p></div>
        </div>
      </td>
    </tr>'''


def _source_label(u):
    """Libellé court et sûr pour une URL source à afficher, même si elle est
    malformée (pas de '//', ou 'NON TROUVÉ') — évite un IndexError sur
    u.split("//")[1] quand une source n'est pas une URL bien formée."""
    parts = str(u).split("//", 1)
    label = parts[1] if len(parts) > 1 else parts[0]
    return label[:46] + ("…" if len(label) > 46 else "")


def card_html(code, cur):
    c = cur[code]
    b_cls, _ = bucket(c["bias"])
    pct, direction, force = format_score(c["bias"])
    unit, dirword = score_unit_word(pct, direction)
    move = c.get("move", "hold")
    na = "NON TROUVÉ"
    sources_list = c.get("sources") or []
    sources_li = "\n".join(
        f'<li><a href="{esc(u)}" target="_blank" rel="noopener">{esc(_source_label(u))}</a></li>'
        for u in sources_list
    )
    return f'''
    <article class="card">
      <header class="card-head">
        <div class="card-id">
          <span class="flag" aria-hidden="true">{FLAGS[code]}</span>
          <div>
            <h3 class="ccy">{code}</h3>
            <p class="bank">{esc(c.get("bank", na))} &middot; {esc(c.get("chief", na))}</p>
          </div>
        </div>
        <span class="chip {MOVE_CLASS.get(move, "chip-neutral")}">{MOVE_LABEL.get(move, "Statu quo")}</span>
      </header>

      <div class="stat-row">
        {stat_pair_html("Taux directeur", c.get("rate_previous", na), c.get("rate_current", na), True)}
        {stat_pair_html("PIB (croissance)", c.get("gdp_previous", na), c.get("gdp_current", na), True)}
        {stat_pair_html("Inflation (IPC)", c.get("cpi_previous", na), c.get("cpi_current", na), True)}
        {stat_pair_html("Chômage", c.get("unemp_previous", na), c.get("unemp_current", na), False)}
      </div>

      <p class="meta-line"><strong>Dernier mouvement de taux&nbsp;:</strong> {esc(c.get("rate_change_date", na))}</p>
      <p class="meta-line"><strong>Prochaine réunion&nbsp;:</strong> {esc(c.get("next", na))}</p>
      <p class="meta-line"><strong>Cycle&nbsp;:</strong> {esc(c.get("cycle", na))}</p>

      <div class="bias-block">
        <div class="bias-head">
          <span class="stat-label">Biais fondamental (cycle banque centrale)</span>
          <span class="bias-num {b_cls}"><span class="proba-tag">Proba</span> {pct}<span class="bias-den">{unit}</span> {dirword}</span>
        </div>
        {gauge_html(c["bias"], aria_label=f"Biais fondamental : {pct}% {direction}, {force}")}
        <p class="bias-strength">{force} &middot; échelle 0–100 ci-dessus (50 = neutre)</p>
      </div>

      <div class="factor-block">
        <span class="stat-label">Facteurs pris en compte</span>
        {factor_grid_html(c)}
      </div>

      <div class="momentum-row">
        <span class="stat-label">Momentum données récentes</span>
        {momentum_badge(c["momentum"])}
      </div>
      {divergence_note(c["bias"], c["momentum"])}

      <div class="events-block">
        <span class="stat-label">Prochains événements (4 jours)</span>
        {events_html(c)}
      </div>

      <details class="speech"><summary>Dernier discours / déclaration</summary><p>{esc(c.get("speech", na))}</p></details>
      <details class="sources"><summary>Sources ({len(sources_list)})</summary><ul>{sources_li}</ul></details>
    </article>'''


def cell_html(h):
    pct, direction, force = format_score(h["prob"])
    unit, dirword = score_unit_word(pct, direction)
    ev_badge = ' <span class="ev-flag" title="Événement majeur dans cette fenêtre — confiance réduite">⚡</span>' if h.get("event") else ""
    return (f'<td class="cell {bucket(h["prob"])[0]}" data-prob="{h["prob"]}">'
            f'<span class="cell-pct">{pct}{unit} {esc(dirword)}</span>'
            f'<span class="cell-label">{esc(force)}</span>{ev_badge}</td>')


def build():
    with open(os.path.join(BASE, "currencies.json")) as f:
        src = json.load(f)
    cur = src["currencies"]
    generated_at = src.get("generated_at", "")

    missing = [k for k in ORDER if k not in cur]
    if missing:
        raise SystemExit(
            f"currencies.json est incomplet — devise(s) manquante(s) : {', '.join(missing)}. "
            f"Les 8 clés {ORDER} sont obligatoires (voir methodology.md)."
        )
    for code in ORDER:
        c = cur[code]
        c["bias"] = clamp(safe_num_field(c.get("bias"), 50), 0, 100)
        c["long_adj"] = safe_num_field(c.get("long_adj"), 0)
        c["momentum"] = safe_num_field(c.get("momentum"), 0)

    pairs = compute_pairs(cur)
    with open(os.path.join(BASE, "data.json"), "w") as f:
        json.dump({"currencies": cur, "pairs": pairs, "generated_at": generated_at}, f, ensure_ascii=False, indent=2)

    cards = "\n".join(card_html(c, cur) for c in ORDER)
    rows = []
    for p in pairs:
        rows.append(f'''
      <tr class="pair-row" data-pair="{p["pair"]}" data-base="{p["base"]}" data-quote="{p["quote"]}">
        <td class="pair-name">
          <button class="why-toggle" type="button" aria-expanded="false" aria-label="Voir le pourquoi de {p["pair"]}">
            <span class="chevron">▸</span>
            <span class="flag" aria-hidden="true">{FLAGS[p["base"]]}</span>{p["base"]}<span class="slash">/</span><span class="flag" aria-hidden="true">{FLAGS[p["quote"]]}</span>{p["quote"]}
          </button>
        </td>
        {cell_html(p["short"])}
        {cell_html(p["medium"])}
        {cell_html(p["long"])}
      </tr>{pair_reason_html(p, cur)}''')
    rows_html = "\n".join(rows)

    with open(os.path.join(BASE, "template.html")) as f:
        template = f.read()

    out = template.replace("__CARDS__", cards).replace("__ROWS__", rows_html)
    if generated_at:
        out = out.replace("__GENERATED_AT__", generated_at)

    with open(os.path.join(BASE, "dashboard.html"), "w") as f:
        f.write(out)

    print("Built dashboard.html —", len(out), "bytes,", len(pairs), "pairs")


if __name__ == "__main__":
    build()
