"""
Answer Aura — a soft colored glow flashes around the card after you answer,
colored by the grade you gave (green = know, yellow = other, red = Again).

The glow is rendered with CSS inside the reviewer webview (not a Qt overlay):
a solid fill with a soft rounded cut-out, faded via opacity. Chromium composites
this on the GPU, so the fade stays smooth with no pixel shimmer.
"""

import os
import json

from aqt import mw, gui_hooks
from aqt.qt import QDialog, QVBoxLayout, QAction, Qt, QDialogButtonBox
from aqt.utils import tooltip

_tuner_dialog = None
_cfg_cache = None
_pending_js = None
_last_web = None            # last known card-area size (w, h), used to size the tuner preview
_ADDON_DIR = os.path.dirname(__file__)

DEFAULT_ROLES = {"1": "dont", "2": "know", "3": "other", "4": "other"}


def _cfg():
    # cached so tuner Apply takes effect immediately; getConfig() is stale until restart
    global _cfg_cache
    if _cfg_cache is None:
        _cfg_cache = mw.addonManager.getConfig(__name__) or {}
    return _cfg_cache


def _glow_js(cfg, hex_color):
    # Builds the flash as three nested divs injected into the card page:
    #   container (overflow:hidden, sharp outer edge) > blur wrapper (filter:blur) > fill (clip-path hole)
    # The clip-path must be on an inner element and the blur on its parent, otherwise the blur
    # runs before the cut-out and does nothing. reach/blur/corner are percentages of half the
    # smaller side; pixels are computed in JS from the real viewport so tuner == real card.
    try:
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
    except Exception:
        r, g, b = 61, 220, 132
    a = max(0, min(255, int(cfg.get("glow_alpha", 130)))) / 255.0
    rgba = "rgba(%d,%d,%d,%.4f)" % (r, g, b, a)
    reach = float(cfg.get("reach_pct", 30))
    blur = float(cfg.get("blur_pct", 40))
    rad = float(cfg.get("corner_radius_pct", 20))
    dur = max(60, int(cfg.get("duration_ms", 700)))
    return (
        "(function(){var id='__aura_glow__';"
        "var o=document.getElementById(id); if(o&&o.parentNode)o.parentNode.removeChild(o);"
        "var W=window.innerWidth,H=window.innerHeight,half=Math.min(W,H)/2;"
        "var reach=%f/100*half,blur=%f/100*half,rad=%f/100*half;"
        "var M=blur+8,FW=W+2*M,FH=H+2*M;"
        "var x0=M+reach,y0=M+reach,x1=FW-M-reach,y1=FH-M-reach;"
        "var outer='M0 0 H'+FW+' V'+FH+' H0 Z',hole='';"
        "if(x1>x0&&y1>y0){var rr=Math.max(0,Math.min(rad,(x1-x0)/2,(y1-y0)/2));"
        "hole=rr<=0?('M'+x0+' '+y0+' H'+x1+' V'+y1+' H'+x0+' Z')"
        ":('M'+(x0+rr)+' '+y0+' H'+(x1-rr)+' A'+rr+' '+rr+' 0 0 1 '+x1+' '+(y0+rr)+' V'+(y1-rr)"
        "+' A'+rr+' '+rr+' 0 0 1 '+(x1-rr)+' '+y1+' H'+(x0+rr)+' A'+rr+' '+rr+' 0 0 1 '+x0+' '+(y1-rr)"
        "+' V'+(y0+rr)+' A'+rr+' '+rr+' 0 0 1 '+(x0+rr)+' '+y0+' Z');}"
        "var clip='path(evenodd, \"'+outer+' '+hole+'\")';"
        "var c=document.createElement('div');c.id=id;var cs=c.style;"
        "cs.position='fixed';cs.top='0';cs.left='0';cs.right='0';cs.bottom='0';"
        "cs.overflow='hidden';cs.pointerEvents='none';cs.zIndex='2147483647';"
        "cs.opacity='1';cs.transition='opacity %dms ease-out';"
        "var bw=document.createElement('div');var bs=bw.style;"
        "bs.position='absolute';bs.top=(-M)+'px';bs.left=(-M)+'px';bs.right=(-M)+'px';bs.bottom=(-M)+'px';"
        "bs.filter='blur('+blur+'px)';bs.webkitFilter='blur('+blur+'px)';"
        "var f=document.createElement('div');var fs=f.style;"
        "fs.position='absolute';fs.top='0';fs.left='0';fs.right='0';fs.bottom='0';"
        "fs.background='%s';fs.clipPath=clip;fs.webkitClipPath=clip;"
        "bw.appendChild(f);c.appendChild(bw);document.body.appendChild(c);"
        "requestAnimationFrame(function(){requestAnimationFrame(function(){c.style.opacity='0';});});"
        "setTimeout(function(){if(c&&c.parentNode)c.parentNode.removeChild(c);}, %d);"
        "})();"
        % (reach, blur, rad, dur, rgba, dur + 200)
    )


