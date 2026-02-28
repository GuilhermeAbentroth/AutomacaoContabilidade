import pandas as pd
import os
import re
from unicodedata import normalize

class BaseProcessor:
    def __init__(self, pasta_pdf, pasta_excel):
        self.pasta_pdf = pasta_pdf
        self.pasta_excel = pasta_excel

    def limpar_valor(self, texto):
        if not texto: return 0.0
        # Remove R$, espaços e garante que o formato numérico seja Pythonic
        texto = str(texto).replace("R$", "").replace(" ", "").strip()
        if "," in texto:
            texto = texto.replace(".", "").replace(",", ".")
        try:
            return float(texto)
        except:
            return 0.0

    def remover_acentos(self, txt):
        if not txt: return ""
        return normalize('NFKD', str(txt)).encode('ASCII', 'ignore').decode('ASCII').upper()

    def preparar_dataframe(self, registros):
        """Padroniza o DF antes de salvar"""
        if not registros: return None
        df = pd.DataFrame(registros)
        # Garante a ordem das colunas
        colunas = ['DATA', 'HISTORICO', 'VALOR', 'TIPO']
        df = df[colunas]
        # Formata valor para o padrão brasileiro de Excel
        df['VALOR'] = df['VALOR'].apply(lambda x: "{:.2f}".format(x).replace(".", ","))
        return df

    def salvar_arquivo(self, df, nome_base):
        """Salva o Excel na pasta de destino"""
        n_s = nome_base + ".xlsx"
        caminho = os.path.join(self.pasta_excel, n_s)
        df.to_excel(caminho, index=False)
        return n_s