import sys
import unicodedata
import re
import pandas as pd

def remover_acentos(texto):
    if not texto or not isinstance(texto, str): return str(texto) if texto else ""
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

def limpar_valor_universal(valor):
    if pd.isna(valor) or str(valor).strip() == "": return 0.0
    v = str(valor).replace('.', '').replace(',', '.')
    v = re.sub(r'[^0-9.-]', '', v)
    try: return float(v)
    except: return 0.0

def isolar_scroll_mouse(widget):
    """Impede que a roda do mouse role a tela geral (CTkScrollableFrame) ao mesmo tempo
    que uma caixa com scroll próprio (log, JSON bruto etc.) — ex.: scrolledtext.ScrolledText,
    que é um tkinter.Text puro por baixo.

    Motivo: o CTkScrollableFrame captura <MouseWheel> globalmente via bind_all e só ignora
    widgets que ele reconhece como "com scroll próprio" (CTkTextbox, CTkScrollbar, outro
    CTkScrollableFrame — ver customtkinter/ctk_scrollable_frame.py::_check_if_valid_scroll).
    Um tkinter.Text/ScrolledText não é reconhecido, então os dois scrolls disparavam juntos.

    Bindar <MouseWheel> direto no widget e retornar "break" resolve: no tkinter, o evento
    passa pelas bindtags do widget na ordem (widget, classe, toplevel, "all") — "break"
    interrompe essa cadeia antes que ela alcance o bind_all do container externo, então só
    o widget sob o cursor rola. Fora dele, ninguém tem esse binding e a tela geral rola normal.
    """
    def _on_mousewheel(event):
        if sys.platform == "darwin":
            widget.yview_scroll(-event.delta, "units")
        else:
            widget.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def _on_button4(event):
        widget.yview_scroll(-1, "units")
        return "break"

    def _on_button5(event):
        widget.yview_scroll(1, "units")
        return "break"

    alvos = [widget]
    barra = getattr(widget, "vbar", None)
    if barra is not None:
        alvos.append(barra)

    for alvo in alvos:
        alvo.bind("<MouseWheel>", _on_mousewheel)
        alvo.bind("<Button-4>", _on_button4)
        alvo.bind("<Button-5>", _on_button5)


def intel_v_f(val):
    v = str(val).strip()
    if not v or v.lower() == "nan": return 0.0
    if re.match(r'^-?\d+\.\d+$', v): return float(v)
    if ',' in v and '.' in v: v = v.replace('.', '').replace(',', '.')
    elif ',' in v: v = v.replace(',', '.')
    v = re.sub(r'[^0-9.-]', '', v)
    try: return float(v)
    except: return 0.0