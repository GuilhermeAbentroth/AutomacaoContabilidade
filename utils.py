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

def intel_v_f(val):
    v = str(val).strip()
    if not v or v.lower() == "nan": return 0.0
    if re.match(r'^-?\d+\.\d+$', v): return float(v)
    if ',' in v and '.' in v: v = v.replace('.', '').replace(',', '.')
    elif ',' in v: v = v.replace(',', '.')
    v = re.sub(r'[^0-9.-]', '', v)
    try: return float(v)
    except: return 0.0