def _on_answer(reviewer, card, ease):
    global _pending_js, _last_web
    web = getattr(reviewer, "web", None)
    if web is not None:
        _last_web = (web.width(), web.height())

    cfg = _cfg()

    # skip decks the user turned off
    disabled = cfg.get("disabled_decks") or []
    if disabled:
        try:
            did = card.odid or card.did  # odid = original deck when in a filtered deck
            deck_name = mw.col.decks.name(did)
        except Exception:
            deck_name = None
        if deck_name and deck_name in disabled:
            _pending_js = None
            return

    roles = cfg.get("ease_roles") or DEFAULT_ROLES
    role = roles.get(str(ease), "off")
    if role == "off":
        _pending_js = None
        return
    color = {
        "dont": cfg.get("dont_know_color", "#FF3B30"),
        "know": cfg.get("know_color", "#3DDC84"),
        "other": cfg.get("other_color", "#FFC400"),
    }.get(role)
    if not color:
        _pending_js = None
        return
    _pending_js = _glow_js(cfg, color)


def _on_show_question(card):
    # Fire on the next question, not on answer: the webview reloads on card change,
    # which would wipe an element injected at answer time.
    global _pending_js
    if not _pending_js:
        return
    js = _pending_js
    _pending_js = None
    try:
        web = mw.reviewer.web
        if web is not None:
            web.eval(js)
    except Exception:
        pass


gui_hooks.reviewer_did_answer_card.append(_on_answer)
gui_hooks.reviewer_did_show_question.append(_on_show_question)


def _tuner_html():
    with open(os.path.join(_ADDON_DIR, "tuner.html"), encoding="utf-8") as f:
        html = f.read()
    cfg = dict(_cfg())
    cfg["_surface"] = list(_last_web) if _last_web else [1000, 620]
    try:
        cfg["_decks"] = sorted(d.name for d in mw.col.decks.all_names_and_ids())
    except Exception:
        cfg["_decks"] = [n for n, _ in mw.col.decks.all_names_and_ids()]
    return html.replace("/*INIT*/null/*INIT*/", json.dumps(cfg))


def _save_from_web(web, on_done=None):
    # pull the current config from the page (auraGetConfig) and persist it
    def cb(cfg):
        if not isinstance(cfg, dict):
            try:
                cfg = json.loads(cfg)
            except Exception as e:
                tooltip("Answer Aura: invalid config (%s)" % e)
                return
        global _cfg_cache
        cur = dict(_cfg())
        cur.update(cfg)
        mw.addonManager.writeConfig(__name__, cur)
        _cfg_cache = cur
        tooltip("Answer Aura: settings saved ✓")
        if on_done:
            on_done()
    web.evalWithCallback("auraGetConfig()", cb)


def open_tuner():
    global _tuner_dialog
    from aqt.webview import AnkiWebView
    # parent to the active window (may be the modal Add-ons dialog) and make the
    # tuner modal too, otherwise a modal parent steals all input and it can't be used/closed
    parent = mw.app.activeWindow() or mw
    d = QDialog(parent)
    d.setWindowModality(Qt.WindowModality.ApplicationModal)
    d.setWindowTitle("Answer Aura — glow tuner")
    d.resize(760, 900)
    lay = QVBoxLayout(d)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    web = AnkiWebView(parent=d)
    web.stdHtml(_tuner_html())
    lay.addWidget(web, 1)

    box = QDialogButtonBox()
    b_reset = box.addButton("Restore Defaults", QDialogButtonBox.ButtonRole.ResetRole)
    box.addButton(QDialogButtonBox.StandardButton.Cancel)
    box.addButton(QDialogButtonBox.StandardButton.Save)
    box.setContentsMargins(10, 8, 10, 10)
    lay.addWidget(box)

    b_reset.clicked.connect(lambda: web.eval("auraReset()"))
    # Save persists then closes; Cancel just closes (discarding unsaved changes)
    box.button(QDialogButtonBox.StandardButton.Save).clicked.connect(
        lambda: _save_from_web(web, on_done=d.accept))
    box.button(QDialogButtonBox.StandardButton.Cancel).clicked.connect(d.reject)

    try:
        cg = mw.screen().availableGeometry()
        d.move(cg.center().x() - d.width() // 2, cg.center().y() - d.height() // 2)
    except Exception:
        pass
    _tuner_dialog = d  # keep a reference so it isn't garbage-collected
    d.show()


# open the tuner from the add-on's Config button as well as the Tools menu
mw.addonManager.setConfigAction(__name__, open_tuner)

_act = QAction("Answer Aura — glow tuner", mw)
_act.triggered.connect(open_tuner)
mw.form.menuTools.addAction(_act)
