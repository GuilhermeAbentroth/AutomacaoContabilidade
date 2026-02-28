import os
import re
import pdfplumber
from datetime import datetime
from base_processor import BaseProcessor


# ==========================================
# CLASSE 1: CAIXA V1 (Padrão Antigo D/C)
# ==========================================
class CaixaProcessorV1(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "CAIXA_V1"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo CAIXA V1: {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)
        linhas_texto = []

        try:
            with pdfplumber.open(caminho_pdf) as pdf:
                for page in pdf.pages:
                    texto = page.extract_text()
                    if texto: linhas_texto.extend(texto.split('\n'))

            registros = []
            for linha in linhas_texto:
                linha_limpa = linha.replace('\xa0', ' ').strip().upper()
                linha_limpa = re.sub(r'\s+', ' ', linha_limpa)

                match_data = re.search(r'(\d{2}/\d{2}/\d{4})', linha_limpa)
                if not match_data:
                    match_data = re.search(r'(\d{2}/\d{2})', linha_limpa[:5])
                    if not match_data: continue

                val_data = match_data.group(1)
                if len(val_data) == 5: val_data += f"/{datetime.now().year}"

                padrao_valor = r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*([DC])'
                matches_valor = list(re.finditer(padrao_valor, linha_limpa))
                if not matches_valor: continue

                transacao = matches_valor[0]
                texto_resto = linha_limpa.replace(val_data, "")
                for m in matches_valor: texto_resto = texto_resto.replace(m.group(0), "")

                texto_resto = re.sub(r'\b\d{4,}\b', '', texto_resto)
                val_hist = texto_resto.replace("NR. DOC", "").replace("HISTORICO", "").replace("DATA MOV", "")
                val_hist = re.sub(r'[.-]', '', val_hist)
                val_hist = re.sub(r'\s+', ' ', val_hist).strip()

                if "SALDO" in val_hist or "TOTAL" in val_hist: continue
                if not val_hist: val_hist = "HISTORICO NAO IDENTIFICADO"

                float_val = self.limpar_valor(transacao.group(1))
                tipo = "DEBITO" if transacao.group(2) == "D" else "CREDITO"
                valor_final = -abs(float_val) if tipo == "DEBITO" else abs(float_val)

                registros.append(
                    {"DATA": val_data, "HISTORICO": self.remover_acentos(val_hist).upper(), "VALOR": valor_final,
                     "TIPO": tipo})

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None: return self.salvar_arquivo(df, os.path.splitext(arquivo)[0] + "_V1")
            return None
        except Exception as e:
            log_func(f"Erro V1 {arquivo}: {e}", "erro")
            return None


# ==========================================
# CLASSE 2: CAIXA V2 HORIZONTAL (A que funcionou)
# ==========================================
class CaixaProcessorV2Horizontal(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "CAIXA_V2_HORIZ"

    def _processar_transacao(self, buffer):
        if not buffer: return None
        texto = " ".join(buffer['linhas']).replace('\n', ' ')
        texto = re.sub(r'\s+', ' ', texto).strip()

        if "SALDO DIA" in texto.upper() or "SALDO ANTERIOR" in texto.upper(): return None

        match_data = re.search(r'(\d{2}/\d{2}/\d{4})', texto)
        if not match_data: return None
        val_data = match_data.group(1)

        matches_valor = list(re.finditer(r'(-?\s*R\$\s*[\d\.,]+)', texto))
        if not matches_valor: return None

        val_str_raw = matches_valor[0].group(1)
        eh_negativo = "-" in val_str_raw
        val_clean = self.limpar_valor(val_str_raw.replace("-", "").replace("R$", ""))
        if val_clean == 0: return None

        tipo = "DEBITO" if eh_negativo else "CREDITO"
        valor_final = -abs(val_clean) if eh_negativo else abs(val_clean)

        desc = texto.replace(val_data, "")
        for m in matches_valor: desc = desc.replace(m.group(0), "")

        desc = re.sub(r'\s+[CD]\s*$', '', desc).strip()
        desc = re.sub(r'\d{2}/\d{2}\s+\d{2}:\d{2}', '', desc)
        desc = re.sub(r'\b\d{6,}\b', '', desc)
        desc = re.sub(r'\s+', ' ', desc).strip()

        if not desc: desc = "HISTORICO NAO IDENTIFICADO"

        return {"DATA": val_data, "HISTORICO": self.remover_acentos(desc).upper(), "VALOR": valor_final, "TIPO": tipo}

    def processar(self, arquivo, log_func):
        log_func(f"Lendo CAIXA V2 (Horizontal): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            linhas_texto = []
            with pdfplumber.open(caminho_pdf) as pdf:
                for page in pdf.pages:
                    texto = page.extract_text()
                    if texto: linhas_texto.extend(texto.split('\n'))

            registros, buffer_atual = [], None

            for linha in linhas_texto:
                linha = linha.strip()
                if not linha: continue

                if re.match(r'^\d{2}/\d{2}/\d{4}', linha):
                    if buffer_atual:
                        res = self._processar_transacao(buffer_atual)
                        if res: registros.append(res)
                    buffer_atual = {'linhas': [linha]}
                elif buffer_atual:
                    buffer_atual['linhas'].append(linha)

            if buffer_atual:
                res = self._processar_transacao(buffer_atual)
                if res: registros.append(res)

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    return self.salvar_arquivo(df, os.path.splitext(arquivo)[0] + "_V2_HORIZ")
            return None
        except Exception as e:
            log_func(f"Erro ao processar V2 Horiz {arquivo}: {e}", "erro")
            return None


# ==========================================
# CLASSE 3: CAIXA V2 VERTICAL (Atualizada e Limpa)
# ==========================================
class CaixaProcessorV2Vertical(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "CAIXA_V2_VERT (em manutenção)"

    def _processar_transacao(self, buffer):
        if not buffer: return None

        texto = " ".join(buffer['linhas']).replace('\n', ' ')
        texto = re.sub(r'\s+', ' ', texto).strip()

        if "SALDO DIA" in texto.upper() or "SALDO ANTERIOR" in texto.upper():
            return None

        match_data = re.search(r'(\d{2}/\d{2}/\d{4})', texto)
        if not match_data: return None
        val_data = match_data.group(1)

        # Procura os valores (O 1º vai ser a transação por causa do layout=True)
        matches_valor = list(re.finditer(r'(-?\s*R\$\s*[\d\.,]+)', texto))
        if not matches_valor: return None

        val_str_raw = matches_valor[0].group(1)
        eh_negativo = "-" in val_str_raw

        val_clean = self.limpar_valor(val_str_raw.replace("-", "").replace("R$", ""))
        if val_clean == 0: return None

        # Filtro Inteligente: Garante o débito mesmo se o "-" sumir no PDF
        desc_temp = texto.upper()
        palavras_debito = ["DEBITO", "DEB ", "CONSORCIO", "MENSALIDADE", "TARIFA", "PAGAMENTO", "SAQUE", "CHEQUE",
                           "ENCARGOS", "IOF", "PIX ENVIADO", "PREST."]
        if any(p in desc_temp for p in palavras_debito):
            eh_negativo = True

        palavras_credito = ["RESGATE", "RECEBIDO", "CREDITO", "CRED ", "PIX RECEBIDO"]
        if any(p in desc_temp for p in palavras_credito):
            eh_negativo = False

        tipo = "DEBITO" if eh_negativo else "CREDITO"
        valor_final = -abs(val_clean) if eh_negativo else abs(val_clean)

        desc = texto.replace(val_data, "")
        for m in matches_valor: desc = desc.replace(m.group(0), "")

        # Limpeza pesada para tirar lixo do Vertical
        desc = re.sub(r'\s+[CD]\s*$', '', desc).strip()
        desc = re.sub(r'\b[CD]\b', '', desc)  # Caça as letras C/D perdidas
        desc = re.sub(r'\d{2}/\d{2}\s+\d{2}:\d{2}', '', desc)
        desc = re.sub(r'\b\d{6,}\b', '', desc)
        desc = re.sub(r'^- ', '', desc).strip()
        desc = re.sub(r'\s+', ' ', desc).strip()

        if not desc: desc = "HISTORICO NAO IDENTIFICADO"

        return {"DATA": val_data, "HISTORICO": self.remover_acentos(desc).upper(), "VALOR": valor_final, "TIPO": tipo}

    def processar(self, arquivo, log_func):
        log_func(f"Lendo CAIXA V2 (Vertical): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            linhas_texto = []
            with pdfplumber.open(caminho_pdf) as pdf:
                for page in pdf.pages:
                    # O layout=True impede que o Saldo e o Valor se juntem
                    texto = page.extract_text(layout=True)
                    if texto: linhas_texto.extend(texto.split('\n'))

            registros, buffer_atual = [], None

            for linha in linhas_texto:
                linha = linha.strip()
                if not linha: continue

                if re.match(r'^\d{2}/\d{2}/\d{4}', linha):
                    if buffer_atual:
                        res = self._processar_transacao(buffer_atual)
                        if res: registros.append(res)
                    buffer_atual = {'linhas': [linha]}
                elif buffer_atual:
                    buffer_atual['linhas'].append(linha)

            if buffer_atual:
                res = self._processar_transacao(buffer_atual)
                if res: registros.append(res)

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    return self.salvar_arquivo(df, os.path.splitext(arquivo)[0] + "_V2_VERT")
            return None
        except Exception as e:
            log_func(f"Erro ao processar V2 Vert {arquivo}: {e}", "erro")
            return None


# ==========================================
# CLASSE 4: CAIXA V3 (Tabelado D/C final)
# ==========================================
class CaixaProcessorV3(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "CAIXA_V3"

    def _processar_transacao(self, buffer):
        if not buffer: return None
        texto = " ".join(buffer['linhas']).replace('\n', ' ')
        texto = re.sub(r'\s+', ' ', texto).strip()

        if "SALDO" in texto.upper() and ("DIA" in texto.upper() or "ANTERIOR" in texto.upper()): return None

        match_data = re.search(r'(\d{2}/\d{2}/\d{4})', texto)
        if not match_data: return None
        val_data = match_data.group(1)

        matches_valor = list(re.finditer(r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*([DC])', texto))
        if not matches_valor: return None

        transacao = matches_valor[0]
        val_str_raw = transacao.group(1)
        tipo_letra = transacao.group(2)

        val_clean = self.limpar_valor(val_str_raw)
        if val_clean == 0: return None

        tipo = "DEBITO" if tipo_letra == "D" else "CREDITO"
        valor_final = -abs(val_clean) if tipo == "DEBITO" else abs(val_clean)

        desc = texto.replace(val_data, "")
        for m in matches_valor: desc = desc.replace(m.group(0), "")

        desc = re.sub(r'\b\d{6,}\b', '', desc)
        desc = re.sub(r'\d{2}:\d{2}:\d{2}', '', desc)
        desc = re.sub(r'\s+', ' ', desc).strip()

        if not desc: desc = "HISTORICO NAO IDENTIFICADO"

        return {"DATA": val_data, "HISTORICO": self.remover_acentos(desc).upper(), "VALOR": valor_final, "TIPO": tipo}

    def processar(self, arquivo, log_func):
        log_func(f"Lendo CAIXA V3 (Tabelado D/C): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            linhas_texto = []
            with pdfplumber.open(caminho_pdf) as pdf:
                for page in pdf.pages:
                    texto = page.extract_text()
                    if texto: linhas_texto.extend(texto.split('\n'))

            registros, buffer_atual = [], None

            for linha in linhas_texto:
                linha = linha.strip()
                if not linha: continue

                if re.match(r'^\d{2}/\d{2}/\d{4}', linha):
                    if buffer_atual:
                        res = self._processar_transacao(buffer_atual)
                        if res: registros.append(res)
                    buffer_atual = {'linhas': [linha]}
                elif buffer_atual:
                    buffer_atual['linhas'].append(linha)

            if buffer_atual:
                res = self._processar_transacao(buffer_atual)
                if res: registros.append(res)

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    return self.salvar_arquivo(df, os.path.splitext(arquivo)[0] + "_V3")
            return None
        except Exception as e:
            log_func(f"Erro ao processar V3 {arquivo}: {e}", "erro")
            return None